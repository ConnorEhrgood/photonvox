"""Publishing phone systems, checking them and finding hand edits: the worker's side of Step 3 (ARCHITECTURE §5, §8). Runs in a system session.

- **publish_version:** compile the version's document, write it to its engine, record what was written (`engine_object`) and the secrets the
  engine was given (`engine_secret`, sealed), then the **post-publish check**: one synthetic call per inbound number and through the emergency
  route's selection (app/engine/fusionpbx.py `checks`). All pass: the version is ready. Any fails, or the write fails: the version is failed and
  the previous ready version is published again (or, with none, what was written is removed).
- **restore:** undo is a new version holding an earlier version's document.
- **check_drift:** what is on the engine now against what the running version wrote; a difference marks the phone system "changed" until the
  next publish puts PhotonVox's version back (decision 5).

Engines are reached through `connect(instance) -> (sqlalchemy Engine, Agent)`; tests pass their own.
"""
from __future__ import annotations

import decimal
import uuid
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from sqlalchemy import delete, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app import audit, crypto
from app.compiler.compile import CompileError, Context, compile_plan
from app.document.model import PhoneSystem as Document
from app.engine import fusionpbx, publish, upstreams, writer
from app.engine.agent import Agent, HttpAgent
from app.models import (EmergencyLocation, EngineObject, EngineSecret, PbxInstance, PhoneSystem, PhoneSystemVersion, Site, utcnow)

Connect = Callable[[PbxInstance], Tuple[Engine, Agent]]


def connect(instance: PbxInstance) -> Tuple[Engine, Agent]:
    """The instance's engine database (as PhotonVox's adapter role) and its agent."""
    from sqlalchemy import create_engine
    eng = create_engine(crypto.unseal(instance.database_url_sealed), pool_pre_ping=True, connect_args={"client_encoding": "utf8"})
    a = instance.agent or {}
    if a.get("kind") != "http" or not instance.agent_secret_sealed:
        raise RuntimeError(f"instance {instance.name}: no agent configured")
    return eng, HttpAgent(a["url"], crypto.unseal(instance.agent_secret_sealed))


def context(db: Session, ps: PhoneSystem, instance: PbxInstance) -> Context:
    """What the compiler needs from outside the document: the sites' time zones (the directory copy), the validated emergency locations, the
    instance's upstreams in Photon's order and 911's upstream."""
    sites = db.execute(select(Site).where(Site.tenant_id == ps.tenant_id)).scalars().all()
    locs = db.execute(select(EmergencyLocation).where(EmergencyLocation.tenant_id == ps.tenant_id, EmergencyLocation.status == "validated")).scalars()
    validated: Dict[str, set] = {}
    for loc in locs:
        validated.setdefault(str(loc.site_id), set()).add(loc.key)
    return Context(domain=ps.domain_name, timezones={str(s.id): s.timezone for s in sites}, upstreams=dict(instance.routing or {}),
                   emergency_gateway=instance.emergency_upstream, validated_locations=validated)


def target(ps: PhoneSystem, instance: PbxInstance) -> fusionpbx.Target:
    return fusionpbx.Target(str(ps.id), str(ps.domain_uuid), {u["key"]: upstreams.gateway_uuid(str(instance.id), u["key"]) for u in instance.upstreams})


def manifest(db: Session, ps: PhoneSystem) -> List[Dict[str, str]]:
    rows = db.execute(select(EngineObject).where(EngineObject.phone_system_id == ps.id)).scalars()
    return [{"table": r.table_name, "uuid": str(r.object_uuid), "hash": r.hash} for r in rows]


def _record(db: Session, ps: PhoneSystem, res: writer.Result) -> None:
    db.execute(delete(EngineObject).where(EngineObject.phone_system_id == ps.id))
    for m in res.manifest:
        db.add(EngineObject(phone_system_id=ps.id, table_name=m["table"], object_uuid=uuid.UUID(m["uuid"]), tenant_id=ps.tenant_id, hash=m["hash"]))
    for label, value in res.new_secrets.items():
        db.merge(EngineSecret(phone_system_id=ps.id, label=label, tenant_id=ps.tenant_id, sealed=crypto.seal(value)))


def run_checks(agent: Agent, plan: Mapping[str, Any], t: fusionpbx.Target) -> List[Dict[str, Any]]:
    out = []
    for c in fusionpbx.checks(plan, t):
        got = agent.check(c["kind"], c["number"], plan["domain"], t.domain_uuid, uuid.uuid4().hex)
        out.append({**c, "got": got, "ok": got in c["expect"]})
    return out


def _write(db: Session, ps: PhoneSystem, instance: PbxInstance, plan: Optional[Mapping[str, Any]], eng: Engine, agent: Agent) -> writer.Result:
    """Write a plan (or, with None, remove everything this phone system wrote) and record what is now on the engine."""
    t = target(ps, instance)
    if plan is None:
        with eng.begin() as conn:
            res = writer.write(conn, fusionpbx.Build(), t.domain_uuid, manifest(db, ps))
        agent.clear_cache(res.cache)
    else:
        res = publish.publish(eng, agent, plan, t, manifest(db, ps))
    _record(db, ps, res)
    return res


def publish_version(db: Session, version_id: uuid.UUID, connect: Connect = connect) -> str:
    """Publish one queued version; returns its final state. Commits as it goes, so a crash leaves an honest record."""
    v = db.get(PhoneSystemVersion, version_id)
    ps = db.get(PhoneSystem, v.phone_system_id)
    instance = db.get(PbxInstance, ps.instance_id)
    v.state, ps.status = "publishing", "publishing"
    db.commit()
    try:
        plan = compile_plan(Document.model_validate(v.document), context(db, ps, instance))
    except CompileError as e:
        return _fail(db, ps, v, f"not publishable: {e}", None)
    eng, agent = connect(instance)
    try:
        _write(db, ps, instance, plan, eng, agent)
        db.commit()
        results = run_checks(agent, plan, target(ps, instance))
    except Exception as e:  # noqa: BLE001 - the engine refused or failed: record it, put the previous version back
        db.rollback()
        return _fail(db, ps, v, f"publish failed: {type(e).__name__}: {e}"[:2000], (eng, agent))
    v.check = {"results": results, "at": utcnow().isoformat()}
    if not all(r["ok"] for r in results):
        bad = [r for r in results if not r["ok"]]
        return _fail(db, ps, v, f"{len(bad)} of {len(results)} checks failed; the first: {bad[0]['kind']} {bad[0]['number']}", (eng, agent))
    for old in db.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.phone_system_id == ps.id, PhoneSystemVersion.state == "ready")).scalars():
        old.state = "superseded"
    v.state, v.published_at = "ready", utcnow()
    ps.published_version, ps.status, ps.drift = v.number, "ready", {}
    from app.emergency import sync_numbers     # 911 registrations follow what is published (decision 31)
    sync_numbers(db, ps, v.document)
    audit.record(db, actor_id=v.created_by, actor_label=v.created_by_label or "PhotonVox", actor_source="direct", action="phone_system.published",
                 tenant_id=ps.tenant_id, target_type="phone_system", target_id=ps.id, version=v.number, checks=len(results))
    db.commit()
    return "ready"


def _fail(db: Session, ps: PhoneSystem, v: PhoneSystemVersion, error: str, engine: Optional[Tuple[Engine, Agent]]) -> str:
    previous = db.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.phone_system_id == ps.id, PhoneSystemVersion.state == "ready")
                          .order_by(PhoneSystemVersion.number.desc())).scalars().first()
    restored = ""
    if engine is not None:
        instance = db.get(PbxInstance, ps.instance_id)
        try:
            plan = compile_plan(Document.model_validate(previous.document), context(db, ps, instance)) if previous else None
            _write(db, ps, instance, plan, *engine)
            restored = f"version {previous.number} restored" if previous else "removed what it had written"
        except Exception as e:  # noqa: BLE001
            db.rollback()       # (this also discards anything set on the rows above; the outcome is set below, after it)
            restored = f"restoring failed too: {type(e).__name__}: {e}"[:500]
    v.state, v.error, ps.status = "failed", f"{error}; {restored}" if restored else error, "failed"
    audit.record(db, actor_id=v.created_by, actor_label=v.created_by_label or "PhotonVox", actor_source="direct", action="phone_system.publish_failed",
                 tenant_id=ps.tenant_id, target_type="phone_system", target_id=ps.id, version=v.number, error=error[:300], restored=restored)
    db.commit()
    return "failed"


def queue(db: Session, ps: PhoneSystem, document: Mapping[str, Any], who_id: Optional[uuid.UUID], who_label: str, note: str = "") -> PhoneSystemVersion:
    """A new version to publish (the API's side). Numbered after the last one."""
    last = db.execute(select(PhoneSystemVersion.number).where(PhoneSystemVersion.phone_system_id == ps.id)
                      .order_by(PhoneSystemVersion.number.desc())).scalars().first() or 0
    v = PhoneSystemVersion(tenant_id=ps.tenant_id, phone_system_id=ps.id, number=last + 1, document=dict(document), note=note[:200],
                           created_by=who_id, created_by_label=who_label[:320])
    db.add(v)
    return v


def publish_queued(db: Session, connect: Connect = connect) -> int:
    """The worker's job: publish queued versions, oldest first (a phone system's versions in order)."""
    done = 0
    for vid in db.execute(select(PhoneSystemVersion.id).where(PhoneSystemVersion.state == "queued").order_by(PhoneSystemVersion.created_at)).scalars().all():
        publish_version(db, vid, connect)
        done += 1
    return done


# ---- hand edits (drift) ----

def _norm(v: Any) -> Any:
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, decimal.Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


# Kinds of object a person may add by hand in FusionPBX's screens; any in the domain that PhotonVox did not write are listed (and left alone).
HAND_MADE = {"v_extensions": "extension", "v_ring_groups": "ring_group_extension", "v_ivr_menus": "ivr_menu_name", "v_destinations": "destination_number"}


def compare(conn: Any, b: fusionpbx.Build, domain_uuid: str) -> Dict[str, List[Dict[str, Any]]]:
    """What differs on the engine from a build: PhotonVox's columns of each row it wrote (changed, or the row missing), the switched-off features,
    and objects added by hand (listed, never touched)."""
    changed: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    extra: List[Dict[str, Any]] = []
    for table in fusionpbx.TABLES:
        want = {r[fusionpbx.KEYS[table]]: r for r in b.rows[table]}
        if not want:
            continue
        cols = sorted({c for r in want.values() for c in r if not isinstance(r[c], fusionpbx.Secret)})
        rows = conn.execute(text(f"select {', '.join(cols)} from {table} where {fusionpbx.KEYS[table]} = any(cast(:ids as uuid[])) "
                                 "and domain_uuid = :d"), {"ids": list(want), "d": domain_uuid}).mappings().all()
        have = {str(r[fusionpbx.KEYS[table]]): r for r in rows}
        for key, w in want.items():
            h = have.get(key)
            if h is None:
                missing.append({"table": table, "uuid": key})
                continue
            diff = [c for c in cols if not isinstance(w.get(c), fusionpbx.Secret) and _norm(h[c]) != w.get(c)]
            if diff:
                changed.append({"table": table, "uuid": key, "columns": diff})
    for table, label in HAND_MADE.items():
        ours = [r[fusionpbx.KEYS[table]] for r in b.rows[table]]
        for r in conn.execute(text(f"select {fusionpbx.KEYS[table]} as id, {label} as label from {table} where domain_uuid = :d "
                                   f"and not ({fusionpbx.KEYS[table]} = any(cast(:ids as uuid[])))"), {"d": domain_uuid, "ids": ours}):
            extra.append({"table": table, "uuid": str(r.id), "label": r.label})
    for app_uuid, enabled in b.features.items():
        for r in conn.execute(text("select dialplan_uuid, dialplan_name, dialplan_enabled from v_dialplans where domain_uuid = :d and app_uuid = :a"),
                              {"d": domain_uuid, "a": app_uuid}):
            if bool(r.dialplan_enabled) != enabled:
                changed.append({"table": "v_dialplans", "uuid": str(r.dialplan_uuid), "columns": ["dialplan_enabled"], "name": r.dialplan_name})
    return {"changed": changed, "missing": missing, "extra": extra}


def check_drift(db: Session, ps: PhoneSystem, connect: Connect = connect) -> Dict[str, Any]:
    """Compare the engine with the running version and record it on the phone system; a change or a missing row marks it "changed"."""
    v = db.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.phone_system_id == ps.id, PhoneSystemVersion.number == ps.published_version)).scalar_one()
    instance = db.get(PbxInstance, ps.instance_id)
    plan = compile_plan(Document.model_validate(v.document), context(db, ps, instance))
    b = fusionpbx.build(plan, target(ps, instance))
    eng, _agent = connect(instance)
    with eng.connect() as conn:
        found = compare(conn, b, str(ps.domain_uuid))
    result = {"checked_at": utcnow().isoformat(), "version": v.number, **found}
    ps.drift = result
    if ps.status in ("ready", "changed"):
        ps.status = "changed" if (found["changed"] or found["missing"]) else "ready"
    db.commit()
    return result


def check_all_drift(db: Session, connect: Connect = connect) -> int:
    n = 0
    for ps in db.execute(select(PhoneSystem).where(PhoneSystem.status.in_(("ready", "changed")))).scalars().all():
        check_drift(db, ps, connect)
        n += 1
    return n
