"""Taking a hand-built domain over in place (decision 32, ARCHITECTURE §17): read it, import it, prove the first publish changes nothing, keep the
adoption. Photon staff only (Platform → Instances). The publish that follows is an ordinary one (app/engine/service.py), which for an adopted
domain writes nothing that is already there, runs no synthetic check and leaves 911 registrations alone.

`read_domain` is the same read as engine/live/export_domain.py (which runs on its own where the app is not installed): every column the login may
read of the domain's rows, the dial plans of its own, public and global contexts, the gateways, never a secret (a deny list on top of the grants).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import decimal
import uuid
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.compiler.compile import CompileError, Context, compile_plan
from app.document.model import PhoneSystem as Document
from app.engine import compare, fusionpbx, importer
from app.models import HeldNumber, PbxInstance, PhoneSystem, Site

DENY = {
    "v_extensions": {"password"}, "v_voicemails": {"voicemail_password"}, "v_ivr_menus": {"ivr_menu_pin_number"},
    "v_gateways": {"username", "password", "auth_username"}, "v_recordings": {"recording_base64"},
    "v_users": {"password", "salt", "api_key", "user_totp_secret", "contact_uuid", "user_email"},
}
DOMAIN_TABLES = ("v_extensions", "v_extension_users", "v_voicemails", "v_destinations", "v_ivr_menus", "v_ivr_menu_options", "v_ring_groups",
                 "v_ring_group_destinations", "v_recordings", "v_users")


class TakeoverError(ValueError):
    pass


def _plain(v: Any) -> Any:
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    if isinstance(v, (uuid.UUID, decimal.Decimal)):
        return str(v)
    return v


def _select(conn: Any, table: str, where: str, args: Mapping[str, Any]) -> Optional[List[Dict[str, Any]]]:
    cols = [r[0] for r in conn.execute(text("select column_name from information_schema.columns where table_schema = current_schema() and table_name = :t "
                                            "and has_column_privilege(current_user, quote_ident(table_schema) || '.' || table_name, column_name, 'select') "
                                            "order by ordinal_position"), {"t": table})]
    cols = [c for c in cols if c not in DENY.get(table, set())]
    if not cols:
        return None
    rows = conn.execute(text(f"select {', '.join(chr(34) + c + chr(34) for c in cols)} from {table} where {where}"), dict(args)).mappings()
    return [{k: _plain(v) for k, v in r.items()} for r in rows]


def read_domain(conn: Any, domain_name: str) -> Dict[str, Any]:
    found = conn.execute(text("select domain_uuid, domain_name, domain_enabled from v_domains where domain_name = :n"), {"n": domain_name}).first()
    if found is None:
        raise TakeoverError(f"the engine has no domain {domain_name!r}")
    d = str(found.domain_uuid)
    out: Dict[str, Any] = {"domain": {"domain_uuid": d, "domain_name": found.domain_name, "domain_enabled": found.domain_enabled}, "tables": {}}
    for t in DOMAIN_TABLES:
        out["tables"][t] = _select(conn, t, "domain_uuid = cast(:d as uuid)", {"d": d})
    out["tables"]["v_dialplans"] = _select(conn, "v_dialplans", "domain_uuid = cast(:d as uuid) or domain_uuid is null or dialplan_context in ('public', 'global')", {"d": d})
    ids = [r["dialplan_uuid"] for r in out["tables"]["v_dialplans"] or []]
    out["tables"]["v_dialplan_details"] = _select(conn, "v_dialplan_details", "dialplan_uuid = any(cast(:ids as uuid[]))", {"ids": ids})
    out["tables"]["v_gateways"] = _select(conn, "v_gateways", "true", {})
    return out


def prove(export: Mapping[str, Any], ps_id: str, site_id: str, upstream: str, timezone: str = "America/New_York") -> Dict[str, Any]:
    """Import, compile, and compare: the adoption to keep, the document, and the proof. Raises when the first publish would change anything."""
    imp = importer.import_domain(export, site_id)
    doc = Document.model_validate(imp.document)
    D = export["domain"]["domain_uuid"]
    ctx = Context(domain=export["domain"]["domain_name"], timezones={site_id: timezone}, upstreams={"national": [upstream]},
                  emergency_gateway=upstream, assigned_numbers=set(doc.numbers), adopted=True)
    plan = compile_plan(doc, ctx)
    regenerated = fusionpbx.build(plan, fusionpbx.Target(ps_id, D, {}, adoption=fusionpbx.Adoption(imp.objects, imp.rows, imp.ids, {})))
    adoption = fusionpbx.Adoption(imp.objects, imp.rows, imp.ids, regenerated.meanings)
    first = fusionpbx.build(plan, fusionpbx.Target(ps_id, D, {}, adoption=adoption))
    live = compare.live_rows(export)
    diff = compare.rows_diff(first, live)
    if diff:
        new, changed = compare.summary(diff)
        raise TakeoverError(f"the first publish would not be a no-op ({new} new rows, {changed} changed): nothing adopted")
    understanding = compare.behavior_diff(compare.behavior(live, D), compare.behavior(compare.as_rows(regenerated), D))
    by_key = {f"{t}:{r[fusionpbx.KEYS[t]]}": r for t in fusionpbx.TABLES for r in (export["tables"].get(t) or [])}
    from app.engine.service import extra_hash
    extras = {f"{t}:{u}": extra_hash(by_key[f"{t}:{u}"]) for t, u in imp.extras if f"{t}:{u}" in by_key}
    return {"document": doc.model_dump(mode="json"),
            "adoption": {"objects": {k: [list(x) for x in v] for k, v in imp.objects.items()}, "rows": imp.rows, "ids": imp.ids,
                         "meanings": regenerated.meanings, "extras": extras,
                         # the regenerated rows, without the secret columns (the build only names their kind; nothing secret is kept)
                         "fresh": {k: {c: v for c, v in r.items() if not isinstance(v, fusionpbx.Secret)} for k, r in compare.as_rows(regenerated).items()}},
            "objects": len(first.adopted), "rows": sum(len(first.rows[t]) for t in fusionpbx.TABLES), "extras": len(extras),
            "understanding": understanding,
            "report": [{"what": i.what, "outcome": i.outcome, "detail": i.detail} for i in imp.report]}


def adopt(db: Session, instance: PbxInstance, tenant_id: uuid.UUID, site_id: uuid.UUID, domain_name: str, conn: Any) -> Dict[str, Any]:
    """Read the domain through `conn` (the instance's login), prove the takeover, and keep it: a phone system for the organization, its draft the
    imported document, its numbers assigned to the organization. Nothing is written to the engine here."""
    if db.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == tenant_id)).scalars().first():
        raise TakeoverError("this organization already has a phone system")
    if db.execute(select(Site).where(Site.id == site_id, Site.tenant_id == tenant_id)).scalar_one_or_none() is None:
        raise TakeoverError("that site is not the organization's")         # (audit VOX-A-10; the CLI's set-911 checks the same)
    export = read_domain(conn, domain_name)
    if db.execute(select(PhoneSystem).where(PhoneSystem.domain_uuid == uuid.UUID(export["domain"]["domain_uuid"]))).scalars().first():
        raise TakeoverError("this domain already belongs to a phone system")
    upstream = (instance.emergency_upstream or (instance.routing or {}).get("national", [None])[0])
    if not upstream:
        raise TakeoverError("the instance names no upstream (routing.national and emergency_upstream): set them before adopting")
    ps = PhoneSystem(id=uuid.uuid4(), tenant_id=tenant_id, instance_id=instance.id, domain_name=export["domain"]["domain_name"],
                     domain_uuid=uuid.UUID(export["domain"]["domain_uuid"]), status="new")
    proof = prove(export, str(ps.id), str(site_id), upstream)
    for number in proof["document"]["numbers"]:
        held = db.get(HeldNumber, number)
        if held is not None and held.tenant_id not in (None, tenant_id):
            raise TakeoverError(f"number …{number[-4:]} is assigned to another organization")
        if held is None:
            db.add(HeldNumber(number=number, tenant_id=tenant_id, carrier="htc", note="adopted with its domain (decision 32)"))
        else:
            held.tenant_id = tenant_id
    ps.draft, ps.adoption = proof["document"], proof["adoption"]
    db.add(ps)
    db.flush()
    return {"phone_system_id": str(ps.id), "objects": proof["objects"], "rows": proof["rows"], "extras": proof["extras"],
            "understanding": proof["understanding"], "report": proof["report"]}


def readopt(db: Session, ps: PhoneSystem, instance: PbxInstance, conn: Any) -> Dict[str, Any]:
    """Prove the takeover again with this build's importer (the engine read again; nothing written there) and keep the new adoption and document:
    still a no-op, or nothing changes. For a domain adopted by an earlier importer (one without the regenerated rows, or a document field
    it lacked). Its protections, if any were set, stay set."""
    export = read_domain(conn, ps.domain_name)
    site = next(iter((ps.draft or {}).get("sites") or {}), None)
    upstream = instance.emergency_upstream or (instance.routing or {}).get("national", [None])[0]
    if not site or not upstream:
        raise TakeoverError("the phone system has no site, or the instance no upstream")
    proof = prove(export, str(ps.id), site, upstream)
    kept = {k: v for k, v in (ps.adoption or {}).items() if k in ("retire", "retired_rows")}
    ps.adoption, ps.draft = {**proof["adoption"], **kept}, proof["document"]
    db.flush()
    return {"objects": proof["objects"], "rows": proof["rows"], "extras": proof["extras"], "understanding": proof["understanding"],
            "report": proof["report"]}


def retire_ids(ps: PhoneSystem, export: Mapping[str, Any], names: List[str]) -> List[str]:
    """The ids of the hand-built dial plans named (each must be one of the adoption's extras: PhotonVox never retires its own or another domain's)."""
    extras = {k.split(":", 1)[1] for k in (ps.adoption or {}).get("extras", {}) if k.startswith("v_dialplans:")}
    by_name = {r["dialplan_name"]: r["dialplan_uuid"] for r in export["tables"].get("v_dialplans") or []
               if r.get("domain_uuid") == export["domain"]["domain_uuid"] and r["dialplan_uuid"] in extras}
    missing = [n for n in names if n not in by_name]
    if missing:
        raise TakeoverError(f"not a hand-built dial plan of this domain: {', '.join(missing)}")
    return [by_name[n] for n in names]


def protect_preview(db: Session, ps: PhoneSystem, instance: PbxInstance, conn: Any, names: List[str], caller: str) -> Dict[str, Any]:
    """The protections version, as a dry run against the engine as it is now (read): every row it would add or change, the hand-built dial plans
    it would retire, and where a call out to each test number goes now and after (read from the dial plans, never called). Nothing is written,
    here or on the engine."""
    from app.engine import service
    export = read_domain(conn, ps.domain_name)
    ids = retire_ids(ps, export, names)
    real, real_draft = ps.adoption, ps.draft
    ps.adoption, ps.draft = _retiring(real or {}, export, ids), {**(ps.draft or {}), "protections": True}   # for this build only; restored below
    blocking: List[Dict[str, str]] = []
    try:
        ctx = service.context(db, ps, instance)
        try:
            plan = compile_plan(Document.model_validate(ps.draft), ctx)
        except CompileError as e:
            # The dry run still shows what would change; what stops the real publish is listed (a 911 address not yet validated, typically).
            blocking = [{"path": p.path, "code": p.code, "message": p.message} for p in e.problems]
            if any(p.code != "emergency_location_unvalidated" for p in e.problems):
                raise TakeoverError(f"the document does not compile: {blocking[0]['message']}")
            doc = Document.model_validate(ps.draft)
            assumed = {sid: {site.emergency_location} for sid, site in doc.sites.items()}       # as if the 911 address were validated
            plan = compile_plan(doc, dataclasses.replace(ctx, validated_locations=assumed))
        b = fusionpbx.build(plan, service.target(ps, instance))
    finally:
        ps.adoption, ps.draft = real, real_draft
    live = compare.live_rows(export)
    diff = compare.rows_diff(b, live)
    after = {k: v for k, v in live.items()}
    for t in fusionpbx.TABLES:
        for r in b.rows[t]:
            after[f"{t}:{r[fusionpbx.KEYS[t]]}"] = {**after.get(f"{t}:{r[fusionpbx.KEYS[t]]}", {}), **r}

    D, name = export["domain"]["domain_uuid"], export["domain"]["domain_name"]
    before_calls, after_calls = compare.outbound(live, D, name, caller), compare.outbound(after, D, name, caller)
    new, changed = compare.summary(diff)
    return {"blocking_the_publish": blocking, "new_rows": new, "changed_rows": changed,
            "changes": sorted({f"{d['table']} {', '.join(d.get('columns') or [])}".strip() for d in diff if d["kind"] == "changed"}),
            "new": sorted({f"{d['table']}" for d in diff if d["kind"] == "new row"}),
            "new_dialplans": sorted(r["dialplan_name"] for r in b.rows["v_dialplans"] if f"v_dialplans:{r['dialplan_uuid']}" not in live),
            "retired": sorted(n for n in names),
            "calls_out": {n: {"now": before_calls[n], "after": after_calls[n]} for n in before_calls},
            "checks": [c["number"] for c in fusionpbx.checks(plan, service.target(ps, instance))]}


def _retiring(adoption: Mapping[str, Any], export: Mapping[str, Any], ids: List[str]) -> Dict[str, Any]:
    """The adoption with these hand-built dial plans managed from now on (their rows as they are now; no longer watched as hand-built extras)."""
    rows = {f"v_dialplans:{r['dialplan_uuid']}": r for r in export["tables"].get("v_dialplans") or [] if r["dialplan_uuid"] in ids}
    extras = {k: v for k, v in (adoption.get("extras") or {}).items() if k.split(":", 1)[1] not in ids}
    return {**adoption, "retire": ids, "retired_rows": rows, "extras": extras}


def protect_apply(ps: PhoneSystem, export: Mapping[str, Any], names: List[str]) -> Dict[str, Any]:
    """The draft becomes the protections version (`protections: true`), with these hand-built dial plans switched off by it (and back on by any
    version without protections, an undo included). The next publish publishes it. Nothing is written to the engine here."""
    ids = retire_ids(ps, export, names)
    ps.adoption = _retiring(ps.adoption or {}, export, ids)
    ps.draft = {**(ps.draft or {}), "protections": True}
    return {"protections": True, "retire": names}
