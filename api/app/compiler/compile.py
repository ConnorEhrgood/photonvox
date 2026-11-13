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


def compile_plan(doc: PhoneSystem, ctx: Context) -> Dict[str, Any]:
    found = problems(doc, ctx.validated_locations)
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
            "caller_id_number": u.direct_number if u.show == "direct" else site.caller_id,
            "emergency_caller_id_number": site.emergency_number,       # what a 911 call from this extension shows: the number registered at its site
            "toll_allow": toll_allow,
            "unreachable": f"voicemail:{u.extension}" if site.unreachable == "voicemail" else "hangup",
        })
    boxes = [{"key": k, "name": b.name, "email": b.email} for k, b in sorted(doc.boxes.items())]
    groups = [{"key": k, "strategy": g.strategy, "ring_seconds": g.ring_seconds, "members": [doc.users[m].extension for m in g.members],
               "then": _dest(doc, g.then) if g.then else "hangup"} for k, g in sorted(doc.groups.items())]
    menus = [{"key": k, "greeting": m.greeting, "options": {d: _dest(doc, t) for d, t in sorted(m.options.items())},
              "timeout": _dest(doc, m.timeout)} for k, m in sorted(doc.menus.items())]

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
                           "gateways": list(ctx.upstreams.get(cls) or ctx.upstreams["national"]), "caller_id": "caller_id_number", "send": "+1$1"})
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
        "outbound_routes": routes,
        "spend_limit_usd": doc.calling.spend_limit_usd,
        "features": {"eavesdrop": doc.features.eavesdrop, "intercept": doc.features.intercept},
    }
