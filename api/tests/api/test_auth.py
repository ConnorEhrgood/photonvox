"""Signing in: tokens, first sign-in through the directory, and what /me says."""
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import text

from app import deps
from app.config import settings
from app.main import app
from tests.api.conftest import auth, pull, token_for


def test_no_token_or_a_bad_token_is_401(client, world):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Basic abc"}).status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    expired = token_for("a-owner", exp=datetime.now(timezone.utc) - timedelta(minutes=1))
    assert client.get("/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    wrong_aud = token_for("a-owner", aud="someone-else")
    assert client.get("/me", headers={"Authorization": f"Bearer {wrong_aud}"}).status_code == 401
    unsigned = jwt.encode({"sub": "a-owner", "iss": settings.oidc_issuer, "aud": settings.oidc_audience, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}, None, algorithm="none")
    assert client.get("/me", headers={"Authorization": f"Bearer {unsigned}"}).status_code == 401      # a token cannot pick its own algorithm


def test_the_sign_in_contract_answers_are_json_and_never_redirects(client, world):
    """The suite's sign-in contract (photonid docs/SIGNIN-BRIEFS.md, item 7): a request without a usable token is a 401 JSON answer with
    `WWW-Authenticate: Bearer` and no `Location`; a refused one is a 403 JSON answer with a `code`. The web app decides what to show."""
    for headers in ({}, {"Authorization": "Bearer garbage"}):
        r = client.get("/me", headers=headers, follow_redirects=False)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer" and "location" not in r.headers
        assert r.headers["content-type"].startswith("application/json") and r.json()["detail"]
    r = client.get("/me", headers=auth("nobody-at-all"), follow_redirects=False)
    assert r.status_code == 403 and "location" not in r.headers and r.json()["detail"]["code"] == "no_access"


def test_me_lists_each_organization_with_role_scope_and_capabilities(client, world):
    r = client.get("/me", headers=auth("a-admin-s1"))
    assert r.status_code == 200
    me = r.json()
    assert me["name"] == "A Admin S1" and me["is_platform_admin"] is False
    [t] = me["tenants"]
    assert t["id"] == world.a and t["name"] == "Cedar Works" and t["role"] == "admin" and t["scope"] == {"sites": [world.a1]}
    assert t["source"] == "direct" and t["expires_at"] is None
    assert "vox.phone.enroll" in t["capabilities"] and "vox.audit.view" not in t["capabilities"]
    assert "home_region" not in t and t["partner_id"] == world.partner


def test_someone_in_two_organizations_sees_both_and_a_stranger_none(client, world, fake):
    fake.grant(world.people["a-user"], world.b, "user", source="partner", expires_at="2099-01-01T00:00:00Z")
    pull(fake)
    tenants = client.get("/me", headers=auth("a-user")).json()["tenants"]
    assert [(t["name"], t["role"], t["source"]) for t in tenants] == [("Birch Co", "user", "partner"), ("Cedar Works", "user", "direct")]
    assert client.get("/me", headers=auth("stranger")).json()["tenants"] == []


def test_an_expired_grant_is_not_listed(client, world, db):
    db.execute(text("update access set expires_at = now() - interval '1 second' where person_id = :p"), {"p": world.people["a-user"]})
    db.commit()
    assert client.get("/me", headers=auth("a-user")).json()["tenants"] == []


def test_a_person_the_database_has_not_got_is_asked_about_once(client, world, fake):
    """The directory invited them a moment ago and its notice has not reached us: the first request resolves them."""
    p = fake.add_person("fresh", "Fresh Face")
    fake.grant(p, world.a, "user", [world.a1])
    before = len(fake.requests)
    r = client.get("/me", headers=auth("fresh"))
    assert r.status_code == 200 and [t["role"] for t in r.json()["tenants"]] == ["user"]
    assert [f"{m} {p}" for m, p, _ in fake.requests[before:]] == ["GET /v1/resolve", "GET /v1/sync"]      # asked once, then a pull brings the copy up to date
    n = len(fake.requests)
    client.get("/me", headers=auth("fresh"))
    assert len(fake.requests) == n                                                                      # now known: no more asking


def test_a_sub_the_directory_does_not_know_is_refused(client, world):
    r = client.get("/me", headers=auth("nobody-at-all"))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "no_access"


def test_a_directory_that_is_down_means_access_is_being_set_up_not_a_crash(client, world, fake):
    fake.down = True
    r = client.get("/me", headers=auth("not-yet-known"))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "access_pending" and r.headers["Retry-After"] == "30"
    assert client.get("/me", headers=auth("a-owner")).status_code == 200      # people we already know never wait for the directory


def test_with_no_directory_configured_an_unknown_person_is_pending(client, world):
    app.dependency_overrides[deps.get_directory] = lambda: None
    r = client.get("/me", headers=auth("not-yet-known"))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "access_pending"


def test_asking_for_an_unknown_person_is_rate_limited(client, world, fake):
    for _ in range(6):
        assert client.get("/me", headers=auth("ghost")).status_code == 403
    n = len(fake.requests)
    r = client.get("/me", headers=auth("ghost"))
    assert r.status_code == 503 and len(fake.requests) == n                 # the seventh did not reach the directory


def test_a_deactivated_person_is_refused(client, world, fake):
    fake.remove_person(world.people["a-user"])
    pull(fake)
    r = client.get("/me", headers=auth("a-user"))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "no_access"


def test_the_platform_routes_are_for_platform_staff_only(client, world):
    assert client.get("/platform/organizations", headers=auth("a-owner")).status_code == 403
    assert client.get("/platform/directory", headers=auth("a-owner")).status_code == 403
    r = client.get("/platform/organizations", headers=auth("staff"))
    assert r.status_code == 200 and [o["name"] for o in r.json()] == ["Birch Co", "Cedar Works"]
    d = client.get("/platform/directory", headers=auth("staff")).json()
    assert d["cursor"] > 0 and d["last_error"] is None and d["last_ok_at"]


def test_platform_directory_status_before_any_pull(client, fake):
    fake.add_person("staff")           # known only through resolve, which brings the copy up to date with a pull
    r = client.get("/platform/directory", headers=auth("staff"))
    assert r.status_code == 200 and r.json()["cursor"] == fake.seq and r.json()["last_error"] is None


def test_the_directory_client_factory_is_there_only_when_a_directory_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "directory_url", "")
    assert deps.get_directory() is None
    monkeypatch.setattr(settings, "directory_url", "https://api.account.example/")
    monkeypatch.setattr(settings, "directory_client_id", "pdc_vox")
    monkeypatch.setattr(settings, "directory_client_secret", "s3cret")
    make = deps.get_directory()
    from photonid_directory_client.testing import MemoryProjection
    c = make(MemoryProjection(), timeout_s=2.0)
    assert c.base_url == "https://api.account.example/" and c.credential == "pdc_vox.s3cret" and c.timeout_s == 2.0
    assert make(MemoryProjection()).timeout_s == settings.directory_timeout_s


def test_the_default_verifier_is_the_oidc_one(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(deps, "default_verifier", lambda: sentinel)
    assert deps.get_verifier() is sentinel


def test_me_skips_a_grant_that_has_lapsed_by_our_clock_even_if_the_database_clock_has_not_caught_up(client, world, monkeypatch):
    from app.routes import me
    monkeypatch.setattr(me, "utcnow", lambda: datetime.now(timezone.utc) + timedelta(days=3650))     # nothing has an expiry here, so use access that does
    assert client.get("/me", headers=auth("a-user")).json()["tenants"][0]["role"] == "user"           # no expiry: still there
    from app.db import SystemSession
    with SystemSession() as s:
        s.execute(text("update access set expires_at = now() + interval '1 hour' where person_id = :p"), {"p": world.people["a-user"]})
        s.commit()
    assert client.get("/me", headers=auth("a-user")).json()["tenants"] == []                                # the database still shows it; our clock says lapsed


def test_the_directory_status_before_the_first_pull_is_empty_not_an_error(client, world, db):
    from app.db import owner_engine
    with owner_engine.begin() as c:
        c.execute(text("delete from sync_state"))
    assert client.get("/platform/directory", headers=auth("staff")).json() == {"cursor": 0, "last_pull_at": None, "last_ok_at": None, "last_error": None}


def test_an_organizations_other_products_are_kept_and_shown_to_platform_staff(client, fake, world):
    """The directory's `products` list is stored as sent (sorted, with our own key), and follows a change."""
    oid = fake.add_org("Elm Co", products=["edge", "board"])
    assert pull(fake).ok
    rows = {o["name"]: o for o in client.get("/platform/organizations", headers=auth("staff")).json()}
    assert rows["Elm Co"]["products"] == ["board", "edge", "vox"] and rows["Cedar Works"]["products"] == ["vox"]
    fake.orgs[oid] = fake.ref.organization(id=oid, name="Elm Co", products=["board"])
    assert pull(fake).ok
    rows = {o["name"]: o for o in client.get("/platform/organizations", headers=auth("staff")).json()}
    assert rows["Elm Co"]["products"] == ["board", "vox"]


def test_a_partner_technician_sees_every_customer_of_the_partner_as_partner_admin(client, world):
    tenants = client.get("/me", headers=auth("tech")).json()["tenants"]
    assert [(t["name"], t["role"], t["source"]) for t in tenants] == [("Birch Co", "admin", "partner"), ("Cedar Works", "admin", "partner")]


def test_a_removed_organization_is_not_listed(client, world, fake):
    fake.unentitle(world.b, cascade=False)                    # only the organization's removal arrives; its access rows are dropped with it
    assert pull(fake).ok
    assert [t["name"] for t in client.get("/me", headers=auth("tech")).json()["tenants"]] == ["Cedar Works"]


def test_health_and_readiness(client):
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/readyz").json() == {"ok": True}
