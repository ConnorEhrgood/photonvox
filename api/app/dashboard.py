"""The customer dashboard (docs/DEMO.md §3): what is going on in the organization's phone system, for the whole organization or one site.

`gather` reads the engine: the call history (FusionPBX's `v_xml_cdr`, the columns the read role has), the extensions and the voicemail
messages (counts only), and vox-agent's `live` (registrations, channels, gateways). `compute` turns that into the page's numbers with no I/O,
so it is tested with plain rows. A part the engine cannot give (an agent without `live`, a role without the voicemail grant) comes back as
None and the page says so; the rest still shows.

Privacy: an outside party's number is shown by its last four digits only. Phones are named by extension and the user's name; never an address.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.document.model import PhoneSystem as Document, ToGroup, ToMenu, ToUser, ToVoicemail

log = logging.getLogger("photonvox.dashboard")

HISTORY_DAYS = 35
EMERGENCY = re.compile(r"^[89]?(911|933)$")
MISSED = {"missed", "cancelled", "no_answer", "busy"}
# Hang-up causes that say the carrier's side did not take the call (not a block of ours, not the called party's answer)
TRUNK_TROUBLE = {"NORMAL_TEMPORARY_FAILURE", "NETWORK_OUT_OF_ORDER", "DESTINATION_OUT_OF_ORDER", "RECOVERY_ON_TIMER_EXPIRE", "GATEWAY_DOWN",
                 "SERVICE_UNAVAILABLE", "SWITCH_CONGESTION", "NORMAL_CIRCUIT_CONGESTION", "INCOMPATIBLE_DESTINATION"}
CDR_COLUMNS = ("xml_cdr_uuid::text as id, direction, caller_id_number, caller_destination, destination_number, start_epoch, answer_epoch, "
               "end_epoch, billsec, status, missed_call, voicemail_message, extension_uuid::text as extension_uuid, hangup_cause")


@dataclass
class Raw:
    """What the engine said, as read: each part None when it could not be read."""
    calls: Optional[List[Dict[str, Any]]] = None
    extensions: Dict[str, str] = field(default_factory=dict)          # extension_uuid -> extension
    voicemail: Optional[List[Dict[str, Any]]] = None                  # {box (the voicemail id: an extension or a box's number), created, new}
    live: Optional[Dict[str, Any]] = None
    problems: List[str] = field(default_factory=list)


def gather(eng: Any, agent: Any, domain_name: str, domain_uuid: str, now: datetime) -> Raw:
    raw = Raw()
    since = int((now - timedelta(days=HISTORY_DAYS)).timestamp())
    try:
        with eng.connect() as c:
            raw.calls = [dict(r) for r in c.execute(text(
                f"select {CDR_COLUMNS} from v_xml_cdr where domain_uuid = :d and start_epoch >= :s and coalesce(leg, 'a') = 'a'"),
                {"d": domain_uuid, "s": since}).mappings()]
            raw.extensions = {r["u"]: r["e"] for r in c.execute(text(
                "select extension_uuid::text as u, extension as e from v_extensions where domain_uuid = :d"), {"d": domain_uuid}).mappings()}
    except Exception as e:  # noqa: BLE001 - the page shows what it has
        log.warning("dashboard: call history of %s not read: %s: %s", domain_name, type(e).__name__, e)
        raw.problems.append("history")
    try:
        with eng.connect() as c:
            raw.voicemail = [dict(r) for r in c.execute(text(
                "select v.voicemail_id::text as box, v.voicemail_description as name, m.created_epoch as created, "
                "coalesce(m.message_status, '') <> 'saved' as new "
                "from v_voicemail_messages m join v_voicemails v on v.voicemail_uuid = m.voicemail_uuid where m.domain_uuid = :d"),
                {"d": domain_uuid}).mappings()]
    except Exception as e:  # noqa: BLE001 - production's read role gets v_voicemail_messages in step P2
        log.info("dashboard: voicemail of %s not read: %s", domain_name, type(e).__name__)
        raw.problems.append("voicemail")
    try:
        raw.live = agent.live(domain_name)
    except Exception as e:  # noqa: BLE001 - an engine whose agent does not allow `live` yet
        log.info("dashboard: live view of %s not read: %s", domain_name, type(e).__name__)
        raw.problems.append("live")
    return raw


# ---- the organization's shape, from its published document ----

def _digits10(n: Optional[str]) -> str:
    d = re.sub(r"[^0-9]", "", n or "")
    return d[-10:] if len(d) >= 10 else d


def _masked(n: Optional[str]) -> str:
    d = re.sub(r"[^0-9]", "", n or "")
    return "…" + d[-4:] if len(d) >= 7 else (d or "unknown")


@dataclass
class Shape:
    ext_site: Dict[str, str]                 # extension -> site id
    ext_name: Dict[str, str]                 # extension -> who (a user's name, a door's)
    endpoints: Dict[str, List[str]]          # site id -> extensions expected to have a phone
    number_site: Dict[str, str]              # ten digits -> site id
    number_key: Dict[str, str]               # ten digits -> the number as the document has it
    caller_id_site: Dict[str, str]           # a site's shown number (ten digits) -> site id
    box_site: Dict[str, str]                 # voicemail id -> site id
    box_name: Dict[str, str]


def shape(doc: Document) -> Shape:
    ext_site, ext_name, endpoints = {}, {}, defaultdict(list)
    for u in doc.users.values():
        ext_site[u.extension], ext_name[u.extension] = u.site, u.name
        endpoints[u.site].append(u.extension)
    for d in doc.doors.values():
        ext_site[d.extension], ext_name[d.extension] = d.site, d.name
        endpoints[d.site].append(d.extension)
    number_site = {_digits10(n): x.site for n, x in doc.numbers.items()}
    caller_id_site = {_digits10(s.caller_id): k for k, s in doc.sites.items()}
    box_site = {u.extension: u.site for u in doc.users.values()}
    box_name = {u.extension: u.name for u in doc.users.values()}
    # A shared box belongs to the site whose number or group sends calls to it (on the engine it is numbered, and named by its description)
    for x in doc.numbers.values():
        for t in (x.open, x.closed):
            if isinstance(t, ToVoicemail) and t.voicemail in doc.boxes:
                box_site.setdefault(doc.boxes[t.voicemail].name, x.site)
    for g in doc.groups.values():
        if isinstance(g.then, ToVoicemail) and g.then.voicemail in doc.boxes and g.members and g.members[0] in doc.users:
            box_site.setdefault(doc.boxes[g.then.voicemail].name, doc.users[g.members[0]].site)
    number_key = {_digits10(n): n for n in doc.numbers}
    return Shape(ext_site, ext_name, dict(endpoints), number_site, number_key, caller_id_site, box_site, box_name)


def target_label(doc: Document, t: Any) -> str:
    if isinstance(t, ToUser):
        u = doc.users.get(t.user)
        return f"{u.name} ({u.extension})" if u else t.user
    if isinstance(t, ToGroup):
        return f"the {t.group} group"
    if isinstance(t, ToMenu):
        return f"the {t.menu} menu"
    if isinstance(t, ToVoicemail):
        b = doc.boxes.get(t.voicemail)
        return f"voicemail ({b.name if b else t.voicemail})"
    return "—"


# ---- one call record ----

def kind_of(r: Mapping[str, Any]) -> str:
    d = (r.get("direction") or "").lower()
    return "inbound" if d == "inbound" else "outbound" if d == "outbound" else "internal"


def site_of(r: Mapping[str, Any], sh: Shape, extensions: Mapping[str, str]) -> Optional[str]:
    k = kind_of(r)
    ext = extensions.get(r.get("extension_uuid") or "")
    caller = (r.get("caller_id_number") or "").strip()
    if k == "inbound":
        return sh.number_site.get(_digits10(r.get("caller_destination"))) or sh.number_site.get(_digits10(r.get("destination_number"))) \
            or sh.ext_site.get(ext or "")
    if k == "outbound":
        return sh.ext_site.get(ext or "") or sh.ext_site.get(caller) or sh.caller_id_site.get(_digits10(caller))
    return sh.ext_site.get(caller) or sh.ext_site.get(ext or "")


def is_missed(r: Mapping[str, Any]) -> bool:
    return kind_of(r) != "outbound" and ((r.get("status") or "") in MISSED or (r.get("missed_call") is True and (r.get("status") or "") != "voicemail"))


def is_voicemail(r: Mapping[str, Any]) -> bool:
    return (r.get("status") or "") == "voicemail" or r.get("voicemail_message") is True


def is_emergency(r: Mapping[str, Any]) -> bool:
    return kind_of(r) == "outbound" and bool(EMERGENCY.match(re.sub(r"[^0-9]", "", r.get("destination_number") or r.get("caller_destination") or "")))


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


# ---- the page ----

def compute(doc: Document, sites: Sequence[Mapping[str, Any]], site: Optional[str], raw: Raw, now: datetime,
            emergency_address: Mapping[str, str], carrier_gateways: Set[str]) -> Dict[str, Any]:
    """`sites`: the organization's sites the person may see ({id, slug, name, timezone}); `site`: one of their ids, or None for all of them."""
    sh = shape(doc)
    visible = {str(s["id"]) for s in sites}
    chosen = {site} if site else visible
    by_id = {str(s["id"]): s for s in sites}
    tz = ZoneInfo((by_id.get(site) or (sites[0] if sites else {})).get("timezone") or "America/New_York")
    local_now = now.astimezone(tz)
    day0 = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_today = int(day0.timestamp())

    def mine(site_id: Optional[str]) -> bool:
        # the whole organization: every call (one with no site too); a site: its own
        return site_id in chosen if site else (site_id is None or site_id in visible)

    out: Dict[str, Any] = {"as_of": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "timezone": str(tz),
                           "site": site, "sites": [{"id": str(s["id"]), "slug": s["slug"], "name": s["name"]} for s in sites
                                                   if str(s["id"]) in doc.sites],
                           "unavailable": sorted(set(raw.problems))}

    # history
    calls = [dict(r, _site=site_of(r, sh, raw.extensions)) for r in (raw.calls or [])]
    calls = [r for r in calls if mine(r["_site"])]
    today = [r for r in calls if _int(r.get("start_epoch")) >= start_today]
    if raw.calls is None:
        out["today"] = out["typical"] = out["busiest"] = out["week"] = None
        out["emergency"] = None
    else:
        out["today"] = _day(today, tz)
        out["typical"] = _typical(calls, day0, local_now, tz)
        out["busiest"] = _busiest(calls, day0, tz)
        week0 = int((day0 - timedelta(days=6)).timestamp())
        out["week"] = _mix([r for r in calls if _int(r.get("start_epoch")) >= week0])
        out["emergency"] = [_emergency(r, sh, raw.extensions, by_id, doc, emergency_address, tz) for r in today if is_emergency(r)]

    # now
    out["now"] = _now(raw.live, sh, mine, carrier_gateways, now) if raw.live is not None else None
    if out["now"] is not None and out["today"] is not None:
        # a call in progress has no record yet (FusionPBX writes it when the call ends): today counts it, and its minutes so far
        t, hour = out["today"], local_now.hour
        for c in out["now"]["calls"]:
            t["calls"] += 1
            t[c["kind"]] += 1
            t["by_hour"][hour][c["kind"]] += 1
        t["minutes"] = round((sum(_int(r.get("billsec")) for r in today) + sum(c["seconds"] for c in out["now"]["calls"] if c["state"] == "talking")) / 60)
        t["in_progress"] = out["now"]["count"]
        t["peak_lines"] = max(t["peak_lines"], out["now"]["lines"])
    out["phones"] = _phones(raw.live, sh, chosen) if raw.live is not None else None
    out["trunk"] = _trunk(raw.live, [r for r in (raw.calls or [])], carrier_gateways, now)
    out["voicemail"] = _voicemail(raw.voicemail, sh, mine) if raw.voicemail is not None else None
    out["numbers"] = _numbers(doc, by_id, chosen, today)
    return out


def _day(rows: List[Dict[str, Any]], tz: ZoneInfo) -> Dict[str, Any]:
    hours = [{"inbound": 0, "outbound": 0, "internal": 0} for _ in range(24)]
    for r in rows:
        hours[datetime.fromtimestamp(_int(r.get("start_epoch")), tz).hour][kind_of(r)] += 1
    mix = _mix(rows)
    return {"calls": len(rows), "minutes": round(sum(_int(r.get("billsec")) for r in rows) / 60),
            "answered": sum(1 for r in rows if _int(r.get("billsec")) > 0 or r.get("status") == "answered"),
            "missed": sum(1 for r in rows if is_missed(r)), "to_voicemail": sum(1 for r in rows if is_voicemail(r)),
            "by_hour": hours, **mix, "peak_lines": _peak([r for r in rows if kind_of(r) != "internal"])}


def _mix(rows: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    m = {"inbound": 0, "outbound": 0, "internal": 0}
    for r in rows:
        m[kind_of(r)] += 1
    return m


def _peak(rows: List[Mapping[str, Any]]) -> int:
    """The most calls on the carrier's lines at once (each call from its start to its end)."""
    edges = sorted([(_int(r.get("start_epoch")), 1) for r in rows] + [(_int(r.get("end_epoch")) or _int(r.get("start_epoch")), -1) for r in rows],
                   key=lambda e: (e[0], e[1]))
    peak = cur = 0
    for _t, d in edges:
        cur += d
        peak = max(peak, cur)
    return peak


def _typical(rows: List[Dict[str, Any]], day0: datetime, local_now: datetime, tz: ZoneInfo) -> Dict[str, Any]:
    """The last four of the same weekday: their average by hour, and their average up to this time of day (what "today so far" is
    compared with). Days before the history began count only when they have calls (a new system has no "usual" yet)."""
    days = [day0 - timedelta(days=7 * i) for i in range(1, 5)]
    counted = []
    for d in days:
        lo, hi = int(d.timestamp()), int((d + timedelta(days=1)).timestamp())
        counted.append([r for r in rows if lo <= _int(r.get("start_epoch")) < hi])
    with_calls = [c for c in counted if c]
    if not with_calls:
        return {"days": 0, "by_hour": [0.0] * 24, "calls_so_far": None, "minutes_so_far": None, "missed_so_far": None, "weekday": local_now.strftime("%A")}
    hours = [0.0] * 24
    so_far = {"calls": 0, "minutes": 0.0, "missed": 0}
    cut = local_now.hour * 3600 + local_now.minute * 60 + local_now.second
    for c in with_calls:
        for r in c:
            t = datetime.fromtimestamp(_int(r.get("start_epoch")), tz)
            hours[t.hour] += 1
            if t.hour * 3600 + t.minute * 60 + t.second <= cut:
                so_far["calls"] += 1
                so_far["minutes"] += _int(r.get("billsec")) / 60
                so_far["missed"] += is_missed(r)
    n = len(with_calls)
    return {"days": n, "by_hour": [round(h / n, 1) for h in hours], "calls_so_far": round(so_far["calls"] / n, 1),
            "minutes_so_far": round(so_far["minutes"] / n), "missed_so_far": round(so_far["missed"] / n, 1), "weekday": local_now.strftime("%A")}


def _busiest(rows: List[Dict[str, Any]], day0: datetime, tz: ZoneInfo) -> Dict[str, Any]:
    """Calls by weekday (Monday first) and hour over the last four weeks, as an average per day."""
    lo = int((day0 - timedelta(days=28)).timestamp())
    grid = [[0.0] * 24 for _ in range(7)]
    for r in rows:
        s = _int(r.get("start_epoch"))
        if lo <= s < int(day0.timestamp()):
            t = datetime.fromtimestamp(s, tz)
            grid[t.weekday()][t.hour] += 1
    weeks = 4
    grid = [[round(v / weeks, 1) for v in day] for day in grid]
    top = max(((d, h, grid[d][h]) for d in range(7) for h in range(24)), key=lambda x: x[2])
    return {"grid": grid, "top": {"weekday": top[0], "hour": top[1], "calls": top[2]} if top[2] > 0 else None}


def _emergency(r: Mapping[str, Any], sh: Shape, extensions: Mapping[str, str], by_id: Mapping[str, Mapping[str, Any]], doc: Document,
               address: Mapping[str, str], tz: ZoneInfo) -> Dict[str, Any]:
    ext = extensions.get(r.get("extension_uuid") or "") or (r.get("caller_id_number") or "")
    site_id = r.get("_site")
    return {"at": datetime.fromtimestamp(_int(r.get("start_epoch")), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "dialed": re.sub(r"[^0-9]", "", r.get("destination_number") or ""), "extension": ext if ext in sh.ext_name else None,
            "who": sh.ext_name.get(ext), "site": (by_id.get(site_id or "") or {}).get("name"), "address": address.get(site_id or ""),
            "answered": _int(r.get("billsec")) > 0, "seconds": _int(r.get("billsec"))}


def _now(live: Mapping[str, Any], sh: Shape, mine: Any, carrier: Set[str], now: datetime) -> Dict[str, Any]:
    """Calls in progress: the engine's channels grouped by call. A call is inbound or outbound when one of its legs is on a gateway, else internal."""
    calls: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for c in live.get("channels") or []:
        calls[c.get("call") or c.get("uuid")].append(c)
    rows = []
    for legs in calls.values():
        gw = [c for c in legs if c.get("gateway")]
        inside = [c for c in legs if not c.get("gateway")]
        kind = ("inbound" if gw[0].get("direction") == "inbound" else "outbound") if gw else "internal"
        exts = [c.get("presence") for c in inside if c.get("presence") in sh.ext_name]
        exts += [x for c in legs for x in (c.get("cid_num"), c.get("dest"), c.get("callee_num")) if x in sh.ext_name and x not in exts]
        if kind == "inbound":
            dialed = _digits10(gw[0].get("dest"))
            site_id = sh.number_site.get(dialed) or (sh.ext_site.get(exts[0]) if exts else None)
            other = _masked(gw[0].get("cid_num"))
        elif kind == "outbound":
            site_id = sh.ext_site.get(exts[0]) if exts else None
            other = _masked(gw[0].get("dest") or gw[0].get("callee_num"))
            dialed = None
        else:
            site_id = sh.ext_site.get(exts[0]) if exts else None
            other = sh.ext_name.get(exts[1], exts[1]) if len(exts) > 1 else None
            dialed = None
        if not mine(site_id):
            continue
        started = min((_int(c.get("created")) for c in legs if c.get("created")), default=int(now.timestamp()))
        states = {(c.get("callstate") or "").upper() for c in legs}
        rows.append({"kind": kind, "who": [{"extension": x, "name": sh.ext_name[x]} for x in exts[:2]], "other": other,
                     "number": sh.number_key.get(dialed or ""),
                     "state": "talking" if "ACTIVE" in states or "HELD" in states else "ringing", "seconds": max(0, int(now.timestamp()) - started),
                     "site": site_id})
    rows.sort(key=lambda r: -r["seconds"])
    lines = sum(1 for r in rows if r["kind"] != "internal")
    return {"calls": rows, "count": len(rows), "lines": lines}


def _phones(live: Mapping[str, Any], sh: Shape, chosen: Set[str]) -> Dict[str, Any]:
    registered: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for r in live.get("registrations") or []:
        registered[r.get("extension")].append(r)
    expected = [(x, s) for s in chosen for x in sh.endpoints.get(s, [])]
    online = [x for x, _s in expected if registered.get(x)]
    offline = [{"extension": x, "name": sh.ext_name.get(x, x), "site": s} for x, s in expected if not registered.get(x)]
    return {"online": len(online), "total": len(expected), "offline": sorted(offline, key=lambda o: o["extension"]),
            "devices": sum(len(registered.get(x, [])) for x, _s in expected)}


def _trunk(live: Optional[Mapping[str, Any]], rows: List[Mapping[str, Any]], carrier: Set[str], now: datetime) -> Dict[str, Any]:
    """Outside calling in plain words: the carrier's gateways as FreeSWITCH sees them, and how the last outside calls went."""
    gws = [g for g in (live or {}).get("gateways") or [] if not carrier or g.get("gateway") in carrier]
    down = [g for g in gws if (g.get("status") or "").upper() == "DOWN" or (g.get("state") or "").upper() in ("FAIL_WAIT", "FAILED", "UNREGED")]
    hour_ago = int((now - timedelta(hours=1)).timestamp())
    out_recent = sorted([r for r in rows if kind_of(r) == "outbound" and not is_emergency(r) and _int(r.get("start_epoch")) >= hour_ago],
                        key=lambda r: _int(r.get("start_epoch")))
    last3 = out_recent[-3:]
    failing = len(last3) == 3 and all((r.get("hangup_cause") or "") in TRUNK_TROUBLE for r in last3)
    last_in = max((_int(r.get("start_epoch")) for r in rows if kind_of(r) == "inbound" and _int(r.get("billsec")) > 0), default=0)
    last_out = max((_int(r.get("start_epoch")) for r in rows if kind_of(r) == "outbound" and _int(r.get("billsec")) > 0), default=0)
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None   # noqa: E731
    if live is None and not rows:
        state, words = "unknown", "We can't see the phone lines right now."
    elif down or failing:
        since = _int(last3[0].get("start_epoch")) if failing else 0
        state = "trouble"
        words = "Outside calls are not getting through" + (f" since {iso(since)}" if since else "") + ". Photon has been told."
    elif live is None:
        state, words = "unknown", "Calls in and out worked at the last call; the live view of the lines isn't available yet."
    else:
        state, words = "ok", "Calls in and out are working."
    return {"state": state, "words": words, "gateways": len(gws), "last_in": iso(last_in), "last_out": iso(last_out)}


def _voicemail(rows: List[Mapping[str, Any]], sh: Shape, mine: Any) -> Dict[str, Any]:
    boxes: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        box = str(r.get("box") or "")
        user = box in sh.box_name
        name = sh.box_name[box] if user else (r.get("name") or f"Box {box}")
        site_id = sh.box_site.get(box if user else name)
        if not mine(site_id):
            continue
        b = boxes.setdefault(box, {"box": box, "extension": box if user else None, "name": name, "new": 0, "saved": 0, "oldest_new": None})
        if r.get("new"):
            b["new"] += 1
            c = _int(r.get("created"))
            b["oldest_new"] = min(b["oldest_new"] or c, c)
        else:
            b["saved"] += 1
    listed = sorted((b for b in boxes.values() if b["new"]), key=lambda b: (-b["new"], b["box"]))
    for b in listed:
        b["oldest_new"] = datetime.fromtimestamp(b["oldest_new"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if b["oldest_new"] else None
    return {"new": sum(b["new"] for b in boxes.values()), "boxes": listed}


def _numbers(doc: Document, by_id: Mapping[str, Mapping[str, Any]], chosen: Set[str], today: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for n, x in sorted(doc.numbers.items()):
        if x.site not in chosen:
            continue
        mine = [r for r in today if kind_of(r) == "inbound" and (_digits10(r.get("caller_destination")) == _digits10(n)
                                                              or _digits10(r.get("destination_number")) == _digits10(n))]
        last = max((_int(r.get("start_epoch")) for r in mine), default=0)
        out.append({"number": n, "site": (by_id.get(x.site) or {}).get("name"), "rings": target_label(doc, x.open),
                    "closed": target_label(doc, x.closed) if x.closed else None, "calls_today": len(mine),
                    "last_call": datetime.fromtimestamp(last, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if last else None})
    return out
