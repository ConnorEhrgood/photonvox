"""The compiler: a validated phone-system document in, the engine plan out. CRITICAL module (100% branch coverage).

The engine plan is everything the phone system needs, in engine terms but not yet in FusionPBX's tables: extensions with their caller IDs and
call classes, voicemail boxes, ring groups, menus, time conditions, inbound numbers, outbound routes per call class with Photon's upstream order,
the locked emergency route, then the locked block route (decision 29). The FusionPBX adapter (app/engine) turns the plan into rows; nothing in it is FusionPBX's
own vocabulary beyond what any FreeSWITCH system has.

Deterministic: the same document and context always give the same plan, byte for byte (keys sorted, lists ordered), which is what makes golden
tests, drift checks and "undo" possible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AbstractSet, Any, Dict, List, Mapping, Optional

from app.compiler import blocking, classes
from app.document.model import PhoneSystem, Target, ToGroup, ToMenu, ToUser
from app.document.validate import Problem, problems


@dataclass(frozen=True)
class Context:
    """What the compiler needs from outside the document: the domain it builds, site time zones (from the directory), the instance's upstream
    gateways in Photon's order per class (§9: never shown to integrators), the gateway that carries 911 (the upstream holding the emergency
    numbers' records), and which emergency locations are validated."""
    domain: str
    timezones: Mapping[str, str]
    upstreams: Mapping[str, List[str]]          # class -> gateway keys, cheapest healthy first: "national", "toll_free", "international", "service"
    emergency_gateway: str
    validated_locations: Mapping[str, AbstractSet[str]] = field(default_factory=dict)
    premium_allowed: bool = False               # Photon staff have let premium numbers through for this organization (§15a)
    assigned_numbers: Optional[AbstractSet[str]] = None   # the numbers assigned to the organization (always given when publishing; review C2)
    # An adopted, hand-built domain (decision 32, ARCHITECTURE §17): its outside calls, 911 and blocking stay hand-built until the protections
    # version, so the 911 address problem does not stop it (its 911 is the engine's own, unchanged), and the builder generates no routes.
    adopted: bool = False
    # How an upstream wants North American numbers: "e164" (+1 and ten digits, the default) or "nanp10" (ten digits, as HUEPC's hand-built
    # routes send HTC today). Upstream key -> format.
    dial_formats: Mapping[str, str] = field(default_factory=dict)


class CompileError(Exception):
    def __init__(self, found: List[Problem]) -> None:
        super().__init__(f"{len(found)} problem(s); the first: {found[0].path}: {found[0].message}" if found else "no upstream")
        self.problems = found


def _dest(doc: PhoneSystem, t: Target) -> str:
    if isinstance(t, ToUser):
        return f"extension:{doc.users[t.user].extension}"
    if isinstance(t, ToGroup):
        return f"ring_group:{t.group}"
    if isinstance(t, ToMenu):
        return f"ivr:{t.menu}"
    return f"voicemail:{doc.users[t.voicemail].extension}" if t.voicemail in doc.users else f"voicemail_box:{t.voicemail}"


def _prefixed(pattern: str, prefixes: List[str]) -> str:
    """Accept the digits with any site's outside-line prefix in front ("9" + number) as well as without."""
    if not prefixes:
        return pattern
    return "^(?:" + "|".join(prefixes) + ")?" + pattern[1:]


def _send(ctx: Context, cls: str) -> str:
    """The number a North American route sends: +1 and the ten digits, or the ten digits alone when every upstream of the class wants them so."""
    gws = list(ctx.upstreams.get(cls) or ctx.upstreams["national"])
    return "$1" if gws and all(ctx.dial_formats.get(g) == "nanp10" for g in gws) else "+1$1"


def compile_plan(doc: PhoneSystem, ctx: Context) -> Dict[str, Any]:
    found = problems(doc, ctx.validated_locations, ctx.assigned_numbers)
    protected = ctx.adopted and doc.protections is True      # the adopted domain's protections version: routes generated, 911 address validated
    if ctx.adopted and not protected:
        found = [p for p in found if p.code != "emergency_location_unvalidated"]
    if found:
        raise CompileError(found)
    if "premium" in doc.calling.blocking.allow and not ctx.premium_allowed:
        raise CompileError([Problem("calling.blocking.allow", "premium_staff_only", "Only Photon staff can let premium numbers through.")])
    if not ctx.emergency_gateway or not ctx.upstreams.get("national"):
        raise CompileError([Problem("instance", "no_upstream", "This instance has no upstream for 911 or national calls; nothing can be published to it.")])

    allowed: List[str] = ["service"]
    if doc.calling.national:
        allowed.append("national")
    if doc.calling.toll_free:
        allowed.append("toll_free")
    countries = sorted(c for c in doc.calling.international if classes.is_valid_international(c))
    if countries:
        allowed.append("international")
    toll_allow = sorted(allowed)

    extensions = []
    for uid in sorted(doc.users, key=lambda u: doc.users[u].extension):
        u = doc.users[uid]
        site = doc.sites[u.site]
        extensions.append({
            "extension": u.extension, "user": uid, "name": u.name, "site": u.site, "email": u.email,
            "caller_id_number": u.direct_number if u.show == "direct" else (u.caller_id or site.caller_id),
            # What a 911 call from this extension shows: the user's own number when set (its 911 address on file), else the site's emergency number.
            "emergency_caller_id_number": u.caller_id or site.emergency_number,
            "toll_allow": toll_allow,
            "unreachable": f"voicemail:{u.extension}" if site.unreachable == "voicemail" else "hangup",
            **({} if u.voicemail else {"voicemail": False}),       # only when off, so the plans of documents that never say stay as they were
        })
    for did in sorted(doc.doors, key=lambda d: doc.doors[d].extension):
        d = doc.doors[did]
        site = doc.sites[d.site]
        # A door station: no voicemail, no call class (it reaches only its own flow), and 911 shows the site's emergency number.
        extensions.append({"extension": d.extension, "door": did, "name": d.name, "site": d.site, "email": None,
                           "caller_id_number": site.caller_id, "emergency_caller_id_number": site.emergency_number, "toll_allow": [],
                           "unreachable": "hangup", "voicemail": False})
    extensions.sort(key=lambda x: x["extension"])
    boxes = [{"key": k, "name": b.name, "email": b.email} for k, b in sorted(doc.boxes.items())]
    groups = [{"key": k, "strategy": g.strategy, "ring_seconds": g.ring_seconds, "members": [doc.users[m].extension for m in g.members],
               "then": _dest(doc, g.then) if g.then else "hangup"} for k, g in sorted(doc.groups.items())]
    menus = [{"key": k, "greeting": m.greeting, "options": {d: _dest(doc, t) for d, t in sorted(m.options.items())},
              "timeout": _dest(doc, m.timeout) if m.timeout else "hangup"} for k, m in sorted(doc.menus.items())]

    time_conditions, inbound = [], []
    for num, n in sorted(doc.numbers.items()):
        site = doc.sites[n.site]
        if n.closed is None:
            inbound.append({"number": num, "site": n.site, "to": _dest(doc, n.open)})
            continue
        hours_name = n.hours or site.hours
        h = doc.hours[hours_name]
        key = f"number-{num.lstrip('+')}"
        time_conditions.append({"key": key, "hours": hours_name, "week": {d: list(h.week[d]) for d in sorted(h.week)}, "holidays": h.holidays,
                                "timezone": ctx.timezones.get(n.site, "America/New_York"), "open": _dest(doc, n.open), "closed": _dest(doc, n.closed)})
        inbound.append({"number": num, "site": n.site, "to": f"time_condition:{key}"})

    doors = []
    for did, d in sorted(doc.doors.items()):
        if d.closed is None:
            doors.append({"key": did, "extension": d.extension, "name": d.name, "site": d.site, "to": _dest(doc, d.open)})
            continue
        hours_name = d.hours or doc.sites[d.site].hours
        h = doc.hours[hours_name]
        key = f"door-{did}"
        time_conditions.append({"key": key, "hours": hours_name, "week": {w: list(h.week[w]) for w in sorted(h.week)}, "holidays": h.holidays,
                                "timezone": ctx.timezones.get(d.site, "America/New_York"), "open": _dest(doc, d.open), "closed": _dest(doc, d.closed)})
        doors.append({"key": did, "extension": d.extension, "name": d.name, "site": d.site, "to": f"time_condition:{key}"})
    time_conditions.sort(key=lambda t: t["key"])

    pages = [{"key": k, "extension": pg.extension, "name": pg.name, "site": pg.site, "members": [doc.users[m].extension for m in pg.members]}
             for k, pg in sorted(doc.pages.items())]

    prefixes = sorted({s.outside_prefix for s in doc.sites.values() if s.outside_prefix})
    routes = [
        # First and locked: 911 and 933, with or without an outside-line prefix, always to the emergency upstream, showing the site's emergency
        # number. No call class, spend limit or restriction applies to it (§11).
        {"key": "emergency", "locked": True, "pattern": _prefixed(r"^(" + "|".join(classes.EMERGENCY) + r")$", prefixes),
         "requires": None, "gateways": [ctx.emergency_gateway], "caller_id": "emergency_caller_id_number", "send": "$1"},
        # Second and locked: the blocked destinations, rejected and recorded (decision 29). The emergency routes come first, so 911 never reaches it.
        blocking.block_route(list(doc.calling.blocking.allow), list(doc.calling.blocking.block), list(doc.calling.blocking.allow_numbers),
                             countries, prefixes, ctx.premium_allowed),
        {"key": "service", "locked": True, "pattern": _prefixed(r"^(" + "|".join(classes.SERVICES) + r")$", prefixes),
         "requires": "service", "gateways": list(ctx.upstreams.get("service") or ctx.upstreams["national"]), "caller_id": "caller_id_number", "send": "$1"},
    ]
    for cls in ("national", "toll_free"):
        if cls in allowed:
            routes.append({"key": cls, "locked": False, "pattern": _prefixed(classes.PATTERNS[cls], prefixes), "requires": cls,
                           "gateways": list(ctx.upstreams.get(cls) or ctx.upstreams["national"]), "caller_id": "caller_id_number", "send": _send(ctx, cls)})
    for code in countries:
        routes.append({"key": f"international-{code}", "locked": False, "pattern": _prefixed(classes.international_pattern(code), prefixes),
                       "requires": "international", "gateways": list(ctx.upstreams.get("international") or ctx.upstreams["national"]),
                       "caller_id": "caller_id_number", "send": ("+1$1" if len(code) == 4 else "+$1")})

    return {
        "domain": ctx.domain,
        "extensions": extensions,
        "voicemail_boxes": boxes,
        "ring_groups": groups,
        "ivr_menus": menus,
        "time_conditions": time_conditions,
        "inbound": inbound,
        **({"doors": doors} if doors else {}),       # only when there are doors, so the plans of documents without stay as they were
        **({"pages": pages} if pages else {}),       # the same for paging groups
        "outbound_routes": routes,
        "outside_prefixes": prefixes,
        "voice": doc.voice,
        "spend_limit_usd": doc.calling.spend_limit_usd,
        "features": {"eavesdrop": doc.features.eavesdrop, "intercept": doc.features.intercept},
        "adopted": ctx.adopted,
        "protected": protected,
    }
