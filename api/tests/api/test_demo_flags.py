"""The demo organization (docs/DEMO.md): the directory's `demo` flag is kept on the tenant (a document without it is not a demo); a demo is placed
on a simulated engine and nobody else is; the publisher refuses a demo on a live engine and a customer on a simulated one before it connects to
anything; the demo is left out of the summary's count across organizations."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db import SystemSession
from app.engine import service
from app.models import PbxInstance, PhoneSystem, PhoneSystemVersion, Tenant
from tests.api.conftest import auth, pull

INSTANCE = {"hostname": "vox-x", "database_url": "postgresql+psycopg://adapter:x@engine/fusionpbx", "agent_url": "http://10.2.1.21:8780",
            "agent_secret": "a" * 64, "upstreams": [{"key": "htc", "proxy": "198.51.100.5", "addresses": ["198.51.100.0/28"]}],
            "routing": {"national": ["htc"]}, "emergency_upstream": "htc"}


def _demo(fake, world, on=True):
    doc = dict(fake.orgs[world.a])
    doc["demo"] = on
    fake.orgs[world.a] = doc
    assert pull(fake).ok


def _tenant(world):
    with SystemSession() as s:
        return s.get(Tenant, uuid.UUID(world.a))


def test_the_directorys_flag_is_kept_and_a_document_without_it_is_not_a_demo(client, fake, world):
    assert _tenant(world).demo is False
    _demo(fake, world)
    assert _tenant(world).demo is True
    doc = dict(fake.orgs[world.a])
    doc.pop("demo")
    fake.orgs[world.a] = doc
    assert pull(fake).ok and _tenant(world).demo is False


def test_a_demo_goes_on_a_simulated_engine_and_nobody_else_does(client, fake, world):
    live = client.post("/platform/instances", headers=auth("staff"), json={"name": "colo-a", **INSTANCE})
    assert live.status_code == 201 and live.json()["simulated"] is False
    _demo(fake, world)
    r = client.post(f"/tenants/{world.a}/phone-system", headers=auth("tech"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_instance"          # only a live engine exists: the demo is not placed on it
    sim = client.post("/platform/instances", headers=auth("staff"), json={"name": "demo-sim", "simulated": True, **INSTANCE})
    assert sim.status_code == 201 and sim.json()["simulated"] is True
    assert client.post(f"/tenants/{world.a}/phone-system", headers=auth("tech")).status_code == 201
    assert client.post(f"/tenants/{world.b}/phone-system", headers=auth("tech")).status_code == 201
    with SystemSession() as s:
        placed = {str(p.tenant_id): s.get(PbxInstance, p.instance_id).name for p in s.execute(select(PhoneSystem)).scalars()}
    assert placed == {world.a: "demo-sim", world.b: "colo-a"}


def test_the_publisher_refuses_a_mismatch_before_connecting_to_anything(client, fake, world):
    client.post("/platform/instances", headers=auth("staff"), json={"name": "colo-a", **INSTANCE})
    assert client.post(f"/tenants/{world.a}/phone-system", headers=auth("tech")).status_code == 201
    _demo(fake, world)                                    # marked a demo after it was placed on the live engine
    with SystemSession() as s:
        ps = s.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == uuid.UUID(world.a))).scalar_one()
        v = service.queue(s, ps, {"version": 1}, None, "test")
        s.commit()
        vid = v.id

    def never(_instance):
        raise AssertionError("the publisher connected to an engine")
    with SystemSession() as s:
        assert service.publish_version(s, vid, never) == "failed"
        v = s.get(PhoneSystemVersion, vid)
        assert "only to a simulated engine" in v.error


def test_the_demo_is_not_counted_across_organizations(client, fake, world):
    before = client.get("/v1/summary", headers=auth("tech")).json()["summary"]
    assert "across 2 organizations" in before
    _demo(fake, world)
    from app.routes import summary
    summary._cache.clear()
    assert "across 1 organization" in client.get("/v1/summary", headers=auth("tech")).json()["summary"]
    assert client.get(f"/v1/summary?organization={world.a}", headers=auth("tech")).status_code == 200      # its own line still answers
