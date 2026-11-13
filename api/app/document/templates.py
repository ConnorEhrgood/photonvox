"""Templates: a whole phone system from a few answers (ARCHITECTURE §3: "a 30-person office in minutes"). A template is a function of the
site, its emergency location, the main number and the users; the integrator then changes anything in the builder. Photon's first templates are
Connor's to name (ARCHITECTURE §22 question 11); these two are the shapes most offices start from."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping

WEEKDAYS_8_TO_5 = {d: ["08:00-17:00"] for d in ("mon", "tue", "wed", "thu", "fri")}


def _base(site: str, location: str, main: str, users: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "version": 1,
        "sites": {site: {"emergency_location": location, "emergency_number": main, "caller_id": main, "hours": "office"}},
        "hours": {"office": {"week": WEEKDAYS_8_TO_5, "holidays": "us-federal"}},
        "users": dict(users),
        "boxes": {"general": {"name": "General mailbox"}},
        "calling": {"national": True, "toll_free": True, "international": []},
    }


def ring_everyone(site: str, location: str, main: str, users: Mapping[str, Any]) -> Dict[str, Any]:
    """Small office: in hours the main number rings everyone at once, then the general mailbox; after hours, straight to the mailbox."""
    d = _base(site, location, main, users)
    d["groups"] = {"everyone": {"members": sorted(users), "then": {"voicemail": "general"}}}
    d["numbers"] = {main: {"site": site, "open": {"group": "everyone"}, "closed": {"voicemail": "general"}}}
    return d


def front_desk_menu(site: str, location: str, main: str, users: Mapping[str, Any]) -> Dict[str, Any]:
    """A menu in hours ("for the front desk, press 1; to leave a message, press 2"), the front desk being everyone until the integrator
    narrows it; after hours, the general mailbox."""
    d = ring_everyone(site, location, main, users)
    d["menus"] = {"main": {"greeting": "Thank you for calling. For the front desk, press 1. To leave a message, press 2.",
                           "options": {"1": {"group": "everyone"}, "2": {"voicemail": "general"}}, "timeout": {"group": "everyone"}}}
    d["numbers"][main]["open"] = {"menu": "main"}
    return d


TEMPLATES: Dict[str, Dict[str, Any]] = {
    "ring-everyone": {"name": "Small office", "description": "The main number rings everyone in office hours, then the mailbox.", "build": ring_everyone},
    "front-desk-menu": {"name": "Front desk menu", "description": "A short menu in office hours: front desk or a message.", "build": front_desk_menu},
}


def catalog() -> List[Dict[str, str]]:
    return [{"key": k, "name": t["name"], "description": t["description"]} for k, t in TEMPLATES.items()]


def build(key: str, site: str, location: str, main: str, users: Mapping[str, Any]) -> Dict[str, Any]:
    fn: Callable[..., Dict[str, Any]] = TEMPLATES[key]["build"]
    return fn(site, location, main, users)
