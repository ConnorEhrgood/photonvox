"""The reference client every product vendors: pull the directory's changes into your Projection, verify a notice, resolve a person at first sign-in.

    client = DirectoryClient("https://api.account.photonind.com", credential, MyProjection(), notice_secrets=[...])
    client.sync_once()                         # on start, every few minutes, and when a notice arrives
    client.handle_notice(request.headers["X-PhotonID-Signature"], raw_body)     # in POST /directory/v1/notify

Pure Python plus httpx. Nothing here talks to your database: that is the Projection."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import httpx

from .notice import NoticeError, verify_notice
from .projection import KINDS, Doc, Projection

__all__ = ["DirectoryClient", "DirectoryError", "AuthError", "Change", "SyncResult", "Resolved", "NoticeError"]
_ORDER = {k: i for i, k in enumerate(KINDS)}      # organizations first, access last (the copy must tolerate any order; this is only tidy)


class DirectoryError(Exception):
    """The directory answered with something unexpected, or could not be reached."""


class AuthError(DirectoryError):
    """The credential was refused (401): it was revoked, expired after a rotation, or is wrong."""


@dataclass(frozen=True)
class Change:
    seq: int
    kind: str
    key: str
    op: str                                  # "upsert" or "remove"
    data: Optional[Doc] = None

    @staticmethod
    def parse(raw: Dict[str, Any]) -> "Change":
        if raw["kind"] not in KINDS or raw["op"] not in ("upsert", "remove"):
            raise DirectoryError(f"unknown change {raw.get('kind')!r}/{raw.get('op')!r}")
        return Change(int(raw["seq"]), raw["kind"], str(raw["key"]), raw["op"], raw.get("data"))


@dataclass
class SyncResult:
    changes: int = 0                         # entities upserted or removed
    pages: int = 0
    snapshot: bool = False                   # a full snapshot was taken (first sync, or the directory asked for a restart)
    cursor: int = 0
    removed_stale: int = 0                   # snapshot only: entities the copy held that the directory no longer has


@dataclass(frozen=True)
class Resolved:
    person: Doc
    access: List[Doc]
    organizations: List[Doc]
    sites: List[Doc]
    as_of: int


@dataclass
class DirectoryClient:
    base_url: str
    credential: str                          # "<client id>.<secret>"
    projection: Projection
    notice_secrets: Sequence[str] = ()
    http: Optional[httpx.Client] = None      # inject one to test (an httpx.MockTransport, or a TestClient)
    page_size: int = 500
    timeout_s: float = 15.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # -- plumbing ------------------------------------------------------------------------------------------------------------------------------

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        client = self.http or httpx.Client(timeout=self.timeout_s)
        try:
            r = client.get(self.base_url.rstrip("/") + path if self.http is None else path, params=params, headers={"Authorization": f"Bearer {self.credential}"})
        except httpx.HTTPError as e:
            raise DirectoryError(f"directory unreachable: {type(e).__name__}") from e
        finally:
            if self.http is None:
                client.close()
        if r.status_code == 401:
            raise AuthError("the directory refused this credential")
        return r

    # -- pulling -------------------------------------------------------------------------------------------------------------------------------

    def sync_once(self) -> SyncResult:
        """Bring the copy up to date: pull until there is nothing more. Safe to call from several places; calls are serialized.

        A first sync (cursor 0) is a snapshot. If the directory says the cursor cannot be continued (409 reset: removals this copy never saw were
        purged, or the directory was restored from an older backup) a new snapshot is taken and what it does not contain is dropped."""
        with self._lock:
            cursor = self.projection.get_cursor()
            if cursor == 0:
                return self._snapshot()
            result = SyncResult(cursor=cursor)
            while True:
                r = self._get("/v1/sync", {"cursor": cursor, "limit": self.page_size})
                if r.status_code == 409 and r.json().get("reset"):
                    return self._snapshot()
                page = self._page(r)
                changes = [Change.parse(c) for c in page["changes"]]
                with self.projection.transaction():
                    self._apply(changes)
                    if page["cursor"] != cursor:
                        self.projection.set_cursor(page["cursor"])
                cursor = page["cursor"]
                result.pages, result.changes, result.cursor = result.pages + 1, result.changes + len(changes), cursor
                if not page["has_more"]:
                    return result

    def _snapshot(self) -> SyncResult:
        """Read everything from the beginning. The stored cursor is not moved until the whole snapshot is in and the stale entities are gone, so a
        crash half-way leaves the copy where it was and the next attempt starts the snapshot again."""
        seen: Dict[str, Set[str]] = {k: set() for k in KINDS}
        result = SyncResult(snapshot=True)
        cursor = 0
        while True:
            # `snapshot=true`: these pages continue one snapshot, so they are not refused when the cursor lies below the forgotten-removals floor.
            r = self._get("/v1/sync", {"cursor": cursor, "limit": self.page_size, "snapshot": "true"})
            page = self._page(r)
            changes = [Change.parse(c) for c in page["changes"]]
            with self.projection.transaction():
                self._apply(changes)
            for c in changes:
                if c.op == "upsert":
                    seen[c.kind].add(c.key)
                else:
                    seen[c.kind].discard(c.key)
            cursor = page["cursor"]
            result.pages, result.changes = result.pages + 1, result.changes + len(changes)
            if not page["has_more"]:
                break
        with self.projection.transaction():
            for kind in KINDS:
                for key in set(self.projection.known_keys(kind)) - seen[kind]:
                    self.projection.remove(kind, key)
                    result.removed_stale += 1
            self.projection.set_cursor(cursor)
        result.cursor = cursor
        return result

    @staticmethod
    def _page(r: httpx.Response) -> Dict[str, Any]:
        if r.status_code != 200:
            raise DirectoryError(f"directory answered {r.status_code}")
        page = r.json()
        for field_ in ("cursor", "has_more", "changes"):
            if field_ not in page:
                raise DirectoryError(f"sync answer without {field_!r}")
        return page

    def _apply(self, changes: Iterable[Change]) -> None:
        p = self.projection
        upserts = {"organization": p.upsert_organization, "site": p.upsert_site, "person": p.upsert_person, "access": p.upsert_access}
        changes = list(changes)
        for c in (c for c in changes if c.op == "remove"):
            p.remove(c.kind, c.key)
        for c in sorted((c for c in changes if c.op == "upsert"), key=lambda c: _ORDER[c.kind]):
            upserts[c.kind](c.data or {})

    # -- notices -------------------------------------------------------------------------------------------------------------------------------

    def verify_notice(self, header: str, body: bytes, now: Optional[int] = None) -> Dict[str, Any]:
        return verify_notice(header, body, self.notice_secrets, now)

    def handle_notice(self, header: str, body: bytes, now: Optional[int] = None) -> Optional[SyncResult]:
        """Verify a notice and pull. Raises NoticeError for one that is not genuine (answer 401 and do nothing). Returns None when the notice is
        about changes this copy already has (a late or repeated notice), otherwise the result of the pull. A notice is a hint: its content is never
        trusted for anything but "hurry"."""
        notice = self.verify_notice(header, body, now)
        seq = notice.get("seq")
        if isinstance(seq, int) and seq <= self.projection.get_cursor():
            return None
        return self.sync_once()

    # -- first sign-in -------------------------------------------------------------------------------------------------------------------------

    def resolve(self, sub: str) -> Optional[Resolved]:
        """What the directory knows of the person with this sign-in identity, for the first sign-in after an invitation (before your copy has caught
        up). None: nothing yet, so say "your access is being set up". Use `sync_once()` afterwards to bring the copy up to date; do not write the
        resolved documents into the copy yourself (they may be older than what a pull has already applied)."""
        r = self._get("/v1/resolve", {"sub": sub})
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise DirectoryError(f"directory answered {r.status_code}")
        b = r.json()
        return Resolved(b["person"], b["access"], b["organizations"], b["sites"], b["as_of"])

    # -- publishing your catalogue -------------------------------------------------------------------------------------------------------------

    def publish_roles(self, product_key: str, roles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Publish this product's full role catalogue (see the directory's contract). Roles not listed are retired."""
        client = self.http or httpx.Client(timeout=self.timeout_s)
        try:
            r = client.put(self.base_url.rstrip("/") + f"/v1/products/{product_key}/roles" if self.http is None else f"/v1/products/{product_key}/roles",
                           json={"roles": roles}, headers={"Authorization": f"Bearer {self.credential}"})
        except httpx.HTTPError as e:
            raise DirectoryError(f"directory unreachable: {type(e).__name__}") from e
        finally:
            if self.http is None:
                client.close()
        if r.status_code == 401:
            raise AuthError("the directory refused this credential")
        if r.status_code != 200:
            raise DirectoryError(f"directory answered {r.status_code}: {r.text[:200]}")
        return r.json()
