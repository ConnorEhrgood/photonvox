"""Audit VOX-A-2 and XP-1: an organization the directory suspends is read only; one it archives or removes is served to nobody but Photon staff,
its PhotonEntry tokens stop answering, and the worker publishes nothing queued for either."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db import SystemSession
from app.engine import service
from app.models import IntegrationToken, PhoneSystem, PhoneSystemVersion, Tenant
from tests.api.conftest import auth, pull

A = "/tenants/{}"


def _status(fake, world, status):
    """The directory changes the organization's status (a new sequence number, so the next pull brings it)."""
    doc = {**fake.orgs[world.a], "status": status}
    fake.orgs[world.a] = doc
    fake.ref.put("organization", doc["id"], doc)
    assert pull(fake).ok


def _token(client, world):
    r = client.post(f"/tenants/{world.a}/integrations/entry-tokens", headers=auth("a-admin"), json={"label": "PhotonEntry"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, uuid.UUID(r.json()["id"])


def _staff_in(fake, world):
    fake.grant(world.people["staff"], world.a, "admin")
    assert pull(fake).ok


def test_a_suspended_organization_is_read_only_except_for_photon_staff(client, fake, world):
    _staff_in(fake, world)
    _status(fake, world, "suspended")
    base = A.format(world.a)
    assert client.get(base, headers=auth("a-admin")).json()["status"] == "suspended"
    assert client.get(f"{base}/sites", headers=auth("a-admin")).status_code == 200
    r = client.post(f"{base}/phone-system", headers=auth("a-admin"))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "organization_suspended"
    assert client.post(f"{base}/integrations/entry-tokens", headers=auth("a-admin"), json={}).status_code == 403
    assert client.post(f"{base}/phone-system", headers=auth("staff")).status_code != 403          # staff are not held back
    _status(fake, world, "active")
    assert client.post(f"{base}/integrations/entry-tokens", headers=auth("a-admin"), json={}).status_code == 201


def test_an_archived_organization_is_served_to_nobody_but_staff_and_its_tokens_stop(client, fake, world):
    _staff_in(fake, world)
    headers, _tid = _token(client, world)
    assert client.get("/integrations/entry/v1/door-stations", headers=headers).status_code == 200
    _status(fake, world, "archived")
    base = A.format(world.a)
    for who in ("a-owner", "a-admin", "tech"):
        assert client.get(base, headers=auth(who)).status_code == 404
    assert client.get(base, headers=auth("staff")).json()["status"] == "removed"
    assert client.get("/integrations/entry/v1/door-stations", headers=headers).status_code == 401
    _status(fake, world, "active")                              # back: the people and the token work again (archiving revoked nothing)
    assert client.get(base, headers=auth("a-owner")).status_code == 200
    assert client.get("/integrations/entry/v1/door-stations", headers=headers).status_code == 200


def test_a_removed_organizations_tokens_are_revoked(client, fake, world):
    headers, tid = _token(client, world)
    fake.unentitle(world.a)
    assert pull(fake).ok
    assert client.get("/integrations/entry/v1/door-stations", headers=headers).status_code == 401
    with SystemSession() as s:
        assert s.get(IntegrationToken, tid).revoked_at is not None


def test_the_worker_publishes_nothing_queued_for_an_organization_no_longer_active(client, fake, world):
    with SystemSession() as s:
        ps = PhoneSystem(tenant_id=uuid.UUID(world.a), instance_id=uuid.uuid4(), domain_name="x.sip.test", domain_uuid=uuid.uuid4(), draft={})
        s.add(ps)
        s.flush()
        v = service.queue(s, ps, {"version": 1}, None, "test")
        s.commit()
        vid = v.id
    _status(fake, world, "suspended")

    def never(_instance):
        raise AssertionError("the worker connected to an engine")
    with SystemSession() as s:
        assert service.publish_queued(s, never) == 1
    with SystemSession() as s:
        v = s.get(PhoneSystemVersion, vid)
        assert v.state == "failed" and "suspended" in v.error
        assert s.execute(select(Tenant.status).where(Tenant.id == uuid.UUID(world.a))).scalar_one() == "suspended"
