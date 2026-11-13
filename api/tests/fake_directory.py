"""The directory for tests: the reference client's own `FakeDirectory` (vendored with the client; it keeps the real directory's rules: ordered changes,
tombstones, snapshots, 409 resets, signed notices) behind the small helpers this suite was written with (`add_org`, `add_site`, `add_person`, `grant`…)."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from photonid_directory_client.projection import Projection
from photonid_directory_client.testing import FakeDirectory as ReferenceFake


def _id() -> str:
    return str(uuid.uuid4())


class FakeDirectory:
    def __init__(self) -> None:
        self.ref = ReferenceFake(product="vox", notice_secret=settings.notice_secrets[0] if settings.notice_secrets else "pdn_fake")
        self.orgs: Dict[str, Dict[str, Any]] = {}
        self.people: Dict[str, Dict[str, Any]] = {}
        self.sites: Dict[str, Dict[str, Any]] = {}
        self.access: Dict[str, Dict[str, Any]] = {}
        self.down = False                       # True: nothing answers (a connect error)
        self.role_puts = 0                      # role catalogs the directory accepted
        real_handle = self.ref.handle

        def handle(request):
            if self.down:
                raise httpx.ConnectError("the fake directory is down", request=request)
            response = real_handle(request)
            if request.method == "PUT" and response.status_code == 200:
                self.role_puts += 1
            return response
        self.ref.handle = handle                # the reference fake builds its transport from this at `client()` time

    # ---- building the world ----

    def add_org(self, name: str = "Cedar Works", id: Optional[str] = None, partner_id: Optional[str] = None, region: str = "us-east", plan: str = "standard",
                status: str = "active", products: Optional[list] = None) -> str:
        extra = {"products": products} if products is not None else {}
        doc = self.ref.organization(id=id or _id(), name=name, region=region, partner_id=partner_id, plan_key=plan, status=status, **extra)
        self.orgs[doc["id"]] = doc
        return doc["id"]

    def add_site(self, org: str, slug: str, name: str = "", id: Optional[str] = None, **over: Any) -> str:
        fields = {"address": "1 Mill Road", "timezone": "America/New_York", "latitude": 35.5, "longitude": -82.5, **over}
        doc = self.ref.site(self.orgs[org], slug, name or slug.title(), id=id or _id(), **fields)
        self.sites[doc["id"]] = doc
        return doc["id"]

    def add_person(self, sub: Optional[str], name: str = "", email: str = "", id: Optional[str] = None, status: str = "active") -> str:
        doc = self.ref.person(sub=sub, email=email or (f"{sub}@example.com" if sub else ""), name=name, id=id or _id(), status=status)
        self.people[doc["id"]] = doc
        return doc["id"]

    def grant(self, person: str, org: str, role: str, sites: Optional[List[str]] = None, source: str = "direct", expires_at: Optional[str] = None,
              others: Optional[List[Dict[str, Any]]] = None) -> None:
        doc = self.ref.access(self.people[person], self.orgs[org], role=role, sites=sites, source=source, expires_at=expires_at, others=others)
        self.access[f"{person}:{org}"] = doc

    def revoke(self, person: str, org: str) -> None:
        self.ref.remove("access", f"{person}:{org}")

    def remove_site(self, site: str) -> None:
        self.ref.remove("site", site)

    def remove_person(self, person: str) -> None:
        self.ref.remove("person", person)

    def unentitle(self, org: str, cascade: bool = True) -> None:
        """The organization stops being entitled to PhotonVox. `cascade=False`: only the organization's removal is sent (we must cope)."""
        if cascade:
            for key, doc in list(self.access.items()):
                if doc["organization_id"] == org:
                    self.ref.remove("access", key)
            for sid, doc in list(self.sites.items()):
                if doc["organization_id"] == org:
                    self.ref.remove("site", sid)
        self.ref.remove("organization", org)

    def compact(self) -> None:
        """Forget the tombstones: a cursor from before them is answered 409 and the client takes a snapshot."""
        self.ref.purge_tombstones()

    # ---- what the directory sends ----

    @property
    def seq(self) -> int:
        return self.ref.seq

    @property
    def requests(self):
        return self.ref.requests

    @property
    def fail_with(self):
        return self.ref.fail_next[0] if self.ref.fail_next else None

    @fail_with.setter
    def fail_with(self, status: Optional[int]) -> None:
        self.ref.fail_next = [status] * 200 if status else []

    def notice(self, now=None, secret=None):
        """A data-free notice, signed: {"content": bytes, "headers": {...}} for posting to /directory/v1/notify."""
        header, body = self.ref.notice(now=now, secrets=[secret] if secret else None)
        return {"content": body, "headers": {"X-PhotonID-Signature": header, "Content-Type": "application/json"}}

    def client(self, projection: Projection, **_ignored: Any):
        return self.ref.client(projection)

    def factory(self):
        """What `get_directory` returns in tests."""
        return lambda projection, timeout_s=None: self.ref.client(projection)
