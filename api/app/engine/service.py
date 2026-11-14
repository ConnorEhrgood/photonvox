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

import hashlib
import json
import logging
import uuid
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from sqlalchemy import delete, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app import audit, crypto
from app.config import settings
from app.compiler.compile import CompileError, Context, compile_plan
from app.document.model import PhoneSystem as Document
from app.engine import fusionpbx, instance as instance_settings, publish, upstreams, writer
from app.engine.compare import norm
from app.engine.agent import Agent, HttpAgent
from app.speech import DEFAULT_VOICE, Speech, audio_key, file_name
from app.speech.google import GoogleSpeech
from app.models import (EmergencyLocation, EngineObject, EngineSecret, HeldNumber, PbxInstance, PhoneSystem, PhoneSystemVersion, Site, SpeechAudio, utcnow)

Connect = Callable[[PbxInstance], Tuple[Engine, Agent]]
log = logging.getLogger("photonvox.publish")


class NoAgent:
    """An instance without vox-agent (the live engine while its domains are only adopted, decision 32): nothing to clear is fine; anything else
    the agent would do is refused, and a publish that would need the cache cleared is rolled back before it commits (app/engine/publish.py)."""

    available = False

    def clear_cache(self, entries: Any) -> None:
        if entries:
            raise RuntimeError("this instance has no vox-agent: a change that needs the engine's cache cleared cannot be published to it yet")

    def __getattr__(self, name: str) -> Any:
        def refuse(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError(f"this instance has no vox-agent ({name})")
        return refuse


def connect(instance: PbxInstance) -> Tuple[Engine, Agent]:
    """The instance's engine database (as PhotonVox's adapter role) and its agent (NoAgent when the instance has none)."""
    from sqlalchemy import create_engine
    eng = create_engine(crypto.unseal(instance.database_url_sealed), pool_pre_ping=True, connect_args={"client_encoding": "utf8"})
    a = instance.agent or {}
    if a.get("kind") != "http" or not instance.agent_secret_sealed:
        return eng, NoAgent()       # type: ignore[return-value]
    return eng, HttpAgent(a["url"], crypto.unseal(instance.agent_secret_sealed))


def apply_instance(instance: PbxInstance, connect: Connect = connect) -> Dict[str, Any]:
    """Put the instance's own settings on its engine: its upstreams (gateways and providers entries) and its outgoing mail, in one transaction,
    then have vox-agent clear the cache, stop removed gateways, rescan and reload the access lists. An instance whose upstreams are its own,
    hand-built (the live engine, decision 32), has nothing to apply: refused, so its gateways are never touched."""
    if not instance.upstreams:
        raise ValueError(f"instance {instance.name}: its upstreams are its own (hand-built); PhotonVox applies nothing to it")
    eng, agent = connect(instance)
    with eng.begin() as conn:
        up = upstreams.write_upstreams(conn, str(instance.id), instance.hostname,
                                       [upstreams.Upstream(u["key"], u["proxy"], tuple(u["addresses"])) for u in instance.upstreams])
        if instance.email.get("host"):
            instance_settings.write_email(conn, str(instance.id), instance.email, crypto.unseal(instance.email_password_sealed)
                                          if instance.email_password_sealed else "")
    agent.clear_cache(up["cache"])
    agent.rescan(up["rescan"], up["kill"])
    agent.reload_acl()
    return {"gateways": sorted(up["gateways"]), "removed": len(up["kill"]), "email": bool(instance.email.get("host"))}


def context(db: Session, ps: PhoneSystem, instance: PbxInstance) -> Context:
    """What the compiler needs from outside the document: the sites' time zones (the directory copy), the validated emergency locations, the
    instance's upstreams in Photon's order and 911's upstream."""
    sites = db.execute(select(Site).where(Site.tenant_id == ps.tenant_id)).scalars().all()
    locs = db.execute(select(EmergencyLocation).where(EmergencyLocation.tenant_id == ps.tenant_id, EmergencyLocation.status == "validated")).scalars()
    validated: Dict[str, set] = {}
    for loc in locs:
        validated.setdefault(str(loc.site_id), set()).add(loc.key)
    assigned = set(db.execute(select(HeldNumber.number).where(HeldNumber.tenant_id == ps.tenant_id)).scalars())
    return Context(domain=ps.domain_name, timezones={str(s.id): s.timezone for s in sites}, upstreams=dict(instance.routing or {}),
                   emergency_gateway=instance.emergency_upstream, validated_locations=validated, assigned_numbers=assigned,
                   adopted=ps.adoption is not None, protected=bool((ps.adoption or {}).get("protected")),
                   dial_formats=dict(instance.dial_formats or {}))


def get_speech() -> Optional[Speech]:
    """The text-to-speech provider (decision 30), or None when none is configured (menus then answer without a spoken greeting)."""
    return GoogleSpeech(settings.google_tts_api_key) if settings.google_tts_api_key else None


def adoption(ps: PhoneSystem) -> Optional[fusionpbx.Adoption]:
    a = ps.adoption
    if not a:
        return None
    return fusionpbx.Adoption(objects={k: [tuple(x) for x in v] for k, v in a["objects"].items()}, rows=a["rows"], ids=a["ids"],
                              meanings=a["meanings"], fresh=a.get("fresh") or {}, protected=bool(a.get("protected")),
                              retire=list(a.get("retire") or []))


def target(ps: PhoneSystem, instance: PbxInstance, speech_on: bool = False) -> fusionpbx.Target:
    gateways = {u["key"]: upstreams.gateway_uuid(str(instance.id), u["key"]) for u in instance.upstreams}
    gateways.update(instance.own_gateways or {})            # the engine's own gateways, by their ids (decision 32)
    return fusionpbx.Target(str(ps.id), str(ps.domain_uuid), gateways, speech_on, adoption(ps))


def speak(db: Session, provider: Speech, agent: Agent, plan: Mapping[str, Any]) -> int:
    """Every greeting of the plan spoken (from the cache when the same words were spoken in the same voice before) and written to the engine.
    Returns how many were new (paid for)."""
    voice, new = plan.get("voice", DEFAULT_VOICE), 0
    for m in plan["ivr_menus"]:
        if m["greeting"].startswith("recording:"):
            continue                    # a recording already on the engine: nothing to speak
        key = audio_key(m["greeting"], voice)
        cached = db.get(SpeechAudio, key)
        if cached is None:
            cached = SpeechAudio(key=key, voice=voice, characters=len(m["greeting"]), audio=provider.synthesize(m["greeting"], voice))
            db.add(cached)
            new += 1
        agent.put_sound(plan["domain"], file_name(m["greeting"], voice), cached.audio)
    return new


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
    """Write a plan (or, with None, remove everything this phone system wrote) and record what is now on the engine. Greetings are spoken and
    put on the engine first, so no menu ever names a file that is not there."""
    provider = get_speech()
    if plan is not None and provider is not None and plan["ivr_menus"]:
        speak(db, provider, agent, plan)
    t = target(ps, instance, provider is not None)
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
        # An adopted domain has none of PhotonVox's check gates (decision 32): its first publish is proven by the compare and by test calls.
        t = target(ps, instance, get_speech() is not None)
        results = [] if plan.get("adopted") and not plan.get("protected") else run_checks(agent, plan, t) + fusionpbx.emergency_read(plan, t)
    except Exception as e:  # noqa: BLE001 - the engine refused or failed: record it, put the previous version back
        db.rollback()
        # The details (SQL, addresses) go to the log for Photon staff; integrators read a sentence (security review L4).
        log.warning("publish of %s version %s failed: %s: %s", ps.id, v.number, type(e).__name__, e)
        return _fail(db, ps, v, _plain(e), (eng, agent))
    v.check = {"results": results, "at": utcnow().isoformat()}
    if not all(r["ok"] for r in results):
        bad = [r for r in results if not r["ok"]]
        return _fail(db, ps, v, f"{len(bad)} of {len(results)} checks failed; the first: {bad[0]['kind']} {bad[0]['number']}", (eng, agent))
    for old in db.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.phone_system_id == ps.id, PhoneSystemVersion.state == "ready")).scalars():
        old.state = "superseded"
    v.state, v.published_at = "ready", utcnow()
    ps.published_version, ps.status, ps.drift = v.number, "ready", {}
    from app.emergency import sync_numbers     # 911 registrations follow what is published (decision 31)
    try:
        if plan.get("adopted"):
            raise _Kept()           # an adopted domain's 911 stays hand-built: no registrations or carrier requests until the protections version
        with db.begin_nested():
            sync_numbers(db, ps, v.document)
    except _Kept:
        pass
    except Exception:  # noqa: BLE001 - the engine is published; a 911 bookkeeping error must not leave it "publishing"
        log.exception("911 registrations for %s not updated", ps.id)
        v.note = (v.note + "; " if v.note else "") + "911 registrations not updated (Photon has been told)"
    audit.record(db, actor_id=v.created_by, actor_label=v.created_by_label or "PhotonVox", actor_source="direct", action="phone_system.published",
                 tenant_id=ps.tenant_id, target_type="phone_system", target_id=ps.id, version=v.number, checks=len(results))
    db.commit()
    return "ready"


class _Kept(Exception):
    pass


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
            log.warning("restoring %s after a failed publish failed too: %s: %s", ps.id, type(e).__name__, e)
            restored = "putting the previous version back failed too (Photon has been told)"
    v.state, v.error, ps.status = "failed", f"{error}; {restored}" if restored else error, "failed"
    audit.record(db, actor_id=v.created_by, actor_label=v.created_by_label or "PhotonVox", actor_source="direct", action="phone_system.publish_failed",
                 tenant_id=ps.tenant_id, target_type="phone_system", target_id=ps.id, version=v.number, error=error[:300], restored=restored)
    db.commit()
    return "failed"


def _plain(e: Exception) -> str:
    """A failed publish in a sentence an integrator can act on, with nothing of the engine's internals."""
    text_ = str(e)
    if isinstance(e, ValueError) and "already answered by another phone system" in text_:
        return "publish failed: a number is already in use on the engine by another organization (Photon has been told)"
    return "publish failed: the engine did not take the change (Photon has been told)"


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
        cols = sorted({c for r in want.values() for c in r if not isinstance(r[c], fusionpbx.Secret) and c not in fusionpbx.AUDIT})
        rows = conn.execute(text(f"select {', '.join(cols)} from {table} where {fusionpbx.KEYS[table]} = any(cast(:ids as uuid[])) "
                                 "and domain_uuid = :d"), {"ids": list(want), "d": domain_uuid}).mappings().all()
        have = {str(r[fusionpbx.KEYS[table]]): r for r in rows}
        for key, w in want.items():
            h = have.get(key)
            if h is None:
                missing.append({"table": table, "uuid": key})
                continue
            diff = [c for c in cols if c in w and not isinstance(w.get(c), fusionpbx.Secret) and norm(h[c]) != norm(w.get(c))]
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


def watch_extras(conn: Any, extras: Mapping[str, str], domain_uuid: str) -> List[Dict[str, Any]]:
    """An adopted domain's hand-built rows (not PhotonVox's, never written): each one's columns now against its hash when adopted. A change or
    a removal is reported (a hand edit); PhotonVox does not put them back."""
    out: List[Dict[str, Any]] = []
    by: Dict[str, Dict[str, str]] = {}
    for k, h in extras.items():
        table, uid = k.split(":", 1)
        by.setdefault(table, {})[uid] = h
    for table, want in sorted(by.items()):
        key = fusionpbx.KEYS[table]
        cols = [r[0] for r in conn.execute(text("select column_name from information_schema.columns where table_schema = current_schema() and table_name = :t "
                                                "and has_column_privilege(current_user, quote_ident(table_schema) || '.' || table_name, column_name, 'select') "
                                                "order by ordinal_position"), {"t": table})]
        cols = [c for c in cols if c not in fusionpbx.AUDIT and c not in SECRET_COLUMNS]
        # A dial plan's details often carry no domain (FusionPBX's screens leave it empty): they are found by their own ids, which the adoption
        # took from the domain's dial plans.
        scope = "" if table == "v_dialplan_details" else " and domain_uuid = :d"
        rows = conn.execute(text(f"select {', '.join(cols)} from {table} where {key} = any(cast(:ids as uuid[])){scope}"),
                            {"ids": list(want), "d": domain_uuid}).mappings().all()
        have = {str(r[key]): extra_hash(dict(r)) for r in rows}
        for uid, h in want.items():
            if uid not in have:
                out.append({"table": table, "uuid": uid, "kind": "removed"})
            elif have[uid] != h:
                out.append({"table": table, "uuid": uid, "kind": "changed"})
    return out


SECRET_COLUMNS = {"password", "voicemail_password", "ivr_menu_pin_number"}


def extra_hash(row: Mapping[str, Any]) -> str:
    """A hand-built row's fingerprint: every column but FusionPBX's bookkeeping and the secrets, normalized."""
    body = {k: norm(v) for k, v in row.items() if k not in fusionpbx.AUDIT and k not in SECRET_COLUMNS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def check_drift(db: Session, ps: PhoneSystem, connect: Connect = connect) -> Dict[str, Any]:
    """Compare the engine with the running version and record it on the phone system; a change or a missing row marks it "changed"."""
    v = db.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.phone_system_id == ps.id, PhoneSystemVersion.number == ps.published_version)).scalar_one()
    instance = db.get(PbxInstance, ps.instance_id)
    plan = compile_plan(Document.model_validate(v.document), context(db, ps, instance))
    b = fusionpbx.build(plan, target(ps, instance, get_speech() is not None))
    eng, _agent = connect(instance)
    with eng.connect() as conn:
        found = compare(conn, b, str(ps.domain_uuid))
        if ps.adoption and ps.adoption.get("extras"):
            found["hand_built_changed"] = watch_extras(conn, ps.adoption["extras"], str(ps.domain_uuid))
    result = {"checked_at": utcnow().isoformat(), "version": v.number, **found}
    ps.drift = result
    if ps.status in ("ready", "changed"):
        ps.status = "changed" if (found["changed"] or found["missing"] or found.get("hand_built_changed")) else "ready"
    db.commit()
    return result


def check_all_drift(db: Session, connect: Connect = connect) -> int:
    n = 0
    for ps in db.execute(select(PhoneSystem).where(PhoneSystem.status.in_(("ready", "changed")))).scalars().all():
        check_drift(db, ps, connect)
        n += 1
    return n
