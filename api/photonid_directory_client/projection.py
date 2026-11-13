"""What a product implements: its read-only local copy of the part of the directory that concerns it.

The directory sends four kinds of thing, each keyed by a string:

  organization   key = organization id.   {id, name, partner_id, home_region, status, plan_key, products}
                 `products`: the keys of ALL the products the organization has switched on (sorted; always includes the product you are, because you are
                 only told about organizations that have you), e.g. ["board", "guard"]. Keys only: no plans, counts or other products' data. Switching any product
                 on or off sends the organization again to every product it still has. `plan_key` is YOUR plan only.
  site           key = site id.           {id, organization_id, slug, name, address, timezone, latitude, longitude, status}
  person         key = person id.         {id, sub, email, name, status, platform_admin, partners}
                 `sub` is the OIDC subject; null until the person has an account.
                 `platform_admin`: Photon platform staff. `partners`: [{partner_id, slug, role: "owner" | "admin" | "staff"}], the person's partner
                 memberships, sorted by partner id, limited to partners with a customer that has you switched on (partner "photon" always listed).
                 Use these instead of a local list of staff: Photon's staff are the platform administrators (`platform_admin`) and the members, in any
                 role, of the partner with slug "photon".
                 They say who someone is, never what they may do in an organization: that is the access rows alone (a staff member who is also a direct
                 owner arrives with `source: "direct"`; read `partners`, not `source`, to tell staff).
                 You are told about a person while they have access with you somewhere, AND about Photon staff while you are switched on for any
                 organization, even with no access row: such a person signs in with no organization (decide what your platform pages give them).
                 Both fields were added on 2026-11-13: treat a document without them (a copy pulled before) as false / [] until the next pull.
  access         key = "<person id>:<organization id>"
                 {person_id, organization_id, role, scope: {"type": "all"} | {"type": "sites", "site_ids": [...]}, source: "direct" | "partner", expires_at,
                  others: [{role, scope, source}, ...]}

Rules for implementers:
  * Do NOT enforce foreign keys between the four kinds. They arrive in the order the changes were made, page by page; an access row can arrive before the
    site it names. The copy is eventually consistent, and always consistent once a pull is complete.
  * A person's role at a site is the STRONGEST role whose scope includes that site, among the row's own (`role`, `scope`) and its `others`. Usually `others`
    is empty. A site-limited admin who is also a whole-organization viewer arrives as role admin / scope sites [A] / others [viewer / all]: admin on A, viewer
    everywhere else. A product that reads only `role` and `scope` under-grants (never over-grants).
  * `expires_at` on an access row is the moment it stops being true. Treat the access as gone after it, even before the directory's next change arrives
    (the directory works out the replacement and sends it within about a minute).
  * Authorization reads this copy only. A directory outage stops only changes to it, never anyone's access.
  * `home_region` is stored with the organization from the first migration, even while every organization is in `us-east`.
  * Every method must be idempotent: the same document may be applied twice.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator

KINDS = ("organization", "site", "person", "access")
Doc = Dict[str, Any]


class Projection(ABC):
    @abstractmethod
    def get_cursor(self) -> int:
        """How far this copy has been brought: 0 for a copy that has never been synced."""

    @abstractmethod
    def set_cursor(self, cursor: int) -> None: ...

    @abstractmethod
    def upsert_organization(self, doc: Doc) -> None: ...

    @abstractmethod
    def upsert_site(self, doc: Doc) -> None: ...

    @abstractmethod
    def upsert_person(self, doc: Doc) -> None: ...

    @abstractmethod
    def upsert_access(self, doc: Doc) -> None: ...

    @abstractmethod
    def remove(self, kind: str, key: str) -> None:
        """Forget this entity. Removing something that is not there is not an error."""

    @abstractmethod
    def known_keys(self, kind: str) -> Iterable[str]:
        """Every key of this kind the copy holds now (used after a snapshot, to drop what the directory no longer has)."""

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Everything applied inside one `with` (a page of changes and the cursor that goes with it) must commit together or not at all.
        The default does nothing: override it with your database transaction."""
        yield
