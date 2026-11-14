"""Whether a phone-system document may be published. CRITICAL module (100% branch coverage).

Everything here is checked before the compiler runs and before anything reaches an engine: a document with any problem is not published, and
the integrator sees each problem by its path ("numbers.+17245550100.open") in words. The rules are ARCHITECTURE §8 and §11: every reference
resolves; every site has a validated emergency location and an emergency number the organization holds (so a PSAP's call back rings something);
caller ID only from held numbers; extensions unique and never colliding with service codes or a site's outside-line prefix; no loop of automatic
forwards.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet, Dict, List, Mapping, Optional, Set

from app.document.model import PhoneSystem, Target, ToGroup, ToMenu, ToUser, ToVoicemail

# N11 service codes and 933 (address read-back): never extensions. 911 is among them.
SERVICE_CODES = frozenset({"211", "311", "411", "511", "611", "711", "811", "911", "933", "988"})


@dataclass(frozen=True, order=True)
class Problem:
    path: str
    code: str
    message: str


def _target_problem(doc: PhoneSystem, t: Target, path: str) -> Optional[Problem]:
    if isinstance(t, ToUser) and t.user not in doc.users:
        return Problem(path, "unknown_user", f"There is no user {t.user!r}.")
    if isinstance(t, ToGroup) and t.group not in doc.groups:
        return Problem(path, "unknown_group", f"There is no ring group {t.group!r}.")
    if isinstance(t, ToMenu) and t.menu not in doc.menus:
        return Problem(path, "unknown_menu", f"There is no menu {t.menu!r}.")
    if isinstance(t, ToVoicemail) and t.voicemail not in doc.users and t.voicemail not in doc.boxes:
        return Problem(path, "unknown_voicemail", f"There is no voicemail box {t.voicemail!r}.")
    return None


def _automatic_next(doc: PhoneSystem, node: str) -> Optional[str]:
    """Where a group or menu sends a call by itself (a group's "then", a menu's timeout), as "group:x" / "menu:y", or None."""
    kind, name = node.split(":", 1)
    t = doc.groups[name].then if kind == "group" else doc.menus[name].timeout
    if isinstance(t, ToGroup) and t.group in doc.groups:
        return f"group:{t.group}"
    if isinstance(t, ToMenu) and t.menu in doc.menus:
        return f"menu:{t.menu}"
    return None


def _loops(doc: PhoneSystem) -> List[Problem]:
    """A call that goes round a chain of groups and menus by itself forever (a group whose "then" leads back to it)."""
    out: List[Problem] = []
    reported: Set[str] = set()
    for start in [f"group:{g}" for g in sorted(doc.groups)] + [f"menu:{m}" for m in sorted(doc.menus)]:
        seen: List[str] = []
        node: Optional[str] = start
        while node is not None and node not in seen:
            seen.append(node)
            node = _automatic_next(doc, node)
        if node is not None and node == start and start not in reported:
            cycle = seen[seen.index(node):]
            reported.update(cycle)
            out.append(Problem(f"{start.split(':')[0]}s.{start.split(':')[1]}", "loop",
                               "Calls would go round " + " → ".join(cycle + [node]) + " forever. Send one of them somewhere that ends."))
    return out


def problems(doc: PhoneSystem, validated_locations: Mapping[str, AbstractSet[str]], assigned: Optional[AbstractSet[str]] = None) -> List[Problem]:
    """Every problem in the document, sorted by path. `validated_locations`: site id -> the emergency locations validated for that site.
    `assigned`: the numbers Photon has assigned to this organization (the held-number inventory); a document may only use those (security
    review C2). Every caller that publishes passes it; None is for checking a document's own consistency alone."""
    out: List[Problem] = []
    held = set(doc.numbers)
    if assigned is not None:
        for number in sorted(held - set(assigned)):
            out.append(Problem(f"numbers.{number}", "number_not_assigned", "This number is not one of the organization's: Photon assigns numbers."))

    for sid, site in doc.sites.items():
        p = f"sites.{sid}"
        if site.emergency_location not in validated_locations.get(sid, ()):
            out.append(Problem(f"{p}.emergency_location", "emergency_location_unvalidated",
                               "This site's emergency address has not been validated. A site gets no phones until it is (911)."))
        if site.emergency_number not in held:
            out.append(Problem(f"{p}.emergency_number", "not_held", "The emergency number must be one of the organization's numbers, so a 911 call back rings someone."))
        if site.caller_id not in held:
            out.append(Problem(f"{p}.caller_id", "not_held", "Calls can show only the organization's own numbers."))
        if site.hours is not None and site.hours not in doc.hours:
            out.append(Problem(f"{p}.hours", "unknown_hours", f"There are no hours called {site.hours!r}."))

    for num, n in doc.numbers.items():
        p = f"numbers.{num}"
        if n.site not in doc.sites:
            out.append(Problem(f"{p}.site", "unknown_site", "This number's site is not in the phone system."))
        for name, t in (("open", n.open), ("closed", n.closed)):
            if t is not None:
                prob = _target_problem(doc, t, f"{p}.{name}")
                if prob:
                    out.append(prob)
        hours = n.hours or (doc.sites[n.site].hours if n.site in doc.sites else None)
        if n.hours is not None and n.hours not in doc.hours:
            out.append(Problem(f"{p}.hours", "unknown_hours", f"There are no hours called {n.hours!r}."))
        if n.closed is not None and hours is None:
            out.append(Problem(f"{p}.closed", "no_hours", "A number with a closed outcome needs hours (its own, or its site's)."))

    for mid, m in doc.menus.items():
        for digit, t in sorted(m.options.items()):
            prob = _target_problem(doc, t, f"menus.{mid}.options.{digit}")
            if prob:
                out.append(prob)
        prob = _target_problem(doc, m.timeout, f"menus.{mid}.timeout") if m.timeout else None
        if prob:
            out.append(prob)

    for gid, g in doc.groups.items():
        for i, member in enumerate(g.members):
            if member not in doc.users:
                out.append(Problem(f"groups.{gid}.members.{i}", "unknown_user", f"There is no user {member!r}."))
        if len(set(g.members)) != len(g.members):
            out.append(Problem(f"groups.{gid}.members", "duplicate_member", "Someone is in this group twice."))
        if g.then is not None:
            prob = _target_problem(doc, g.then, f"groups.{gid}.then")
            if prob:
                out.append(prob)

    by_ext: Dict[str, str] = {}
    by_direct: Dict[str, str] = {}
    for uid, u in doc.users.items():
        p = f"users.{uid}"
        if u.site not in doc.sites:
            out.append(Problem(f"{p}.site", "unknown_site", "This user's site is not in the phone system."))
        elif doc.sites[u.site].outside_prefix and u.extension.startswith(doc.sites[u.site].outside_prefix):
            out.append(Problem(f"{p}.extension", "extension_prefix", f"At this site {doc.sites[u.site].outside_prefix} starts an outside call, so no extension may start with it."))
        if u.extension in SERVICE_CODES:
            out.append(Problem(f"{p}.extension", "extension_reserved", f"{u.extension} is a service number (911, 988, 311…) and can't be an extension."))
        if u.extension in by_ext:
            out.append(Problem(f"{p}.extension", "extension_taken", f"Extension {u.extension} is already {by_ext[u.extension]}'s."))
        else:
            by_ext[u.extension] = uid
        if u.direct_number is not None:
            if u.direct_number not in held:
                out.append(Problem(f"{p}.direct_number", "not_held", "A direct number must be one of the organization's numbers."))
            if u.direct_number in by_direct:
                out.append(Problem(f"{p}.direct_number", "direct_taken", f"That number is already {by_direct[u.direct_number]}'s direct number."))
            else:
                by_direct[u.direct_number] = uid
        elif u.show == "direct":
            out.append(Problem(f"{p}.show", "no_direct_number", "This user has no direct number to show."))
        if u.caller_id and u.caller_id not in held:
            out.append(Problem(f"{p}.caller_id", "not_held", "What a user's calls show must be one of the organization's numbers."))

    for did, d in doc.doors.items():
        p = f"doors.{did}"
        if d.site not in doc.sites:
            out.append(Problem(f"{p}.site", "unknown_site", "This door's site is not in the phone system."))
        elif doc.sites[d.site].outside_prefix and d.extension.startswith(doc.sites[d.site].outside_prefix):
            out.append(Problem(f"{p}.extension", "extension_prefix", f"At this site {doc.sites[d.site].outside_prefix} starts an outside call, so no extension may start with it."))
        if d.extension in SERVICE_CODES:
            out.append(Problem(f"{p}.extension", "extension_reserved", f"{d.extension} is a service number (911, 988, 311…) and can't be an extension."))
        if d.extension in by_ext:
            out.append(Problem(f"{p}.extension", "extension_taken", f"Extension {d.extension} is already {by_ext[d.extension]}'s."))
        else:
            by_ext[d.extension] = did
        for name, t in (("open", d.open), ("closed", d.closed)):
            if t is not None:
                prob = _target_problem(doc, t, f"{p}.{name}")
                if prob:
                    out.append(prob)
        hours = d.hours or (doc.sites[d.site].hours if d.site in doc.sites else None)
        if d.hours is not None and d.hours not in doc.hours:
            out.append(Problem(f"{p}.hours", "unknown_hours", f"There are no hours called {d.hours!r}."))
        if d.closed is not None and hours is None:
            out.append(Problem(f"{p}.closed", "no_hours", "A door with an after-hours outcome needs hours (its own, or its site's)."))

    for pid, pg in doc.pages.items():
        p = f"pages.{pid}"
        if pg.site not in doc.sites:
            out.append(Problem(f"{p}.site", "unknown_site", "This paging group's site is not in the phone system."))
        elif doc.sites[pg.site].outside_prefix and pg.extension.startswith(doc.sites[pg.site].outside_prefix):
            out.append(Problem(f"{p}.extension", "extension_prefix", f"At this site {doc.sites[pg.site].outside_prefix} starts an outside call, so no extension may start with it."))
        if pg.extension in SERVICE_CODES:
            out.append(Problem(f"{p}.extension", "extension_reserved", f"{pg.extension} is a service number (911, 988, 311…) and can't be an extension."))
        if pg.extension in by_ext:
            out.append(Problem(f"{p}.extension", "extension_taken", f"Extension {pg.extension} is already {by_ext[pg.extension]}'s."))
        else:
            by_ext[pg.extension] = pid
        for i, m in enumerate(pg.members):
            if m not in doc.users:
                out.append(Problem(f"{p}.members.{i}", "unknown_user", f"There is no user {m!r}."))
        if len(set(pg.members)) != len(pg.members):
            out.append(Problem(f"{p}.members", "duplicate_member", "Someone is in this paging group twice."))

    out.extend(_loops(doc))
    return sorted(out)
