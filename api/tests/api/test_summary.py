"""GET /v1/summary for the suite's home dashboard (photonid HOME-PLAN.md), against the contract copied from photonid; the account app's token
accepted on this route only; and each organization's address (slug) in /me."""
import json
import pathlib

import jsonschema
import pytest
from sqlalchemy import update

from app.config import settings
from app.db import SystemSession
from app.models import PhoneSystem
from app.routes import summary
from tests.api.conftest import auth, pull, token_for

CONTRACT = pathlib.Path(__file__).resolve().parents[1] / "directory_contract"
SCHEMA = json.loads((CONTRACT / "summary.schema.json").read_text())
ACCOUNT = "https://account.photonind.com"


@pytest.fixture(autouse=True)
def fresh_cache():
    summary._cache.clear()
    yield
    summary._cache.clear()


def make_ps(tenant, status="new"):
    """A phone system for the organization (its engine does not matter here)."""
    import uuid
    with SystemSession() as s:
        s.add(PhoneSystem(tenant_id=uuid.UUID(tenant), instance_id=uuid.uuid4(), domain_name=f"{tenant[:8]}.test", domain_uuid=uuid.uuid4(), status=status))
        s.commit()


def bearer(sub, **claims):
    return {"Authorization": f"Bearer {token_for(sub, **claims)}"}


def valid(body):
    jsonschema.validate(body, SCHEMA)
    return body


def test_the_contract_samples_validate_against_the_schema():
    for name in ("summary.sample.json", "summary-all.sample.json"):
        valid(json.loads((CONTRACT / name).read_text()))


def test_an_organization_without_a_phone_system_is_unknown_and_its_line_is_cached(client, world):
    r = client.get(f"/v1/summary?organization={world.a}", headers=auth("a-user"))
    assert r.status_code == 200 and r.headers["cache-control"] == "private, max-age=30"
    body = valid(r.json())
    assert body["product"] == "vox" and body["organization_id"] == world.a and body["state"] == "unknown" and body["sites"] == []
    assert body["summary"] == "No phone system yet"


def test_a_phone_systems_state_is_the_line_and_the_cache_holds_it_for_30_seconds(client, world, monkeypatch):
    make_ps(world.a)
    with SystemSession() as s:
        ps = s.query(PhoneSystem).one()
        for st, want in (("ready", ("ok", "Phone system up to date (version 3)")), ("changed", ("attention", "Changes made outside")),
                         ("failed", ("attention", "The last change could not")), ("publishing", ("ok", "A change is being published")),
                         ("new", ("unknown", "Being set up"))):
            s.execute(update(PhoneSystem).where(PhoneSystem.id == ps.id).values(status=st, published_version=3))
            s.commit()
            summary._cache.clear()
            body = valid(client.get(f"/v1/summary?organization={world.a}", headers=auth("a-user")).json())
            assert body["state"] == want[0] and body["summary"].startswith(want[1]), (st, body)
        s.execute(update(PhoneSystem).where(PhoneSystem.id == ps.id).values(status="ready"))
        s.commit()
    first = client.get(f"/v1/summary?organization={world.a}", headers=auth("a-user")).json()     # cached as "new"
    assert first["state"] == "unknown"
    monkeypatch.setattr(summary.time, "monotonic", lambda: 10 ** 9)
    assert client.get(f"/v1/summary?organization={world.a}", headers=auth("a-user")).json()["state"] == "ok"


def test_only_people_with_access_or_photon_staff_see_an_organizations_line(client, world):
    assert client.get(f"/v1/summary?organization={world.b}", headers=auth("a-user")).status_code == 403
    assert client.get(f"/v1/summary?organization={world.b}", headers=auth("staff")).status_code == 200
    assert client.get(f"/v1/summary?organization={world.a}").status_code == 401


def test_without_an_organization_one_line_across_every_organization_the_person_reaches(client, world):
    body = valid(client.get("/v1/summary", headers=auth("tech")).json())
    assert body["organization_id"] is None and body["state"] == "unknown" and body["summary"] == "No phone systems yet across 2 organizations"
    make_ps(world.a, "changed")
    with SystemSession() as s:
        s.execute(update(PhoneSystem).values(status="changed"))
        s.commit()
    summary._cache.clear()
    body = valid(client.get("/v1/summary", headers=auth("tech")).json())
    assert body["state"] == "attention" and body["summary"].startswith("1 of 1 phone systems need attention across 2 organizations")
    with SystemSession() as s:
        s.execute(update(PhoneSystem).values(status="ready"))
        s.commit()
    summary._cache.clear()
    assert valid(client.get("/v1/summary", headers=auth("tech")).json())["summary"].startswith("1 phone system up to date across 2 organizations")
    summary._cache.clear()
    assert valid(client.get("/v1/summary", headers=auth("a-user")).json())["summary"].startswith("1 phone system up to date across 1 organization ")
    assert valid(client.get("/v1/summary", headers=auth("stranger")).json())["summary"] == "No organizations in PhotonVox"


def test_the_account_apps_token_is_accepted_on_the_summary_only(client, world, monkeypatch):
    monkeypatch.setattr(settings, "oidc_web_client_id", "vox-web")
    assert client.get("/me", headers=bearer("a-user", client_id="vox-web")).status_code == 200
    r = client.get("/me", headers=bearer("a-user", client_id="account-app"))
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert client.get("/me", headers=bearer("a-user", azp="account-app")).status_code == 401
    assert client.get(f"/v1/summary?organization={world.a}", headers=bearer("a-user", client_id="account-app")).status_code == 200


def test_cors_for_the_dashboard_on_the_summary_only(client, world):
    pre = client.options("/v1/summary", headers={"Origin": ACCOUNT, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
    assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == ACCOUNT and "Authorization" in pre.headers["access-control-allow-headers"]
    r = client.get(f"/v1/summary?organization={world.a}", headers={**auth("a-user"), "Origin": ACCOUNT})
    assert r.headers["access-control-allow-origin"] == ACCOUNT
    other = client.get("/me", headers={**auth("a-user"), "Origin": ACCOUNT})
    assert other.headers.get("access-control-allow-origin") != ACCOUNT
    stranger = client.get(f"/v1/summary?organization={world.a}", headers={**auth("a-user"), "Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in stranger.headers


def test_an_organizations_address_comes_from_the_directory(client, world, fake):
    fake.add_org("Cedar Works", id=world.a, partner_id=world.partner, slug="cedar-works", former_slugs=["cedar"])
    pull(fake)
    t = next(t for t in client.get("/me", headers=auth("a-user")).json()["tenants"] if t["id"] == world.a)
    assert t["slug"] == "cedar-works" and t["former_slugs"] == ["cedar"]
