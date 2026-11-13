"""Compare a build with what is live on the engine (the takeover's "compile and compare until identical", ARCHITECTURE §17.3).

- `rows_diff`: row by row, column by column: every row the build would write against the live row with the same id. Empty means the publish
  changes nothing. FusionPBX's bookkeeping columns (dates, users) and secrets (which the build never carries) are not compared.
- `behavior`: what a domain's rows do, independent of how they are written: what each number rings, each menu key, each extension's name and
  caller IDs, each voicemail box. Comparing it for the live rows and for a freshly generated build shows whether PhotonVox understood the
  domain (where it differs, regenerating that object would change behavior: the report says so).
Pure: no database.
"""
from __future__ import annotations

import datetime as dt
import decimal
import json
import re
import uuid
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.engine.fusionpbx import AUDIT, KEYS, TABLES, Build, Secret

Rows = Mapping[str, Mapping[str, Any]]          # "table:id" -> row


def norm(v: Any) -> Any:
    """One form for a value read from PostgreSQL, from JSON, or built: dates as ISO text, ids as text, JSON text parsed, booleans kept."""
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    if isinstance(v, (uuid.UUID, decimal.Decimal)):
        return str(v)
    if isinstance(v, str) and v[:1] in "[{":
        try:
            return json.loads(v)
        except ValueError:
            return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    return v


def rows_diff(b: Build, live: Rows) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for table in TABLES:
        for r in b.rows[table]:
            uid = r[KEYS[table]]
            have = live.get(f"{table}:{uid}")
            if have is None:
                out.append({"table": table, "id": uid, "kind": "new row"})
                continue
            cols = sorted(c for c, v in r.items() if c not in AUDIT and not isinstance(v, Secret))
            changed = [c for c in cols if norm(r[c]) != norm(have.get(c))]
            if changed:
                out.append({"table": table, "id": uid, "kind": "changed", "columns": changed,
                            "values": {c: {"live": have.get(c), "build": r[c]} for c in changed}})
    return out


def _resolve(app: Optional[str], data: Optional[str], ext_of: Mapping[str, str], menu_of: Mapping[str, str]) -> str:
    """Where a FusionPBX action sends a call, by identity (an extension's number, a menu's id), not by how it is written."""
    if app == "ivr":
        return f"menu {data}"
    if app != "transfer" or not data:
        return f"{app} {data}"
    dest = data.split(" ")[0]
    if dest in ext_of:
        return f"extension {dest}"
    if dest in menu_of:
        return f"menu {menu_of[dest]}"
    m = re.fullmatch(r"\*99(\d+)", dest)
    if m:
        return f"voicemail {m.group(1)}"
    return f"transfer {dest}"


def behavior(rows: Rows, domain_uuid: str) -> Dict[str, Any]:
    by: Dict[str, List[Mapping[str, Any]]] = {}
    for k, r in rows.items():
        if r.get("domain_uuid") == domain_uuid:
            by.setdefault(k.split(":", 1)[0], []).append(r)
    ext_of = {x["extension"]: x["extension_uuid"] for x in by.get("v_extensions", [])}
    menu_of = {m["ivr_menu_extension"]: m["ivr_menu_uuid"] for m in by.get("v_ivr_menus", [])}
    digits = lambda s: re.sub(r"\D", "", s or "")[-10:]        # noqa: E731
    out: Dict[str, Any] = {"numbers": {}, "extensions": {}, "menus": {}, "voicemail": {}}
    for d in by.get("v_destinations", []):
        out["numbers"][digits((d.get("destination_prefix") or "") + d["destination_number"])] = (
            _resolve(d.get("destination_app"), d.get("destination_data"), ext_of, menu_of) if d.get("destination_enabled") else "disabled")
    for x in by.get("v_extensions", []):
        # 911 shows the emergency caller ID, or the outbound one when none is set (FusionPBX's emergency route)
        out["extensions"][x["extension"]] = {"name": x.get("effective_caller_id_name"), "outbound": digits(x.get("outbound_caller_id_number")),
                                             "911": digits(x.get("emergency_caller_id_number") or x.get("outbound_caller_id_number")),
                                             "enabled": bool(x.get("enabled"))}
    for v in by.get("v_voicemails", []):
        out["voicemail"][v["voicemail_id"]] = {"enabled": bool(v.get("voicemail_enabled")), "email": v.get("voicemail_mail_to") or None}
    opts = by.get("v_ivr_menu_options", [])
    for m in by.get("v_ivr_menus", []):
        keys = {}
        for o in opts:
            if o["ivr_menu_uuid"] == m["ivr_menu_uuid"] and o.get("ivr_menu_option_enabled"):
                app, _, data = (o.get("ivr_menu_option_param") or o.get("ivr_menu_option_action") or "").partition(" ")
                keys[o["ivr_menu_option_digits"]] = _resolve(app, data, ext_of, menu_of)
        out["menus"][m["ivr_menu_uuid"]] = {"keys": keys, "greeting": m.get("ivr_menu_greet_long"),
                                            "exit": _resolve(m.get("ivr_menu_exit_app"), m.get("ivr_menu_exit_data"), ext_of, menu_of)
                                            if m.get("ivr_menu_exit_app") not in (None, "", "hangup") else None}
    return out


def behavior_diff(live: Mapping[str, Any], built: Mapping[str, Any]) -> List[str]:
    """What a freshly generated build would do differently, in words."""
    out: List[str] = []
    for part in ("numbers", "extensions", "voicemail", "menus"):
        a, b = live.get(part, {}), built.get(part, {})
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                label = k[-4:] if part == "numbers" else (k if part != "menus" else "the menu")
                out.append(f"{part} {label}: live {_short(a.get(k))}, regenerated {_short(b.get(k))}")
    return out


def _short(v: Any) -> str:
    s = json.dumps(v, sort_keys=True, default=str)
    return re.sub(r"\d{10}", lambda m: "…" + m.group(0)[-4:], s)


def live_rows(export: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The export's rows of the managed tables, keyed "table:id"."""
    out: Dict[str, Dict[str, Any]] = {}
    for table in TABLES:
        for r in export["tables"].get(table) or []:
            out[f"{table}:{r[KEYS[table]]}"] = r
    return out


def as_rows(b: Build) -> Dict[str, Dict[str, Any]]:
    return {f"{t}:{r[KEYS[t]]}": r for t in TABLES for r in b.rows[t]}


def summary(diff: List[Dict[str, Any]]) -> Tuple[int, int]:
    return sum(1 for d in diff if d["kind"] == "new row"), sum(1 for d in diff if d["kind"] == "changed")
