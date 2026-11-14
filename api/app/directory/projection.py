"""Our read-only copy of the PhotonID directory, as the reference client's `Projection` (photonid_directory_client/projection.py has the rules).

Only the system role writes these tables. The copy is eventually consistent and order-tolerant: the four kinds arrive in the order the directory
changed them, page by page, so no foreign keys tie them together (migration 0002 drops them). Every method is idempotent. Nothing is hard-deleted that
PhotonVox's own data will point at: an organization that is no longer entitled is marked `removed` (its access ends, its history stays), as are
sites; a person who is removed is deactivated and loses all access.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, Iterator, List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app import audit
from app.models import Access, Person, Site, SyncState, Tenant
from app.roles import ROLES
from photonid_directory_client.projection import Doc, Projection


class BadDocument(Exception):
    """A document the directory sent that we cannot store (a malformed id or time). The batch is rolled back; the error is kept in `sync_state`."""


def _uuid(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as e:
        raise BadDocument(f"not a UUID: {str(value)[:40]!r}") from e


def _when(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise BadDocument(f"not a time: {value[:40]!r}") from e


# Photon's own partner in the directory: every member of it, in any role, is Photon staff (decided 2026-11-13, as in PhotonConsole).
PHOTON_PARTNER = "photon"


def staff_flags(doc: Doc) -> tuple:
    """(is_staff, is_platform_admin) from a person document. Photon staff are the platform administrators and every member, in any role, of partner
    Photon. A document from before the directory sent these fields, or a malformed one, gives neither (the client's contract)."""
    is_platform_admin = doc.get("platform_admin") is True
    partners = doc.get("partners") if isinstance(doc.get("partners"), list) else []
    in_photon = any(isinstance(p, dict) and p.get("slug") == PHOTON_PARTNER for p in partners)
    return is_platform_admin or in_photon, is_platform_admin


def _scope(scope: Dict[str, Any]) -> tuple:
    """(whole organization?, site ids) from the directory's {"type": "all"} | {"type": "sites", "site_ids": [...]}."""
    if scope.get("type") == "all":
        return True, []
    return False, [_uuid(s) for s in scope["site_ids"]]


class DbProjection(Projection):
    def __init__(self, db: Session) -> None:
        self.db = db

    # -- the cursor (one row, kept with the sync's own bookkeeping) -------------------------------------------------------------------------------

    def _state(self) -> SyncState:
        state = self.db.get(SyncState, 1)
        if state is None:
            state = SyncState(id=1, cursor=0)
            self.db.add(state)
            self.db.flush()
        return state

    def get_cursor(self) -> int:
        return int(self._state().cursor)

    def set_cursor(self, cursor: int) -> None:
        self._state().cursor = cursor

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """A page and its cursor commit together or not at all: a savepoint inside the pull's own transaction."""
        with self.db.begin_nested():
            yield
            self.db.flush()

    # -- upserts ------------------------------------------------------------------------------------------------------------------------------------

    def upsert_organization(self, doc: Doc) -> None:
        tid = _uuid(doc["id"])
        row = self.db.get(Tenant, tid)
        if row is None:
            row = Tenant(id=tid)
            self.db.add(row)
        row.name, row.plan_key, row.home_region = doc["name"], doc.get("plan_key", ""), doc["home_region"]
        # The address (/org/<slug>/): a document from before the directory sent it keeps none until the next pull.
        row.slug, row.former_slugs = doc.get("slug") or None, sorted(doc.get("former_slugs") or [])
        row.partner_id = _uuid(doc["partner_id"]) if doc.get("partner_id") else None
        row.products = sorted(doc.get("products") or [])
        # An archived organization is not ours to serve: its access is kept but the tenant is "removed" like one that lost its entitlement.
        row.status = {"active": "active", "suspended": "suspended"}.get(doc["status"], "removed")
        self.db.flush()

    def upsert_site(self, doc: Doc) -> None:
        sid = _uuid(doc["id"])
        row = self.db.get(Site, sid)
        if row is None:
            row = Site(id=sid)
            self.db.add(row)
        row.tenant_id, row.slug, row.name = _uuid(doc["organization_id"]), doc["slug"], doc["name"]
        row.address, row.timezone = doc.get("address") or "", doc.get("timezone") or "UTC"
        row.latitude, row.longitude = doc.get("latitude"), doc.get("longitude")
        row.status = "active" if doc["status"] == "active" else "removed"
        self.db.flush()

    def upsert_person(self, doc: Doc) -> None:
        pid = _uuid(doc["id"])
        row = self.db.get(Person, pid)
        if row is None:
            row = Person(id=pid)
            self.db.add(row)
        row.sub, row.name, row.email = doc.get("sub") or None, doc.get("name", ""), doc.get("email", "")
        row.active = doc["status"] == "active"
        self._set_flags(row, *staff_flags(doc))
        self.db.flush()

    def _set_flags(self, row: Person, is_staff: bool, is_platform_admin: bool) -> None:
        """Staff and platform admin come from the directory only. A change is audited: it widens or narrows what someone may do across every
        organization."""
        before = (bool(row.is_staff), bool(row.is_platform_admin))
        row.is_staff, row.is_platform_admin = is_staff, is_platform_admin
        if before != (is_staff, is_platform_admin):
            audit.record(self.db, actor_id=None, actor_label="directory", actor_source="directory", action="directory.staff_flags",
                         target_type="person", target_id=row.id, email=row.email, is_staff=is_staff, is_platform_admin=is_platform_admin)

    def upsert_access(self, doc: Doc) -> None:
        pid, tid = _uuid(doc["person_id"]), _uuid(doc["organization_id"])
        if doc["role"] not in ROLES:
            # A role this build does not know (retired, or from a newer catalog): no access, and never a guess at what it meant.
            self.db.execute(delete(Access).where(Access.person_id == pid, Access.tenant_id == tid))
            return
        all_, sites = _scope(doc["scope"])
        others: List[Dict[str, Any]] = [{"role": o["role"], "scope": o["scope"], "source": o["source"]} for o in doc.get("others") or [] if o["role"] in ROLES]
        for o in others:
            _scope(o["scope"])        # validates the ids now, so a bad one fails the batch here and not on a later read
        row = self.db.get(Access, (pid, tid))
        if row is None:
            row = Access(person_id=pid, tenant_id=tid)
            self.db.add(row)
        row.role, row.scope_all, row.site_ids = doc["role"], all_, sites
        row.source, row.expires_at, row.others = doc["source"], _when(doc.get("expires_at")), others
        self.db.flush()

    # -- removals -----------------------------------------------------------------------------------------------------------------------------------

    def remove(self, kind: str, key: str) -> None:
        if kind == "organization":
            tid = _uuid(key)
            self.db.execute(update(Tenant).where(Tenant.id == tid).values(status="removed"))
            self.db.execute(delete(Access).where(Access.tenant_id == tid))
            self.db.execute(update(Site).where(Site.tenant_id == tid).values(status="removed"))
        elif kind == "site":
            self.db.execute(update(Site).where(Site.id == _uuid(key)).values(status="removed"))
        elif kind == "person":
            pid = _uuid(key)
            self.db.execute(update(Person).where(Person.id == pid).values(active=False))
            row = self.db.get(Person, pid)
            if row is not None:
                self._set_flags(row, False, False)
            self.db.execute(delete(Access).where(Access.person_id == pid))
        else:
            person, _, org = key.partition(":")
            self.db.execute(delete(Access).where(Access.person_id == _uuid(person), Access.tenant_id == _uuid(org)))
        self.db.flush()

    def known_keys(self, kind: str) -> Iterable[str]:
        if kind == "organization":
            return [str(i) for i in self.db.execute(select(Tenant.id).where(Tenant.status != "removed")).scalars()]
        if kind == "site":
            return [str(i) for i in self.db.execute(select(Site.id).where(Site.status != "removed")).scalars()]
        if kind == "person":
            return [str(i) for i in self.db.execute(select(Person.id).where(Person.active.is_(True))).scalars()]
        return [f"{p}:{t}" for p, t in self.db.execute(select(Access.person_id, Access.tenant_id)).all()]
