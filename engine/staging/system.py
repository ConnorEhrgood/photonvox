#!/usr/bin/env python3
"""The staging test phone system (engine/staging/prove-publish.sh), written to .state/adapter.json and its .context.json.

    python3 engine/staging/system.py [full|reduced]

Two sites (Los Angeles: unreachable → voicemail, dials 9 for an outside line; New York: unreachable → hang up), four users, a menu, a group, a
shared box, six numbers, and call blocking with a listed prefix and a number let through a blocked category. The hours are made from the clock
so the time zone shows: "open-now" is open at this moment in Los Angeles; "utc-window" would be open now only if the engine ignored the
site's time zone (it is the same hours in UTC), so it must route as closed. "reduced" removes a user, a number and a menu option (the removal
test).
"""
import datetime as dt
import json
import pathlib
import sys
from zoneinfo import ZoneInfo

S1, S2 = "a1111111-1111-4111-8111-111111111111", "a2222222-2222-4222-8222-222222222222"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def window(now: dt.datetime) -> tuple:
    h = now.hour
    start, end = max(0, h - 1), min(24, h + 2)
    return DAYS[now.weekday()], [f"{start:02d}:00-{end:02d}:00"]


def document(mode: str) -> dict:
    utc = dt.datetime.now(dt.timezone.utc)
    la_day, la_span = window(utc.astimezone(ZoneInfo("America/Los_Angeles")))
    utc_day, utc_span = window(utc)
    doc = {
        "version": 1,
        "sites": {
            S1: {"emergency_location": "loc-la", "emergency_number": "+12125550300", "caller_id": "+12125550300", "unreachable": "voicemail",
                 "outside_prefix": "9"},
            S2: {"emergency_location": "loc-ny", "emergency_number": "+12125550303", "caller_id": "+12125550303", "unreachable": "none"},
        },
        "hours": {"open-now": {"week": {la_day: la_span}}, "utc-window": {"week": {utc_day: utc_span}}},
        "numbers": {
            "+12125550300": {"site": S1, "open": {"menu": "main"}},
            "+12125550301": {"site": S1, "open": {"user": "u1"}, "closed": {"user": "u2"}, "hours": "open-now"},
            "+12125550302": {"site": S1, "open": {"user": "u1"}, "closed": {"user": "u2"}, "hours": "utc-window"},
            "+12125550303": {"site": S2, "open": {"user": "u3"}},
            "+12125550304": {"site": S1, "open": {"user": "u4"}},
            "+12125550305": {"site": S1, "open": {"group": "desk"}},
        },
        "menus": {"main": {"greeting": "Thanks for calling. For the desk, press 1. For New York, press 2.",
                           "options": {"1": {"group": "desk"}, "2": {"user": "u3"}}, "timeout": {"voicemail": "general"}}},
        "groups": {"desk": {"members": ["u1", "u2"], "then": {"voicemail": "general"}}},
        "users": {
            "u1": {"name": "Ann Desk", "site": S1, "extension": "301", "direct_number": "+12125550301", "show": "direct"},
            "u2": {"name": "Bo Desk", "site": S1, "extension": "302"},
            "u3": {"name": "Cy York", "site": S2, "extension": "303"},
            "u4": {"name": "Di Away", "site": S1, "extension": "304"},
        },
        "boxes": {"general": {"name": "General mailbox"}},
        "calling": {"national": True, "toll_free": True, "international": [],
                    "blocking": {"block": ["+1212555999"], "allow_numbers": ["+1876555"]}},
    }
    if mode == "reduced":
        doc["users"].pop("u4")
        doc["numbers"].pop("+12125550304")
        doc["menus"]["main"]["options"].pop("2")
    return doc


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    out = pathlib.Path(__file__).resolve().parent / ".state"
    out.mkdir(exist_ok=True)
    (out / "adapter.json").write_text(json.dumps(document(mode), indent=1))
    (out / "adapter.context.json").write_text(json.dumps({
        "domain": "adapter.vox.test", "phone_system_id": "7a6b0000-0000-4000-8000-0000000000a5",
        "timezones": {S1: "America/Los_Angeles", S2: "America/New_York"}, "validated_locations": {S1: ["loc-la"], S2: ["loc-ny"]}}, indent=1))
    print(f"{mode}: {out / 'adapter.json'}")
