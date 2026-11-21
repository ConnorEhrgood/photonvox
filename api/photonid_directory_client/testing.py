"""For a product's own tests: an in-memory Projection and a fake directory (an in-memory server for httpx) that behaves like the real one.

    directory = FakeDirectory()
    org = directory.organization(name="Acme", region="eu-west")          # organizations may sit in different regions
    directory.person(sub="ann", email="ann@example.com")
    directory.access(person, org, role="admin")
    projection = MemoryProjection()
    client = directory.client(projection)
    client.sync_once()
    header, body = directory.notice()                                     # a signed notice, as the real directory sends it
    client.handle_notice(header, body)

The fake keeps the real directory's rules: one row per entity numbered in the order changes were made, removals kept as tombstones until purged,
`cursor=0` is a snapshot, a cursor it cannot continue from is answered 409 `{"reset": true}`."""
from __future__ import annotations

import copy
import json
import re
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

import httpx

from .client import DirectoryClient
from .notice import sign_notice
from .projection import KINDS, Doc, Projection


def _slugify(name: str) -> str:
    """As the directory makes an organization's slug from its name (a-z 0-9 and hyphens)."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:63].strip("-") or "org"

BASE = "http://directory.test"


class MemoryProjection(Projection):
    def __init__(self) -> None:
        self.data: Dict[str, Dict[str, Doc]] = {k: {} for k in KINDS}
        self.cursor = 0
        self.transactions = 0

    def get_cursor(self) -> int:
        return self.cursor

    def set_cursor(self, cursor: int) -> None:
        self.cursor = cursor

    def upsert_organization(self, doc: Doc) -> None:
        self.data["organization"][doc["id"]] = copy.deepcopy(doc)

    def upsert_site(self, doc: Doc) -> None:
        self.data["site"][doc["id"]] = copy.deepcopy(doc)

    def upsert_person(self, doc: Doc) -> None:
        self.data["person"][doc["id"]] = copy.deepcopy(doc)

    def upsert_access(self, doc: Doc) -> None:
        self.data["access"][f"{doc['person_id']}:{doc['organization_id']}"] = copy.deepcopy(doc)

    def remove(self, kind: str, key: str) -> None:
        self.data[kind].pop(key, None)

    def known_keys(self, kind: str) -> Iterable[str]:
        return list(self.data[kind])

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """All or nothing: an exception inside puts everything back, as a database transaction would."""
        before = (copy.deepcopy(self.data), self.cursor)
        try:
            yield
            self.transactions += 1
        except BaseException:
            self.data, self.cursor = before
            raise


class FakeDirectory:
    def __init__(self, product: str = "guard", credential: str = "pdc_fake0000000000.fakesecret", notice_secret: str = "pdn_fake") -> None:
        self.product, self.credential, self.notice_secret = product, credential, notice_secret
        self.rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.seq = 0
        self.floor = 0
        self.requests: List[Tuple[str, str, Dict[str, str]]] = []
        self.fail_next: List[int] = []           # statuses to answer instead of the real answer, one per request
        self.published: Optional[List[Doc]] = None

    # -- the directory's state ------------------------------------------------------------------------------------------------------------------

    def put(self, kind: str, key: str, data: Doc) -> None:
        self.seq += 1
        self.rows[(kind, key)] = {"seq": self.seq, "present": True, "data": copy.deepcopy(data)}

    def remove(self, kind: str, key: str) -> None:
        if (kind, key) in self.rows:
            self.seq += 1
            self.rows[(kind, key)] = {"seq": self.seq, "present": False, "data": None}

    def purge_tombstones(self) -> None:
        gone = [k for k, v in self.rows.items() if not v["present"]]
        if gone:
            self.floor = max(self.floor, max(self.rows[k]["seq"] for k in gone))
            for k in gone:
                del self.rows[k]

    def restore_to(self, seq: int) -> None:
        """As if the directory had been restored from a backup taken at `seq`: everything after it is forgotten."""
        self.rows = {k: v for k, v in self.rows.items() if v["seq"] <= seq}
        self.seq = seq

    def organization(self, id: Optional[str] = None, name: str = "Organization", region: str = "us-east", partner_id: Optional[str] = None, plan_key: str = "standard",
                     status: str = "active", products: Optional[List[str]] = None, slug: Optional[str] = None, former_slugs: Optional[List[str]] = None,
                     demo: bool = False) -> Doc:
        """`products`: the other products the organization has switched on; this product's own key is always in the list, which is sorted (as the directory sends it).
        `slug`: its address in every product (/org/<slug>/; default: from the name); `former_slugs`: the ones it had, which redirect.
        `demo`: Photon's demo organization (left out of billing, usage counts and platform alerts)."""
        doc = {"id": id or str(uuid.uuid4()), "name": name, "slug": slug or _slugify(name), "former_slugs": sorted(former_slugs or []),
               "partner_id": partner_id or str(uuid.uuid4()), "home_region": region, "status": status, "plan_key": plan_key,
               "products": sorted({self.product, *(products or [])}), "demo": demo}
        self.put("organization", doc["id"], doc)
        return doc

    def site(self, org: Doc, slug: str, name: str = "", id: Optional[str] = None, **fields: Any) -> Doc:
        doc = {"id": id or str(uuid.uuid4()), "organization_id": org["id"], "slug": slug, "name": name or slug, "address": "", "timezone": "UTC", "latitude": None,
               "longitude": None, "status": "active", **fields}
        self.put("site", doc["id"], doc)
        return doc

    def person(self, sub: Optional[str] = None, email: str = "", name: str = "", id: Optional[str] = None, status: str = "active", platform_admin: bool = False,
               partners: Optional[List[Doc]] = None) -> Doc:
        """`platform_admin`: Photon platform staff. `partners`: [{"partner_id", "slug", "role"}] memberships (sorted by partner id, as the directory sends
        them; role "owner", "admin" or "staff"; Photon's own staff are members of the partner with slug "photon").
        The directory tells a product about platform staff even when they hold no access in it: call this without `access` to model that."""
        doc = {"id": id or str(uuid.uuid4()), "sub": sub, "email": email, "name": name, "status": status, "platform_admin": platform_admin,
               "partners": sorted((dict(p) for p in partners or []), key=lambda p: p["partner_id"])}
        self.put("person", doc["id"], doc)
        return doc

    def access(self, person: Doc, org: Doc, role: str = "viewer", sites: Optional[List[str]] = None, source: str = "direct", expires_at: Optional[str] = None,
               others: Optional[List[Doc]] = None) -> Doc:
        """`others`: lower-ranked {role, scope, source} entries covering the rest (a site-limited admin who is also a whole-organization viewer)."""
        doc = {"person_id": person["id"], "organization_id": org["id"], "role": role, "scope": {"type": "all"} if sites is None else {"type": "sites", "site_ids": sorted(sites)},
               "source": source, "expires_at": expires_at, "others": others or []}
        self.put("access", f"{person['id']}:{org['id']}", doc)
        return doc

    def state(self) -> Dict[str, Dict[str, Doc]]:
        """What a perfectly synced copy would hold: present entities by kind and key."""
        out: Dict[str, Dict[str, Doc]] = {k: {} for k in KINDS}
        for (kind, key), v in self.rows.items():
            if v["present"]:
                out[kind][key] = v["data"]
        return out

    # -- the wire ---------------------------------------------------------------------------------------------------------------------------------

    def notice(self, seq: Optional[int] = None, now: Optional[int] = None, secrets: Optional[List[str]] = None) -> Tuple[str, bytes]:
        body = json.dumps({"product": self.product, "event": "changed", "seq": self.seq if seq is None else seq}, separators=(",", ":"), sort_keys=True).encode()
        return sign_notice(secrets or [self.notice_secret], body, now), body

    def client(self, projection: Projection, **kw: Any) -> DirectoryClient:
        http = httpx.Client(transport=httpx.MockTransport(self.handle), base_url=BASE)
        return DirectoryClient(BASE, self.credential, projection, notice_secrets=[self.notice_secret], http=http, **kw)

    def handle(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append((request.method, request.url.path, params))
        if self.fail_next:
            return httpx.Response(self.fail_next.pop(0), json={"detail": "injected failure"})
        if request.headers.get("authorization") != f"Bearer {self.credential}":
            return httpx.Response(401, json={"detail": "Invalid credential"})
        if request.method == "GET" and request.url.path == "/v1/sync":
            return self._sync(int(params.get("cursor", "0")), int(params.get("limit", "500")), params.get("snapshot") == "true")
        if request.method == "GET" and request.url.path == "/v1/resolve":
            return self._resolve(params.get("sub", ""))
        if request.method == "PUT" and request.url.path == f"/v1/products/{self.product}/roles":
            self.published = json.loads(request.content)["roles"]
            return httpx.Response(200, json={"roles": len(self.published), "retired": [], "retired_still_granted": {}})
        return httpx.Response(404, json={"detail": "Not found"})

    def _sync(self, cursor: int, limit: int, snapshot: bool = False) -> httpx.Response:
        limit = max(1, min(limit, 1000))
        if cursor < 0 or cursor > self.seq or (0 < cursor < self.floor and not snapshot):
            return httpx.Response(409, json={"reset": True, "detail": "Start again from a snapshot (cursor=0)"})
        rows = sorted(((v["seq"], k, v) for k, v in self.rows.items() if v["seq"] > cursor), key=lambda t: t[0])
        has_more = len(rows) > limit
        rows = rows[:limit]
        changes = [{"seq": seq, "kind": k[0], "key": k[1], "op": "upsert", "data": v["data"]} if v["present"] else {"seq": seq, "kind": k[0], "key": k[1], "op": "remove"}
                   for seq, k, v in rows if not (cursor == 0 and not v["present"])]
        return httpx.Response(200, json={"snapshot": cursor == 0 or snapshot, "cursor": rows[-1][0] if rows else cursor, "has_more": has_more, "changes": changes})

    def _resolve(self, sub: str) -> httpx.Response:
        people = [v["data"] for (kind, _k), v in self.rows.items() if kind == "person" and v["present"] and v["data"]["sub"] == sub]
        if not people:
            return httpx.Response(404, json={"detail": "Unknown"})
        person = people[0]
        access = [v["data"] for (kind, _k), v in self.rows.items() if kind == "access" and v["present"] and v["data"]["person_id"] == person["id"]]
        orgs = {a["organization_id"] for a in access}
        return httpx.Response(200, json={
            "as_of": self.seq, "person": person, "access": access,
            "organizations": [v["data"] for (kind, k), v in self.rows.items() if kind == "organization" and v["present"] and k in orgs],
            "sites": [v["data"] for (kind, _k), v in self.rows.items() if kind == "site" and v["present"] and v["data"]["organization_id"] in orgs]})
