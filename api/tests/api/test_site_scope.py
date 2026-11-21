"""Audit 2026-11-17 §3.1: a capability asked with no site must not let a person limited to some sites act on the whole organization. Every
route that checks a capability is walked with a mixed grant (admin of one site, user of the whole organization): an organization-wide route
refuses them, and a route that keeps to sites itself must say how here. A new route fails this test until it is one or the other."""
from __future__ import annotations

import uuid

from fastapi.routing import APIRoute

from app.deps import REQUIRED
from app.main import app
from tests.api.conftest import auth, pull

T = "/tenants/{tenant_id}"
# Routes that let a site-limited person in, and how each keeps to their sites.
SITE_AWARE = {
    ("GET", T + "/phone-system"): "the document, read whole (the builder needs it); every change is checked per site",
    ("PUT", T + "/phone-system/draft"): "policy.refusal with the sites where the person may build",
    ("POST", T + "/phone-system/publish"): "refused unless the version changes only their sites against the live one",
    ("GET", T + "/phone-system/versions"): "the version list (numbers, states, check counts)",
    ("POST", T + "/phone-system/versions/{number}/restore"): "policy.refusal, then the same live comparison as publishing",
    ("GET", T + "/phone-system/templates"): "the template catalog (no organization data)",
    ("POST", T + "/phone-system/draft/template"): "a site where they may build, then policy.refusal",
    ("POST", T + "/phone-system/draft/clone"): "policy.refusal",
    ("POST", T + "/phone-system/import"): "a site where they may build, then policy.refusal",
    ("POST", T + "/sites/{site_id}/emergency-locations"): "the capability at the named site",
    ("GET", T + "/emergency"): "only the sites where they may view",
    ("GET", T + "/numbers"): "the organization's assigned numbers (needed to give one to their site)",
    ("GET", T + "/members"): "only people who share a site where they may see members",
    ("GET", T + "/dashboard"): "only the sites where they may view",
}


def _routes(routes):
    """Every API route of the app, also those inside included routers (FastAPI keeps those as their own router)."""
    for r in routes:
        if isinstance(r, APIRoute):
            yield r
        elif getattr(r, "original_router", None) is not None:
            yield from _routes(r.original_router.routes)


def _deps(dependant):
    for d in dependant.dependencies:
        yield d
        yield from _deps(d)


def _mixed(fake, world, sub="a-mixed"):
    pid = fake.add_person(sub, name="Mixed")
    fake.grant(pid, world.a, "admin", [world.a1], others=[{"role": "user", "scope": {"type": "all"}, "source": "direct"}])
    assert pull(fake).ok


def test_every_route_is_organization_wide_or_says_how_it_keeps_to_sites(client, fake, world):
    _mixed(fake, world)
    walked, org_wide = set(), 0
    for route in _routes(app.routes):
        asks = {REQUIRED[d.call] for d in _deps(route.dependant) if d.call in REQUIRED}
        if not asks:
            continue
        assert len(asks) == 1, route.path
        _capability, sites = asks.pop()
        for method in route.methods:
            key = (method, route.path)
            walked.add(key)
            if sites:
                assert key in SITE_AWARE, f"{key} lets site-limited people in: say how it keeps to their sites in SITE_AWARE"
                continue
            assert key not in SITE_AWARE, f"{key} is organization-wide now: take it out of SITE_AWARE"
            path = route.path.format(tenant_id=world.a, site_id=world.a1, token_id=uuid.uuid4(), number=1)
            for sub in ("a-mixed", "a-admin-s1"):
                assert client.request(method, path, headers=auth(sub)).status_code == 403, (sub, key)
            assert client.request(method, path, headers=auth("a-admin")).status_code != 403, key     # the whole organization's admin passes
            org_wide += 1
    assert set(SITE_AWARE) <= walked, set(SITE_AWARE) - walked
    assert org_wide >= 4          # creating the phone system and the PhotonEntry tokens at least


def test_a_mixed_grant_sees_and_builds_only_where_its_site_limited_role_reaches(client, fake, world):
    """A site-limited admin who is a whole-organization user: their reach is every site, but they may see the phone system's sites and members
    only where they are admin."""
    _mixed(fake, world)
    sites = {s["id"] for s in client.get(f"/tenants/{world.a}/sites", headers=auth("a-mixed")).json()}
    assert sites == {world.a1, world.a2}                       # they reach every site (as a user) ...
    members = {m["name"] for m in client.get(f"/tenants/{world.a}/members", headers=auth("a-mixed")).json()}
    assert "A User S2" not in members and "A Admin S1" in members     # ... but see members only where they may (a1)
