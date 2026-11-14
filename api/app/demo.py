"""The demo organization's phone system (docs/DEMO.md; photon-suite DEMO.md): Photon Demo, `demo`, with the directory's fixed ids. Everything is
fictional: people, numbers (only (412) 555-0100 to 0199), and 911 locations (a city only, marked as not a real address). It is published only to a
simulated instance (staging CT 610), never to a live engine: the publisher refuses otherwise (app/engine/service.py)."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

ORG = "3560c835-5885-442d-bf55-6e250e4b5190"
HQ, WAREHOUSE, APARTMENTS, BILLBOARDS = ("72a17302-e998-4a17-9459-dbc61c4ea410", "736b1e29-7f84-40a8-b06b-1495902f7d2f",
                                         "e8088684-45b6-45f3-aebc-5e0efc638a3c", "b23c8137-ae72-4106-a3e6-55d882d9c3c1")
SITES = {HQ: ("demo-hq", "Headquarters", "Pittsburgh", "PA"), WAREHOUSE: ("demo-warehouse", "Distribution Center", "Washington", "PA"),
         APARTMENTS: ("demo-apartments", "Riverside Apartments", "Wheeling", "WV"), BILLBOARDS: ("demo-billboards", "Route 19 Billboards", "Washington", "PA")}
PHONE_SITES = (HQ, WAREHOUSE, APARTMENTS)          # the billboards have no phones
DOMAIN = "demo.vox.test"


def n(last: int) -> str:
    """A demo number: (412) 555-01xx, the fictional range, and nothing else."""
    assert 100 <= last <= 199
    return f"+1412555{last:04d}"


# The organization's numbers; 0180–0199 are "the outside world" (the simulated callers and the numbers the phones call), never the organization's.
MAIN_HQ, MAIN_WAREHOUSE, DOCK, LEASING, MAINTENANCE = n(100), n(140), n(141), n(170), n(171)
OUTSIDE = [n(x) for x in range(180, 200)]

# (key, name, site, extension, direct line or None, voicemail)
PEOPLE: List[Tuple[str, str, str, str, Any, bool]] = [
    ("reception", "Front desk", HQ, "100", None, True),
    ("avery", "Avery Collins", HQ, "101", n(101), True),
    ("jordan", "Jordan Reyes", HQ, "102", n(102), True),
    ("morgan", "Morgan Patel", HQ, "103", None, True),
    ("riley", "Riley Chen", HQ, "104", n(103), True),
    ("casey", "Casey Brooks", HQ, "105", None, True),
    ("taylor", "Taylor Nguyen", HQ, "106", None, True),
    ("quinn", "Quinn Ellis", HQ, "107", n(104), True),
    ("devon", "Devon Shaw", HQ, "108", None, True),
    ("it-desk", "IT help desk", HQ, "109", None, True),
    ("conference", "Conference room", HQ, "110", None, False),
    ("lobby", "Lobby phone", HQ, "111", None, False),
    ("shipping", "Shipping desk", WAREHOUSE, "200", None, True),
    ("dock", "Dock office", WAREHOUSE, "201", None, True),
    ("forklift-1", "Forklift handset 1", WAREHOUSE, "202", None, False),
    ("forklift-2", "Forklift handset 2", WAREHOUSE, "203", None, False),
    ("supervisor", "Sam Ortiz", WAREHOUSE, "204", None, True),
    ("speaker-north", "Overhead speaker, north", WAREHOUSE, "220", None, False),
    ("speaker-south", "Overhead speaker, south", WAREHOUSE, "221", None, False),
    ("leasing-1", "Leasing office 1", APARTMENTS, "300", None, True),
    ("leasing-2", "Leasing office 2", APARTMENTS, "301", None, True),
    ("maintenance", "Maintenance on call", APARTMENTS, "302", None, True),
    ("office", "Manager's office", APARTMENTS, "303", None, True),
]
SALES = ["avery", "jordan", "morgan"]
SUPPORT = ["riley", "casey", "taylor"]
OFFICE_WEEK = {d: ["08:00-17:00"] for d in ("mon", "tue", "wed", "thu", "fri")}


def document() -> Dict[str, Any]:
    """The demo's phone-system document (app/document/model.py), as a published version holds it."""
    site = lambda main, loc, hours: {"emergency_location": loc, "emergency_number": main, "caller_id": main, "hours": hours}   # noqa: E731
    users = {k: {"name": name, "site": s, "extension": ext, **({"direct_number": direct, "show": "direct"} if direct else {}),
                 **({} if vm else {"voicemail": False})} for k, name, s, ext, direct, vm in PEOPLE}
    return {
        "version": 1,
        "protections": None,
        "sites": {HQ: site(MAIN_HQ, "main", "office"), WAREHOUSE: site(MAIN_WAREHOUSE, "main", "shifts"),
                  APARTMENTS: site(LEASING, "main", "leasing")},
        "hours": {"office": {"week": OFFICE_WEEK, "holidays": "us-federal"},
                  "shifts": {"week": {d: ["06:00-22:00"] for d in ("mon", "tue", "wed", "thu", "fri")} | {"sat": ["07:00-15:00"]}, "holidays": "none"},
                  "leasing": {"week": {d: ["09:00-18:00"] for d in ("mon", "tue", "wed", "thu", "fri")} | {"sat": ["10:00-16:00"]}, "holidays": "us-federal"}},
        "numbers": {
            MAIN_HQ: {"site": HQ, "open": {"menu": "main"}, "closed": {"voicemail": "company"}},
            MAIN_WAREHOUSE: {"site": WAREHOUSE, "open": {"group": "shipping"}, "closed": {"voicemail": "shipping"}},
            DOCK: {"site": WAREHOUSE, "open": {"user": "dock"}},
            LEASING: {"site": APARTMENTS, "open": {"group": "leasing"}, "closed": {"voicemail": "leasing"}},
            MAINTENANCE: {"site": APARTMENTS, "open": {"user": "maintenance"}},
            **{direct: {"site": s, "open": {"user": k}} for k, _name, s, _e, direct, _v in PEOPLE if direct},
        },
        "menus": {"main": {"greeting": "Thank you for calling Photon Demo. For sales, press 1. For support, press 2. For accounts, press 3. "
                                       "For the front desk, press 0.",
                           "options": {"1": {"group": "sales"}, "2": {"group": "support"}, "3": {"user": "quinn"}, "0": {"user": "reception"}},
                           "timeout": {"user": "reception"}}},
        "groups": {"sales": {"members": SALES, "strategy": "simultaneous", "ring_seconds": 20, "then": {"voicemail": "sales"}},
                   "support": {"members": SUPPORT, "strategy": "simultaneous", "ring_seconds": 20, "then": {"voicemail": "support"}},
                   "shipping": {"members": ["shipping", "dock", "supervisor"], "strategy": "simultaneous", "ring_seconds": 25, "then": {"voicemail": "shipping"}},
                   "leasing": {"members": ["leasing-1", "leasing-2", "office"], "strategy": "sequence", "ring_seconds": 15, "then": {"voicemail": "leasing"}}},
        "users": users,
        "pages": {"warehouse": {"name": "Warehouse paging", "site": WAREHOUSE, "extension": "290",
                                "members": ["shipping", "dock", "forklift-1", "forklift-2", "supervisor", "speaker-north", "speaker-south"]}},
        "boxes": {"company": {"name": "Company mailbox"}, "sales": {"name": "Sales"}, "support": {"name": "Support"},
                  "shipping": {"name": "Shipping"}, "leasing": {"name": "Leasing office"}},
        "calling": {"national": True, "toll_free": True, "international": []},
    }


def emergency_locations() -> Dict[str, Dict[str, Any]]:
    """Each phone site's 911 location: its city only, and plainly not a real address (never sent to a carrier: the demo has none)."""
    return {s: {"street": "Demo site, not a real address", "unit": "", "city": SITES[s][2], "state": SITES[s][3], "zip": ""} for s in PHONE_SITES}
