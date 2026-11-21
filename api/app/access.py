"""Who may do what in PhotonVox: pure functions over a person's grant. CRITICAL module (100% branch coverage).

The PhotonID directory decides a person's **grant** in an organization (role, whole organization or listed sites, direct or through a partner, an
optional expiry) and sends it with our copy of the directory. The role says which capabilities they have (app/roles.py). PhotonVox's own fine
limits (which extension is yours, which inboxes you see) arrive with the features that need them and will only ever narrow.

Site scope: a capability asked about a particular site is refused outside the grant's sites. A capability asked with no site is a role question
only; the caller then lists data through `visible_site_ids`, so a site-limited person never sees another site's rows (row-level security enforces
the same for sites). A route that acts on the whole organization asks `allowed_everywhere` instead: an entry covering the whole organization must
hold the capability, so a person limited to some sites is refused (audit 2026-11-17 §3.1; app/deps.py `require`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import AbstractSet, Any, FrozenSet, Optional, Tuple

from app.roles import ROLES


@dataclass(frozen=True)
class Entry:
    """One (role, scope) the directory sent for a person: the grant's own, or one of its lower-ranked `others`."""
    role: str
    scope_all: bool = True
    site_ids: FrozenSet[uuid.UUID] = frozenset()


@dataclass(frozen=True)
class Grant:
    role: str
    scope_all: bool = True
    site_ids: FrozenSet[uuid.UUID] = frozenset()
    source: str = "direct"                    # direct | partner
    expires_at: Optional[datetime] = None
    # The directory's `others`: lower-ranked entries that cover the rest (a site-limited admin who is also a whole-organization user). A person's role
    # at a site is the strongest entry that covers it; entries are never merged into a wider grant (suite ARCHITECTURE §5).
    others: Tuple[Entry, ...] = ()

    @classmethod
    def from_row(cls, row: Any) -> "Grant":
        others = []
        for o in row.others or ():
            scope = o["scope"]
            others.append(Entry(o["role"], scope["type"] == "all", frozenset(uuid.UUID(x) for x in scope.get("site_ids", ()))))
        return cls(role=row.role, scope_all=row.scope_all, site_ids=frozenset(row.site_ids or ()), source=row.source, expires_at=row.expires_at,
                   others=tuple(others))

    @property
    def entries(self) -> Tuple[Entry, ...]:
        return (Entry(self.role, self.scope_all, self.site_ids),) + self.others

    @property
    def reach_all(self) -> bool:
        """Some entry covers the whole organization."""
        return any(e.scope_all for e in self.entries)

    @property
    def reach_sites(self) -> FrozenSet[uuid.UUID]:
        """Every site some entry names (meaningless when `reach_all`)."""
        return frozenset().union(*(e.site_ids for e in self.entries))


def is_active(grant: Grant, now: datetime) -> bool:
    """A grant with an expiry (later: time-boxed elevated access) stops working at that instant, whatever the directory has synced since."""
    return grant.role in ROLES and (grant.expires_at is None or grant.expires_at > now)


def role_at(grant: Grant, site_id: uuid.UUID) -> Optional[str]:
    """The strongest role that applies at this site, or None when no entry covers it."""
    best: Optional[str] = None
    for e in grant.entries:
        if e.role in ROLES and (e.scope_all or site_id in e.site_ids) and (best is None or ROLES[e.role].rank > ROLES[best].rank):
            best = e.role
    return best


def allowed(grant: Grant, capability: str, now: datetime, site_id: Optional[uuid.UUID] = None) -> bool:
    if not is_active(grant, now):
        return False
    # With no site this is a question about the role alone (the strongest entry); at a site it is the strongest entry that covers it.
    role = grant.role if site_id is None else role_at(grant, site_id)
    return role is not None and capability in ROLES[role].capabilities


def narrowed(grant: Grant, capability: str) -> Grant:
    """The grant cut down to the entries whose role holds `capability`: its reach is where the person may use it. A site-limited admin who is
    also a whole-organization user reaches every site, but builds only at theirs (audit 2026-11-17 §3.1)."""
    keep = [e for e in grant.entries if e.role in ROLES and capability in ROLES[e.role].capabilities]
    if not keep:
        return Grant(grant.role, False, frozenset(), grant.source, grant.expires_at)      # reaches no site
    first, *rest = keep
    return Grant(first.role, first.scope_all, first.site_ids, grant.source, grant.expires_at, tuple(rest))


def allowed_everywhere(grant: Grant, capability: str, now: datetime) -> bool:
    """The capability for the whole organization: an entry that covers every site holds it."""
    return is_active(grant, now) and narrowed(grant, capability).reach_all


# Capabilities used only on organization-wide routes (app/deps.py `require` without `sites`): held through a site-limited entry they allow
# nothing, so `capabilities` does not offer them there (the web app would show a page the API refuses).
ORG_ONLY = frozenset({"vox.entry.manage"})


def capabilities(grant: Grant, now: datetime) -> FrozenSet[str]:
    """Everything the grant allows somewhere (the web app gates its buttons on this; the API checks again per request and per site)."""
    if not is_active(grant, now):
        return frozenset()
    found = frozenset().union(*(ROLES[e.role].capabilities for e in grant.entries if e.role in ROLES))
    return frozenset(c for c in found if c not in ORG_ONLY or narrowed(grant, c).reach_all)


def visible_site_ids(grant: Grant, all_site_ids: AbstractSet[uuid.UUID]) -> FrozenSet[uuid.UUID]:
    """Of the organization's sites, the ones this grant reaches."""
    return frozenset(all_site_ids) if grant.reach_all else frozenset(all_site_ids) & grant.reach_sites


def sees_member(actor: Grant, target: Grant) -> bool:
    """Whether a people list shows `target` to `actor`: everyone, for a whole-organization person; otherwise those who reach one of their sites."""
    return actor.reach_all or target.reach_all or bool(actor.reach_sites & target.reach_sites)
