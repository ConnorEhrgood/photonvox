"""An organization's own routes: what each role sees, site scope, and isolation between organizations for every route."""
import uuid

import pytest

from app.main import app
from tests.api.conftest import auth


def tenant_get_routes():
    """Every GET under an organization, from the OpenAPI schema (FastAPI nests included routers, so app.routes does not list them flat)."""
    return sorted(p for p, ops in app.openapi()["paths"].items() if p.startswith("/tenants/{tenant_id}") and "get" in ops)


def test_there_are_tenant_routes_to_check():
    assert tenant_get_routes() == ["/tenants/{tenant_id}", "/tenants/{tenant_id}/emergency", "/tenants/{tenant_id}/members", "/tenants/{tenant_id}/numbers",
                                   "/tenants/{tenant_id}/phone-system", "/tenants/{tenant_id}/phone-system/templates",
                                   "/tenants/{tenant_id}/phone-system/versions", "/tenants/{tenant_id}/sites"]


@pytest.mark.parametrize("path", tenant_get_routes())
def test_every_tenant_route_is_404_for_another_organization_and_for_strangers(client, world, path):
    for who in ("b-owner", "stranger"):
        r = client.get(path.format(tenant_id=world.a), headers=auth(who))
        assert r.status_code == 404, (who, path)
    assert client.get(path.format(tenant_id=uuid.uuid4()), headers=auth("a-owner")).status_code == 404     # an id that does not exist looks the same


@pytest.mark.parametrize("path", tenant_get_routes())
def test_every_tenant_route_needs_a_token(client, world, path):
    assert client.get(path.format(tenant_id=world.a)).status_code == 401


def test_the_organization_says_your_role_and_what_you_can_do(client, world):
    t = client.get(f"/tenants/{world.a}", headers=auth("a-admin-s1")).json()
    assert t["name"] == "Cedar Works" and t["role"] == "admin" and t["scope"] == {"sites": [world.a1]} and t["source"] == "direct"
    assert "vox.phone.enroll" in t["capabilities"] and "vox.number.release" not in t["capabilities"]
    tech = client.get(f"/tenants/{world.b}", headers=auth("tech")).json()
    assert tech["role"] == "admin" and tech["source"] == "partner"


def test_sites_follow_the_grant_scope(client, world):
    names = lambda who: [s["name"] for s in client.get(f"/tenants/{world.a}/sites", headers=auth(who)).json()]
    assert names("a-owner") == ["Annex", "Main office"]
    assert names("a-admin-s1") == ["Main office"]
    assert names("a-user-s2") == ["Annex"]
    assert names("tech") == ["Annex", "Main office"]


def test_members_are_for_admins_and_show_partner_staff_as_partner_support(client, world):
    assert client.get(f"/tenants/{world.a}/members", headers=auth("a-user")).status_code == 403
    rows = client.get(f"/tenants/{world.a}/members", headers=auth("a-owner")).json()
    assert [m["role"] for m in rows][:1] == ["owner"]                                      # strongest first
    partner = [m for m in rows if m["source"] == "partner"]
    assert [(m["name"], m["email"], m["role"]) for m in partner] == [("Partner support", "", "admin")]
    assert {m["name"] for m in rows} >= {"A Owner", "A Admin", "A User", "A User S2"}


def test_a_site_limited_admin_sees_only_people_who_reach_their_site(client, world):
    names = {m["name"] for m in client.get(f"/tenants/{world.a}/members", headers=auth("a-admin-s1")).json()}
    assert "A User S2" not in names                       # only on the annex
    assert {"A Owner", "A Admin", "A Admin S1", "A User", "Partner support"} <= names


def test_a_person_who_has_not_signed_in_yet_is_pending_and_a_deactivated_one_is_not_listed(client, world, fake):
    p = fake.add_person(None, name="Invited")
    fake.grant(p, world.a, "user")
    gone = world.people["a-user-s2"]
    fake.remove_person(gone)
    from tests.api.conftest import pull
    assert pull(fake).ok
    rows = {m["name"]: m for m in client.get(f"/tenants/{world.a}/members", headers=auth("a-owner")).json()}
    assert rows["Invited"]["pending"] is True and rows["A Owner"]["pending"] is False
    assert "A User S2" not in rows


def test_an_expired_grant_is_404_on_the_organization_even_before_the_directory_says_so(client, world, db):
    from sqlalchemy import text
    db.execute(text("update access set expires_at = now() - interval '1 second' where person_id = :p"), {"p": world.people["a-admin"]})
    db.commit()
    assert client.get(f"/tenants/{world.a}", headers=auth("a-admin")).status_code == 404


def test_who_is_labeled_by_name_then_email_then_id():
    from app.deps import Who
    pid = uuid.uuid4()
    assert Who(pid, "s", "Ann", "ann@example.com", False).label == "Ann"
    assert Who(pid, "s", "", "ann@example.com", False).label == "ann@example.com"
    assert Who(pid, "s", "", "", False).label == str(pid)
