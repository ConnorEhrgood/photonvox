"""Who may make which change to a phone system's draft (security review H1, 2026-11-13). CRITICAL module (100% branch coverage).

`vox.phone_system.build` lets someone build; on top of it:
- a change that widens what may be dialed (an international country, a blocked category or number let through, a block removed, national or
  toll-free switched back on, a higher spend limit) or switches on eavesdrop or intercept needs `vox.calling.policy` (owners);
- a change to the organization's numbers needs `vox.number.manage`;
- someone limited to some sites may change only those sites' people, numbers, doors and site settings, nothing organization-wide (hours, menus,
  groups, mailboxes, calling, features, voice).
"""
from __future__ import annotations

from typing import Any, List, Set

from app.document.model import PhoneSystem

ORG_WIDE = ("hours", "menus", "groups", "boxes", "calling", "features", "voice")


def widened(old: PhoneSystem, new: PhoneSystem) -> List[str]:
    """What the change opens up, in words; empty when it opens nothing."""
    o, n = old.calling, new.calling
    out = []
    if set(n.international) - set(o.international):
        out.append("international countries switched on: " + ", ".join(sorted(set(n.international) - set(o.international))))
    if n.national and not o.national:
        out.append("national calls switched on")
    if n.toll_free and not o.toll_free:
        out.append("toll-free calls switched on")
    if set(n.blocking.allow) - set(o.blocking.allow):
        out.append("blocked categories let through: " + ", ".join(sorted(set(n.blocking.allow) - set(o.blocking.allow))))
    if set(n.blocking.allow_numbers) - set(o.blocking.allow_numbers):
        out.append("blocked numbers let through")
    if set(o.blocking.block) - set(n.blocking.block):
        out.append("numbers no longer blocked")
    if n.spend_limit_usd > o.spend_limit_usd:
        out.append(f"daily spend limit raised to ${n.spend_limit_usd}")
    for f in ("eavesdrop", "intercept"):
        if getattr(new.features, f) and not getattr(old.features, f):
            out.append(f"{f} switched on")
    return out


def numbers_changed(old: PhoneSystem, new: PhoneSystem) -> bool:
    return old.numbers != new.numbers


def touched_sites(old: PhoneSystem, new: PhoneSystem) -> Set[str]:
    """The sites a change touches (their people, numbers, settings); "*" when it touches something organization-wide."""
    out: Set[str] = set()
    if any(getattr(old, part) != getattr(new, part) for part in ORG_WIDE):
        out.add("*")
    for part, site_of in (("users", lambda x: x.site), ("numbers", lambda x: x.site), ("doors", lambda x: x.site), ("pages", lambda x: x.site)):
        a, b = getattr(old, part), getattr(new, part)
        for key in set(a) | set(b):
            if a.get(key) != b.get(key):
                out |= {site_of(x) for x in (a.get(key), b.get(key)) if x is not None}
    for key in set(old.sites) | set(new.sites):
        if old.sites.get(key) != new.sites.get(key):
            out.add(key)
    return out


def refusal(old: PhoneSystem, new: PhoneSystem, can: Any, reach_all: bool, reach_sites: Set[str]) -> str:
    """Why this person may not make this change, in a sentence; empty when they may. `can(capability)` is their role's check."""
    opened = widened(old, new)
    if opened and not can("vox.calling.policy"):
        return "Only an owner can open up calling: " + "; ".join(opened) + "."
    if numbers_changed(old, new) and not can("vox.number.manage"):
        return "Your role does not include changing the organization's numbers."
    if not reach_all:
        touched = touched_sites(old, new)
        if "*" in touched:
            return "Your access is limited to some sites: hours, menus, groups, mailboxes and calling are the whole organization's."
        if not touched <= reach_sites:
            return "Your access is limited to some sites: this changes another site."
    return ""
