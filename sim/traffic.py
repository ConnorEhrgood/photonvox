"""The demo's call traffic (docs/DEMO.md §1): when calls happen at each site, what kind, who answers, how long. Standard library only, so the
same model drives the 35-day back-fill (sim/backfill.py, call records) and the live simulator (sim/scheduler.py, real SIP calls through SIPp).
Deterministic for a given day: the back-fill re-made tomorrow says the same about today as it did. Every number is from (412) 555-0100 to 0199.

Never an emergency number, a service code (N11, 988) or anything outside the fictional range: `call()` refuses to make one.
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
FICTIONAL = re.compile(r"^41255501\d\d$")          # ten digits: (412) 555-0100 to 0199
OUTSIDE = [f"41255501{x}" for x in range(80, 100)]  # the outside world: callers and the numbers the phones call


@dataclass(frozen=True)
class Site:
    key: str
    # calls per hour, Monday–Friday, by hour of day (New York time); weekends scale it
    weekday: Tuple[float, ...]
    saturday: float
    sunday: float
    mix: Tuple[float, float, float, float]          # inbound, outbound, internal, page
    numbers: Dict[str, Tuple[float, str]]           # the site's numbers (ten digits) -> (share of inbound calls, what answers: "group:x", "ext:101")
    groups: Dict[str, Tuple[str, ...]]              # group -> member extensions
    phones: Tuple[str, ...]                         # extensions that make and take calls
    caller_id: str                                  # what calls out show (ten digits)
    page: Optional[str] = None                      # the paging group's extension
    boxes: Dict[str, str] = field(default_factory=dict)   # group or number -> the voicemail box its unanswered calls reach
    hours: Dict[int, Tuple[int, int]] = field(default_factory=dict)   # weekday (Monday 0) -> open from, until (hours of the day)
    holidays: bool = False                          # closed on the US federal holidays
    closed: Dict[str, str] = field(default_factory=dict)  # a number that goes to a voicemail box outside the hours -> the box


def _hours(**at: float) -> Tuple[float, ...]:
    return tuple(at.get(f"h{h}", 0.0) for h in range(24))


SITES: Dict[str, Site] = {
    "demo-hq": Site(
        "demo-hq",
        weekday=_hours(h7=3, h8=11, h9=17, h10=22, h11=19, h12=11, h13=14, h14=20, h15=17, h16=12, h17=4, h18=1),
        saturday=0.06, sunday=0.03, mix=(0.52, 0.30, 0.18, 0.0),
        numbers={"4125550100": (0.7, "menu"), "4125550101": (0.08, "ext:101"), "4125550102": (0.08, "ext:102"), "4125550103": (0.07, "ext:104"),
                 "4125550104": (0.07, "ext:107")},
        groups={"sales": ("101", "102", "103"), "support": ("104", "105", "106")},
        phones=("100", "101", "102", "103", "104", "105", "106", "107", "108", "109", "111"), caller_id="4125550100",
        boxes={"sales": "sales", "support": "support"},
        hours={d: (8, 17) for d in range(5)}, holidays=True, closed={"4125550100": "company"}),
    "demo-warehouse": Site(
        "demo-warehouse",
        weekday=_hours(h6=2, h7=4, h8=5, h9=5, h10=4, h11=4, h12=2, h13=4, h14=5, h15=4, h16=3, h17=2, h18=2, h19=1.5, h20=1, h21=0.5),
        saturday=0.4, sunday=0.0, mix=(0.40, 0.30, 0.18, 0.12),
        numbers={"4125550140": (0.75, "group:shipping"), "4125550141": (0.25, "ext:201")},
        groups={"shipping": ("200", "201", "204")}, phones=("200", "201", "202", "203", "204"), caller_id="4125550140", page="290",
        boxes={"shipping": "shipping"},
        hours={**{d: (6, 22) for d in range(5)}, 5: (7, 15)}, closed={"4125550140": "shipping"}),
    "demo-apartments": Site(
        "demo-apartments",
        weekday=_hours(h8=0.5, h9=2.5, h10=3, h11=3, h12=2, h13=2.5, h14=3, h15=3, h16=2.5, h17=2.5, h18=1.5, h19=1, h20=0.8, h21=0.5, h22=0.3, h23=0.2),
        saturday=0.7, sunday=0.35, mix=(0.66, 0.24, 0.10, 0.0),
        numbers={"4125550170": (0.8, "group:leasing"), "4125550171": (0.2, "ext:302")},
        groups={"leasing": ("300", "301", "303")}, phones=("300", "301", "302", "303"), caller_id="4125550170",
        boxes={"leasing": "leasing"},
        hours={**{d: (9, 18) for d in range(5)}, 5: (10, 16)}, holidays=True, closed={"4125550170": "leasing"}),
}
MENU = {"1": "group:sales", "2": "group:support", "3": "ext:107", "0": "ext:100"}     # the headquarters' menu: the key pressed -> what it rings


def holiday(d: date) -> bool:
    """A US federal holiday, as the engine's hours have them (api/app/engine/fusionpbx.py US_FEDERAL: the day itself, never an observed day)."""
    monday, thursday = d.weekday() == 0, d.weekday() == 3
    return ((d.month, d.day) in ((1, 1), (6, 19), (7, 4), (11, 11), (12, 25))
            or (monday and ((d.month in (1, 2) and 15 <= d.day <= 21) or (d.month == 5 and d.day >= 25) or (d.month == 9 and d.day <= 7)
                            or (d.month == 10 and 8 <= d.day <= 14)))
            or (thursday and d.month == 11 and 22 <= d.day <= 28))


def is_open(site: Site, at: datetime) -> bool:
    span = site.hours.get(at.weekday())
    return bool(span) and span[0] <= at.hour < span[1] and not (site.holidays and holiday(at.date()))


@dataclass
class Call:
    start: float                # unix seconds
    site: str
    kind: str                   # inbound | outbound | internal | page
    caller: str                 # an extension, or an outside number (ten digits)
    dialed: str                 # what was dialed: a number (ten digits), an extension, a paging group
    reached: str                # who it reached: an extension, "voicemail:<box>", or "" (nobody: missed or not answered)
    status: str                 # answered | missed | voicemail
    ring_s: int
    talk_s: int
    digit: str = ""             # the key the caller pressed in the menu
    closed: bool = False        # the number was closed: the call went straight to its voicemail box

    @property
    def end(self) -> float:
        return self.start + self.ring_s + self.talk_s


def _talk(rng: random.Random, kind: str) -> int:
    if kind == "page":
        return rng.randint(8, 25)
    median = {"inbound": 150, "outbound": 120, "internal": 60}[kind]
    return int(min(1800, max(15, rng.lognormvariate(math.log(median), 0.8))))


def _outcome(rng: random.Random, site: Site, target: str) -> Tuple[str, str, int, str]:
    """(reached, status, ring seconds, the menu key pressed) for an inbound call to `target` ("menu", "group:x", "ext:101")."""
    digit = ""
    if target == "menu":
        digit = rng.choices(list(MENU), weights=[0.38, 0.32, 0.12, 0.18])[0]
        target = MENU[digit]
    kind, _, key = target.partition(":")
    r = rng.random()
    if r < 0.06:                                         # hung up while it rang
        return "", "missed", rng.randint(4, 18), digit
    if kind == "group":
        if r < 0.12:
            return f"voicemail:{site.boxes.get(key, key)}", "voicemail", GROUP_RING_S[key], digit
        return rng.choice(site.groups[key]), "answered", rng.randint(3, 14), digit
    if r < 0.16:
        return f"voicemail:{key}", "voicemail", PHONE_RING_S, digit
    return key, "answered", rng.randint(3, 12), digit


GREETING_S = 13                                          # a voicemail box's greeting, before the caller's message
PHONE_RING_S = 30                                        # how long the engine rings a phone before its voicemail (the extension's call_timeout)
GROUP_RING_S = {"sales": 20, "support": 20, "shipping": 25, "leasing": 45}     # ...and a group (the document's ring_seconds; leasing: three in turn)


def day(site_key: str, d: date, seed: str = "photon-demo") -> List[Call]:
    """Every call at a site on one day (New York time), in order."""
    site = SITES[site_key]
    rng = random.Random(f"{seed}:{site_key}:{d.isoformat()}")
    scale = site.sunday if d.weekday() == 6 or (site.holidays and holiday(d)) else site.saturday if d.weekday() == 5 else 1.0
    scale *= rng.uniform(0.85, 1.15)                     # no two days alike
    calls: List[Call] = []
    for hour in range(24):
        rate = site.weekday[hour] * scale
        t = 0.0
        while True:                                      # a Poisson process within the hour
            t += rng.expovariate(rate) * 3600 if rate > 0 else 3600
            if t >= 3600:
                break
            start = datetime(d.year, d.month, d.day, hour, tzinfo=NY).timestamp() + t
            kind = rng.choices(("inbound", "outbound", "internal", "page"), weights=site.mix)[0]
            if kind == "page" and not site.page:
                kind = "internal"
            if kind == "inbound":
                number = rng.choices(list(site.numbers), weights=[w for w, _ in site.numbers.values()])[0]
                if number in site.closed and not is_open(site, datetime.fromtimestamp(start, NY)):
                    left = rng.random() < 0.6            # a message, or hung up in the greeting
                    c = Call(start, site_key, kind, rng.choice(OUTSIDE), number, f"voicemail:{site.closed[number]}", "voicemail", 0, 0,
                             closed=True) if left else Call(start, site_key, kind, rng.choice(OUTSIDE), number, "", "missed", rng.randint(3, 9), 0,
                                                            closed=True)
                else:
                    reached, status, ring, digit = _outcome(rng, site, site.numbers[number][1])
                    c = Call(start, site_key, kind, rng.choice(OUTSIDE), number, reached, status, ring, 0, digit=digit)
            elif kind == "outbound":
                answered = rng.random() > 0.12
                c = Call(start, site_key, kind, rng.choice(site.phones), rng.choice(OUTSIDE), "outside" if answered else "",
                         "answered" if answered else "missed", rng.randint(4, 20), 0)
            elif kind == "internal":
                a, b = rng.sample(site.phones, 2)
                answered = rng.random() > 0.15
                c = Call(start, site_key, kind, a, b, b if answered else "", "answered" if answered else "missed", rng.randint(2, 15), 0)
            else:
                c = Call(start, site_key, kind, rng.choice(site.phones), site.page, site.page, "answered", 1, 0)
            if c.status == "answered" or c.status == "voicemail":
                c.talk_s = _talk(rng, kind) if c.status == "answered" else GREETING_S + rng.randint(5, 12)
            check(c)
            calls.append(c)
    return calls


def between(start: datetime, end: datetime, sites: Sequence[str] = tuple(SITES)) -> List[Call]:
    """Every call at the sites from `start` to `end`, in order."""
    out: List[Call] = []
    d = start.astimezone(NY).date()
    while d <= end.astimezone(NY).date():
        out += [c for s in sites for c in day(s, d) if start.timestamp() <= c.start < end.timestamp()]
        d += timedelta(days=1)
    return sorted(out, key=lambda c: c.start)


EXTENSION = re.compile(r"^[1-8][0-9]{1,4}$")


def check(c: Call) -> None:
    """Every number a simulated call uses is fictional or an extension of the demo; never 911, 933, 988, an N11 code or any other number."""
    for v in (c.caller, c.dialed):
        if not (FICTIONAL.match(v) or (EXTENSION.match(v) and not re.match(r"^[2-9]11$|^988$|^933$", v))):
            raise ValueError(f"a simulated call may not use {v!r}")
