"""Taking a hand-built domain over in place (decision 32, ARCHITECTURE §17): read it, import it, prove the first publish changes nothing, keep the
adoption. Photon staff only (Platform → Instances). The publish that follows is an ordinary one (app/engine/service.py), which for an adopted
domain writes nothing that is already there, runs no synthetic check and leaves 911 registrations alone.

`read_domain` is the same read as engine/live/export_domain.py (which runs on its own where the app is not installed): every column the login may
read of the domain's rows, the dial plans of its own, public and global contexts, the gateways, never a secret (a deny list on top of the grants).
"""
from __future__ import annotations

import datetime as dt
import decimal
import uuid
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.compiler.compile import Context, compile_plan
from app.document.model import PhoneSystem as Document
from app.engine import compare, fusionpbx, importer
from app.models import HeldNumber, PbxInstance, PhoneSystem

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
                         "meanings": regenerated.meanings, "extras": extras},
            "objects": len(first.adopted), "rows": sum(len(first.rows[t]) for t in fusionpbx.TABLES), "extras": len(extras),
            "understanding": understanding,
            "report": [{"what": i.what, "outcome": i.outcome, "detail": i.detail} for i in imp.report]}


def adopt(db: Session, instance: PbxInstance, tenant_id: uuid.UUID, site_id: uuid.UUID, domain_name: str, conn: Any) -> Dict[str, Any]:
    """Read the domain through `conn` (the instance's login), prove the takeover, and keep it: a phone system for the organization, its draft the
    imported document, its numbers assigned to the organization. Nothing is written to the engine here."""
    if db.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == tenant_id)).scalars().first():
        raise TakeoverError("this organization already has a phone system")
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
