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


# ---- calls out, evaluated by reading the dial plans (never by calling) -----------------------------------------------------------------------

PROBES = ("2125550123", "12125550123", "+12125550123", "8005550100", "18005550100", "9005550100", "7249765100", "8765550100", "2425550100",
          "8095550100", "3405550100", "7875550100", "411", "611", "711", "988", "311", "011442079460000", "911", "933", "9911")


def _cond_value(field: str, number: str, caller: str, toll_allow: str) -> str:
    return {"destination_number": number, "caller_id_number": caller, "${user_exists}": "false", "${call_direction}": "",
            "${toll_allow}": toll_allow, "${photonvox_synthetic}": "", "${loopback_leg}": ""}.get(field, "")


def _evaluate(xml: str, number: str, caller: str, toll_allow: str) -> Optional[str]:
    """What one FusionPBX dial plan (extension XML) does with a call out, or None when it does not take it: conditions in order, a failing one
    ends the extension unless break="never"; break="on-true" ends it at the first that holds (the block route's categories)."""
    import xml.etree.ElementTree as ET
    try:
        ext = ET.fromstring(xml)
    except ET.ParseError:
        return None
    if ext.get("continue") == "true":
        return None                                 # sets variables and lets the call go on (call_direction)
    done: List[str] = []
    variables: Dict[str, str] = {}
    for cond in ext.findall("condition"):
        field, expr, brk = cond.get("field"), cond.get("expression"), cond.get("break", "on-false")
        m = None
        if field is None and expr is None:
            ok = True
        else:
            try:
                m = re.search(expr or "", _cond_value(field or "", number, caller, toll_allow))
            except re.error:
                m = None
            ok = m is not None
        if ok:
            for a in cond.findall("action"):
                # As FreeSWITCH does: $1… are this condition's captures; ${name} a variable an earlier action set.
                data = re.sub(r"\$(\d)", lambda g: (m.group(int(g.group(1))) or "") if m and int(g.group(1)) <= (m.re.groups or 0) else "", a.get("data") or "")
                data = re.sub(r"\$\{(\w+)\}", lambda g: variables.get(g.group(1), g.group(0)), data)
                if a.get("application") in ("set", "export") and "=" in data:
                    k, _, v = data.partition("=")
                    variables[k] = v
                done.append(f"{a.get('application')} {data}".strip())
            if brk == "on-true":
                break
        elif brk == "on-false":
            return None
    effect = [d for d in done if d.split(" ")[0] in ("bridge", "hangup", "transfer", "respond")]
    if not effect:
        return None
    e = effect[0]
    if e.startswith("bridge"):
        return "bridge " + re.sub(r"sofia/gateway/[0-9a-f-]{36}/", "gateway/…/", e.split(" ", 1)[1])
    return e


def outbound(rows: Rows, domain_uuid: str, domain_name: str, caller: str, numbers: Tuple[str, ...] = PROBES) -> Dict[str, str]:
    """For each number, the dial plan that takes a call to it from extension `caller` (with that extension's call classes) and what it does,
    from the domain's enabled dial plans in their order. Read only."""
    plans = sorted((r for k, r in rows.items() if k.startswith("v_dialplans:") and r.get("domain_uuid") == domain_uuid
                    and r.get("dialplan_context") == domain_name and r.get("dialplan_enabled") in (True, "true", "t")),
                   key=lambda r: (int(r.get("dialplan_order") or 0), r.get("dialplan_name") or ""))
    ext = next((r for k, r in rows.items() if k.startswith("v_extensions:") and r.get("extension") == caller and r.get("domain_uuid") == domain_uuid), {})
    toll = ext.get("toll_allow") or ""
    out: Dict[str, str] = {}
    for n in numbers:
        out[n] = "no route (the call fails)"
        for p in plans:
            got = _evaluate(p.get("dialplan_xml") or "", n, caller, toll)
            if got:
                out[n] = f"{p.get('dialplan_name')} (order {p.get('dialplan_order')}): {got}"
                break
    return out
