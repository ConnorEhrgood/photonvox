"""The takeover importer (ARCHITECTURE §17.2, decision 32): a hand-built FusionPBX domain, as engine/live/export_domain.py read it, in; out come

- the **document** (what PhotonVox shows and edits: users, numbers, the menu, shared boxes),
- the **adoption**: for every object the document describes, the live rows that make it up (their ids and every non-secret column) and the
  object's meaning when it was adopted. The builder (app/engine/fusionpbx.py) emits exactly those live rows while the object's meaning is
  unchanged, so the first publish changes nothing; an object is regenerated only when someone changes it later (§17.4);
- the **hand-built extras**: the domain's rows the document does not describe, left untouched and watched for edits;
- the **report**: everything that could not be expressed, each with what it does and what happens to it (nothing is dropped silently).

Pure: no database, no clock. Secrets never pass through it (the export holds none).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.engine.fusionpbx import IVR_APP, INBOUND_APP, KEYS

Row = Dict[str, Any]
# The tables an adopted object's rows live in (as the builder emits them); rows of the domain in other tables, or not claimed, are extras.
MANAGED = ("v_extensions", "v_voicemails", "v_destinations", "v_ivr_menus", "v_ivr_menu_options", "v_dialplans", "v_dialplan_details",
           "v_ring_groups", "v_ring_group_destinations")
AUDIT = ("insert_date", "insert_user", "update_date", "update_user")


@dataclass
class Item:
    """One line of the report. outcome: expressed (as the document says) | different (expressed, with the difference shown) | extra (left as it is,
    untouched, watched) | decide (needs a person) | unused."""
    what: str
    outcome: str
    detail: str
    rows: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class Imported:
    document: Dict[str, Any]
    objects: Dict[str, List[Tuple[str, str]]]            # builder object key -> the live rows (table, id) that make it up
    rows: Dict[str, Row]                                 # "table:id" -> the live row (every column the export has)
    ids: Dict[str, str]                                  # builder name ("extension:100") -> the live id
    extras: List[Tuple[str, str]]                        # (table, id) of the domain's rows no object claims
    report: List[Item]


def _e164(digits: str) -> Optional[str]:
    d = re.sub(r"\D", "", digits or "")
    if len(d) == 10:
        return "+1" + d
    if len(d) == 11 and d.startswith("1"):
        return "+" + d
    return None


def _target(app: Optional[str], data: Optional[str], domain: str, users: Mapping[str, str], menus: Mapping[str, str]) -> Optional[Dict[str, str]]:
    """A FusionPBX transfer ("100 XML <domain>") as a document outcome, or None when the document has no such outcome."""
    if app != "transfer" or not data:
        return None
    m = re.fullmatch(r"(\S+) XML (\S+)", data.strip())
    if not m or m.group(2) != domain:
        return None
    dest = m.group(1)
    if dest in users:
        return {"user": users[dest]}
    if dest in menus:
        return {"menu": menus[dest]}
    vm = re.fullmatch(r"\*99(\d+)", dest)
    if vm and vm.group(1) in users:
        return {"voicemail": users[vm.group(1)]}
    return None


def import_domain(export: Mapping[str, Any], site_id: str, location_key: str = "main") -> Imported:
    dom = export["domain"]
    D, name = dom["domain_uuid"], dom["domain_name"]
    T: Mapping[str, List[Row]] = {t: (r or []) for t, r in export["tables"].items()}
    rows: Dict[str, Row] = {}
    objects: Dict[str, List[Tuple[str, str]]] = {}
    ids: Dict[str, str] = {}
    report: List[Item] = []

    def claim(obj: str, table: str, row: Row) -> None:
        uid = row[KEYS[table]]
        rows[f"{table}:{uid}"] = dict(row)
        objects.setdefault(obj, []).append((table, uid))

    mine = lambda t: [r for r in T.get(t, []) if r.get("domain_uuid") == D]     # noqa: E731
    dialplans = {r["dialplan_uuid"]: r for r in T.get("v_dialplans", [])}
    details: Dict[str, List[Row]] = {}
    for r in T.get("v_dialplan_details", []):
        details.setdefault(r["dialplan_uuid"], []).append(r)

    def claim_dialplan(obj: str, dp_uuid: Optional[str], builder_name: str) -> None:
        if dp_uuid and dp_uuid in dialplans:
            claim(obj, "v_dialplans", dialplans[dp_uuid])
            ids["dialplan:" + builder_name] = dp_uuid
            for det in sorted(details.get(dp_uuid, []), key=lambda r: (r.get("dialplan_detail_group") or 0, r.get("dialplan_detail_order") or 0)):
                claim(obj, "v_dialplan_details", det)

    # ---- users: one per extension, with its own voicemail box ----
    exts = sorted(mine("v_extensions"), key=lambda r: r["extension"])
    boxes = {r["voicemail_id"]: r for r in mine("v_voicemails")}
    users: Dict[str, str] = {}                           # extension -> user key
    for x in exts:
        users[x["extension"]] = f"u-{x['extension']}"
    emergency = Counter(_e164(x.get("emergency_caller_id_number") or "") for x in exts)
    outbound = Counter(_e164(x.get("outbound_caller_id_number") or "") for x in exts)
    site_caller_id = outbound.most_common(1)[0][0] if outbound else None
    site_emergency = emergency.most_common(1)[0][0] if emergency else None
    if not site_emergency:
        # No extension has an emergency caller ID: FusionPBX's 911 route then sends the outbound caller ID. The document names the site's
        # caller ID as its emergency number, which is what 911 shows today for most extensions.
        site_emergency = site_caller_id
        report.append(Item("911 caller ID", "different", "no extension has an emergency caller ID set, so a 911 call shows the calling extension's "
                           "outbound caller ID (the hand-built 911 handling, kept as it is); the document shows the site's caller ID as its "
                           "emergency number. To decide with the protections version: one registered 911 number per site (§11)", []))

    # ---- numbers ----
    menus: Dict[str, str] = {}
    for m in mine("v_ivr_menus"):
        menus[m["ivr_menu_extension"]] = "main" if len(mine("v_ivr_menus")) == 1 else re.sub(r"[^a-z0-9-]", "-", m["ivr_menu_name"].lower())[:40]
    numbers: Dict[str, Any] = {}
    direct: Dict[str, str] = {}                          # user key -> its direct number (a number that rings only that user)
    for dst in sorted(mine("v_destinations"), key=lambda r: r["destination_number"]):
        num = _e164((dst.get("destination_prefix") or "") + dst["destination_number"])
        tgt = _target(dst.get("destination_app"), dst.get("destination_data"), name, users, menus)
        what = f"number {dst['destination_number'][-4:]} (…{dst['destination_number'][-4:]})"
        if dst.get("destination_type") != "inbound" or not num or tgt is None or not dst.get("destination_enabled"):
            report.append(Item(what, "extra", "an inbound number the document cannot describe (kept exactly as it is)", [("v_destinations", dst["destination_uuid"])]))
            continue
        numbers[num] = {"site": site_id, "open": tgt}
        obj = "inbound:" + num
        claim(obj, "v_destinations", dst)
        ids["destination:" + num] = dst["destination_uuid"]
        claim_dialplan(obj, dst.get("dialplan_uuid"), "inbound:" + num)
        if "user" in tgt:
            direct.setdefault(tgt["user"], num)
        extras = [k for k in ("destination_hold_music", "destination_caller_id_name", "destination_caller_id_number", "destination_cid_name_prefix",
                              "destination_record", "destination_distinctive_ring", "destination_ringback", "destination_accountcode",
                              "destination_conditions") if dst.get(k) not in (None, "", False, "silence")]
        if extras:
            report.append(Item(what, "different", "rings " + (f"user {tgt.get('user')}" if 'user' in tgt else f"menu {tgt.get('menu')}")
                               + f"; also sets {', '.join(extras)}, which the document has no place for: kept on the engine while the number "
                               "is unchanged, and lost if PhotonVox regenerates it", [("v_destinations", dst["destination_uuid"])]))

    # ---- users (after numbers: a user's direct number is the number that rings only them) ----
    doc_users: Dict[str, Any] = {}
    for x in exts:
        key, ext = users[x["extension"]], x["extension"]
        cid = _e164(x.get("outbound_caller_id_number") or "")
        u: Dict[str, Any] = {"name": (x.get("effective_caller_id_name") or ext)[:100], "site": site_id, "extension": ext}
        if direct.get(key) and cid == direct[key]:
            u.update(direct_number=direct[key], show="direct")
            if not x.get("emergency_caller_id_number"):
                report.append(Item(f"extension {ext}", "decide", f"its 911 calls show its direct line (…{cid[-4:]}: no emergency caller ID is set); "
                                   "regenerated, they would show the site's emergency number. Kept exactly as it is; decide with the "
                                   "protections version (§11)", [("v_extensions", x["extension_uuid"])]))
        elif cid and cid != site_caller_id:
            if cid in numbers:
                u["caller_id"] = cid            # its own caller ID, one of the organization's numbers: outside and 911 calls show it (Connor, 2026-11-14)
            else:
                report.append(Item(f"extension {ext}", "decide", f"its outside calls, and so its 911 calls (no emergency caller ID is set), show "
                                   f"…{cid[-4:]}, which is not one of the domain's numbers: the engine keeps it exactly as it is; regenerating "
                                   "this user would change what 911 sees", [("v_extensions", x["extension_uuid"])]))
        box = boxes.get(ext)
        if box and box.get("voicemail_mail_to"):
            u["email"] = box["voicemail_mail_to"]
        if box and not box.get("voicemail_enabled"):
            u["voicemail"] = False
        doc_users[key] = u
        obj = "extension:" + ext
        claim(obj, "v_extensions", x)
        ids["extension:" + ext] = x["extension_uuid"]
        if box:
            claim(obj, "v_voicemails", box)
            ids["voicemail:extension:" + ext] = box["voicemail_uuid"]
        diffs = []
        if cid != (u.get("direct_number") or u.get("caller_id") or site_caller_id):
            diffs.append("its outside calls show a number that is neither the site's nor a number ringing only this user")
        if x.get("emergency_caller_id_number") and _e164(x["emergency_caller_id_number"]) != site_emergency:
            diffs.append("its 911 caller ID differs from the site's")
        if (x.get("outbound_caller_id_name") or None) not in (None, ""):
            diffs.append("its outside calls carry a caller ID name")
        for k, default in (("call_timeout", 30), ("hold_music", None), ("limit_max", "5"), ("number_alias", None), ("toll_allow", None),
                           ("forward_all_enabled", None), ("forward_busy_enabled", None), ("forward_no_answer_enabled", None),
                           ("follow_me_enabled", None), ("do_not_disturb", None), ("call_group", None), ("user_record", None), ("dial_string", None)):
            v = x.get(k)
            if v not in (default, None, "", False, "false") and str(v) != str(default):
                diffs.append(f"{k} is set")
        if not box:
            diffs.append("it has no voicemail box")
        if diffs:
            report.append(Item(f"extension {ext}", "different", "; ".join(diffs) + ": kept on the engine while the user is unchanged",
                               [("v_extensions", x["extension_uuid"])]))

    # ---- the menu ----
    doc_menus: Dict[str, Any] = {}
    options = mine("v_ivr_menu_options")
    for m in mine("v_ivr_menus"):
        key = menus[m["ivr_menu_extension"]]
        obj = "ivr:" + key
        claim(obj, "v_ivr_menus", m)
        ids["ivr:" + key] = m["ivr_menu_uuid"]
        opts: Dict[str, Any] = {}
        unknown = []
        for o in sorted((o for o in options if o["ivr_menu_uuid"] == m["ivr_menu_uuid"]), key=lambda o: o["ivr_menu_option_digits"]):
            claim(obj, "v_ivr_menu_options", o)
            ids[f"ivr:{key}:{o['ivr_menu_option_digits']}"] = o["ivr_menu_option_uuid"]
            app, _, data = (o.get("ivr_menu_option_param") or "").partition(" ")
            t = _target(app, data, name, users, menus) if o.get("ivr_menu_option_action") == "menu-exec-app" else None
            if t and re.fullmatch(r"[0-9]", o["ivr_menu_option_digits"]) and o.get("ivr_menu_option_enabled"):
                opts[o["ivr_menu_option_digits"]] = t
            else:
                unknown.append(o["ivr_menu_option_digits"])
        claim_dialplan(obj, m.get("dialplan_uuid"), "ivr:" + key)
        exit_t = _target(m.get("ivr_menu_exit_app"), m.get("ivr_menu_exit_data"), name, users, menus)
        greeting = m.get("ivr_menu_greet_long") or ""
        doc_menus[key] = {"greeting": f"recording:{greeting}" if greeting else "recording:none", "options": opts,
                          **({"timeout": exit_t} if exit_t else {})}
        notes = []
        if m.get("ivr_menu_exit_app") and not exit_t:
            notes.append(f"its exit action ({m.get('ivr_menu_exit_app')}) is not one the document can describe")
        if m.get("ivr_menu_direct_dial"):
            notes.append(f"callers may dial an extension directly ({m.get('ivr_menu_digit_len')} digits)")
        if m.get("ivr_menu_greet_short"):
            notes.append("it has a short greeting for repeats")
        notes.append(f"timeout {m.get('ivr_menu_timeout')} ms, {m.get('ivr_menu_max_failures')} failures, {m.get('ivr_menu_max_timeouts')} timeouts, ringback {m.get('ivr_menu_ringback')}")
        if unknown:
            notes.append(f"keys {', '.join(unknown)} do something the document cannot describe")
        report.append(Item(f"menu {m['ivr_menu_extension']}", "different", "greeting is their recording, referenced as it is; " + "; ".join(notes)
                           + ": kept on the engine while the menu is unchanged", [("v_ivr_menus", m["ivr_menu_uuid"])]))

    # ---- what nobody claimed: the hand-built extras ----
    claimed = {(t, u) for objs in objects.values() for t, u in objs}
    extras: List[Tuple[str, str]] = []
    for t in MANAGED:
        for r in T.get(t, []):
            if t == "v_dialplan_details":
                continue                                  # a dial plan's details go with it
            in_domain = r.get("domain_uuid") == D
            if in_domain and (t, r[KEYS[t]]) not in claimed:
                extras.append((t, r[KEYS[t]]))
                if t == "v_dialplans":
                    for det in details.get(r["dialplan_uuid"], []):
                        extras.append(("v_dialplan_details", det["dialplan_detail_uuid"]))
                    kind = {IVR_APP: "a menu's", INBOUND_APP: "an inbound route's"}.get(r.get("app_uuid") or "", "")
                    report.append(Item(f"dial plan {r['dialplan_name']!r} (order {r['dialplan_order']}, {'enabled' if r['dialplan_enabled'] else 'disabled'})",
                                       "extra", f"{kind + ' ' if kind else ''}hand-built or FusionPBX's own: left exactly as it is, untouched, and watched for edits",
                                       [(t, r["dialplan_uuid"])]))
                else:
                    report.append(Item(f"{t} row", "extra", "left exactly as it is, untouched, and watched for edits", [(t, r[KEYS[t]])]))
    for t, what in (("v_recordings", "recordings (their audio stays where it is)"), ("v_users", "FusionPBX users of this domain (they can still sign in to FusionPBX's screens)"),
                    ("v_extension_users", "links of FusionPBX users to extensions")):
        n = len(mine(t))
        if n:
            report.append(Item(f"{n} {what}", "extra", "not PhotonVox's: left exactly as they are", []))
    gws = [g for g in T.get("v_gateways", [])]
    for g in gws:
        owner = "this domain" if g.get("domain_uuid") == D else ("no domain (global)" if not g.get("domain_uuid") else "another domain on the engine")
        report.append(Item(f"gateway {g.get('gateway')!r}", "extra", f"owned by {owner}; the instance's upstream, adopted as it is, never rewritten", []))

    document = {
        "version": 1,
        "sites": {site_id: {"emergency_location": location_key, "emergency_number": site_emergency or "", "caller_id": site_caller_id or "",
                            "hours": None}},
        "numbers": numbers, "menus": doc_menus, "users": doc_users, "groups": {}, "boxes": {}, "hours": {},
        "calling": {"national": True, "toll_free": True, "international": []},
        "features": {"eavesdrop": False, "intercept": False},
    }
    report.insert(0, Item("outside calls, 911 and blocking", "extra", "the domain's own outbound routes, its block route and its 911 handling stay "
                          "hand-built (listed below) until the protections version; PhotonVox generates none of them at the takeover", []))
    return Imported(document=document, objects=objects, rows=rows, ids=ids, extras=extras, report=report)
