"""The demo's phone system by the operator's commands (app/manage.py, docs/DEMO.md): `demo seed` makes it on a simulated engine and publishes
it, and run again puts it back as written; `demo remove` takes it off the engine and out of PhotonVox. Neither ever touches a customer or a
live engine, and a demo never gets a 911 registration or a carrier request."""
from __future__ import annotations

import io
import json
import uuid

import pytest
from sqlalchemy import select, text

from app import demo, manage
from app.db import SystemSession
from app.models import (AuditLog, CarrierRequest, EmergencyLocation, EmergencyNumber, EngineObject, HeldNumber, PbxInstance, PhoneSystem,
                        PhoneSystemVersion, Site, Tenant)
from tests.api import fpbx
from tests.api.test_phone_system import FakeAgent

GATEWAY = "895b6ff4-fbff-5b3d-9cc1-395d72a86307"
URL = "postgresql+psycopg://adapter:x@engine/fusionpbx\n"
ORG = uuid.UUID(demo.ORG)


@pytest.fixture()
def eng():
    e = fpbx.create()
    yield e
    fpbx.drop(e)


@pytest.fixture()
def run(eng):
    agent = FakeAgent(eng)

    def run_(*a, stdin=""):
        o = io.StringIO()
        rc = manage.main(list(a), io.StringIO(stdin), o, lambda instance: (eng, agent))
        return rc, json.loads(o.getvalue())
    return run_


def _count(eng, table="v_extensions"):
    with eng.connect() as c:
        return c.execute(text(f"select count(*) from {table}")).scalar()


def _rows(model, **where):
    with SystemSession() as s:
        return list(s.execute(select(model).filter_by(**where)).scalars())


def test_an_instance_is_simulated_only_when_the_operator_says_so(run):
    assert run("add-instance", "live-a", "fusionpbx", f"htc={GATEWAY}", stdin=URL)[1]["simulated"] is False
    assert run("add-instance", "demo-sim", "vox-staging", f"sipp-upstream={GATEWAY}", "simulated", stdin=URL)[1]["simulated"] is True
    with pytest.raises(SystemExit, match="simulated"):
        run("add-instance", "other", "vox-staging", f"sipp-upstream={GATEWAY}", "simulate", stdin=URL)
    assert {i.name: i.simulated for i in _rows(PbxInstance)} == {"live-a": False, "demo-sim": True}


def test_the_seed_makes_the_demo_and_publishes_it(run, eng):
    run("add-instance", "demo-sim", "vox-staging", f"sipp-upstream={GATEWAY}", "simulated", stdin=URL)
    rc, out = run("demo", "seed", "demo-sim")
    assert rc == 0 and out["state"] == "ready" and not out["error"] and out["version"] == 1
    assert out["domain"] == demo.DOMAIN and out["checks"] > 0 and out["checks_failed"] == []
    doc = demo.document()
    assert _count(eng) == len(doc["users"]) and _count(eng, "v_destinations") == len(doc["numbers"])
    tenant, = _rows(Tenant)
    assert tenant.id == ORG and tenant.demo and tenant.slug == "demo"
    assert {str(s.id): s.slug for s in _rows(Site)} == {k: v[0] for k, v in demo.SITES.items()}
    assert {h.number for h in _rows(HeldNumber, tenant_id=ORG)} == set(doc["numbers"])
    assert {str(e.site_id): e.status for e in _rows(EmergencyLocation)} == {s: "validated" for s in demo.PHONE_SITES}
    ps, = _rows(PhoneSystem)
    assert ps.domain_name == demo.DOMAIN and ps.published_version == 1 and ps.status == "ready"
    # Fictional numbers: never registered for 911, never sent to a carrier.
    assert _rows(EmergencyNumber) == [] and _rows(CarrierRequest) == []
    assert [a.action for a in _rows(AuditLog, actor_label=manage.OPERATOR)][:2] == ["instance.added", "phone_system.publish_requested"]


def test_seeded_again_it_is_as_written_again(run, eng):
    run("add-instance", "demo-sim", "vox-staging", f"sipp-upstream={GATEWAY}", "simulated", stdin=URL)
    run("demo", "seed", "demo-sim")
    before = _count(eng)
    with SystemSession() as s:
        ps = s.execute(select(PhoneSystem)).scalar_one()
        draft = json.loads(json.dumps(ps.draft))
        gone = sorted(draft["users"])[0]
        draft["users"].pop(gone)                        # a visitor's edit, left in the draft
        ps.draft = draft
        s.commit()
        ids = (ps.id, ps.domain_uuid)
    rc, out = run("demo", "seed", "demo-sim")
    assert out["state"] == "ready" and out["version"] == 2 and _count(eng) == before
    ps, = _rows(PhoneSystem)
    assert ps.draft == demo.document() and (ps.id, ps.domain_uuid) == ids and ps.published_version == 2
    assert len(_rows(HeldNumber)) == len(demo.document()["numbers"]) and len(_rows(EmergencyLocation)) == len(demo.PHONE_SITES)


def test_the_seed_goes_nowhere_but_a_simulated_engine_and_a_demo(run, eng):
    run("add-instance", "live-a", "fusionpbx", f"htc={GATEWAY}", stdin=URL)
    for name in ("live-a", "nowhere"):
        with pytest.raises(SystemExit, match="simulated instance"):
            run("demo", "seed", name)
    run("add-instance", "demo-sim", "vox-staging", f"sipp-upstream={GATEWAY}", "simulated", stdin=URL)
    with SystemSession() as s:
        s.add(Tenant(id=ORG, name="A customer", slug="customer", status="active", products=["vox"]))
        s.commit()
    with pytest.raises(SystemExit, match="does not mark"):
        run("demo", "seed", "demo-sim")
    with SystemSession() as s:
        s.get(Tenant, ORG).demo = True
        other = uuid.uuid4()
        s.add(Tenant(id=other, name="Someone else", slug="else", status="active", products=["vox"]))
        s.add(HeldNumber(number=sorted(demo.document()["numbers"])[0], tenant_id=other))
        s.commit()
    with pytest.raises(SystemExit, match="held for someone else"):
        run("demo", "seed", "demo-sim")
    assert _rows(PhoneSystem) == [] and _count(eng) == 0


def test_the_seed_refuses_a_demo_that_is_somewhere_else_or_busy(run, eng):
    run("add-instance", "demo-sim", "vox-staging", f"sipp-upstream={GATEWAY}", "simulated", stdin=URL)
    run("add-instance", "demo-sim-2", "vox-staging-2", f"sipp-upstream={GATEWAY}", "simulated", stdin=URL)
    run("demo", "seed", "demo-sim")
    with pytest.raises(SystemExit, match="elsewhere"):
        run("demo", "seed", "demo-sim-2")
    with SystemSession() as s:
        v = s.execute(select(PhoneSystemVersion)).scalar_one()
        v.state = "publishing"
        s.commit()
    for cmd in (("demo", "seed", "demo-sim"), ("demo", "remove")):
        with pytest.raises(SystemExit, match="still publishing"):
            run(*cmd)


def test_remove_takes_it_off_the_engine_and_out_of_photonvox(run, eng):
    run("add-instance", "demo-sim", "vox-staging", f"sipp-upstream={GATEWAY}", "simulated", stdin=URL)
    with pytest.raises(SystemExit, match="no phone system"):
        run("demo", "remove")
    run("demo", "seed", "demo-sim")
    written = len(_rows(EngineObject))
    assert written and _count(eng) > 0
    rc, out = run("demo", "remove")
    assert rc == 0 and out["domain"] == demo.DOMAIN and out["instance"] == "demo-sim" and out["engine_rows_removed"] == written
    assert _count(eng) == 0 and _count(eng, "v_destinations") == 0 and _count(eng, "v_dialplans") == 0
    for model in (PhoneSystem, PhoneSystemVersion, EngineObject, HeldNumber, EmergencyLocation):
        assert _rows(model) == []
    assert len(_rows(Tenant)) == 1 and len(_rows(Site)) == len(demo.SITES)          # the organization is the directory's: it stays
    assert _rows(AuditLog, action="phone_system.removed")[0].actor_label == manage.OPERATOR
    # And seeded again, it is the same phone system on the same rows.
    rc, out = run("demo", "seed", "demo-sim")
    assert out["state"] == "ready" and out["version"] == 1 and len(_rows(EngineObject)) == written


def test_remove_is_never_for_a_customer_or_a_live_engine(run, eng):
    run("add-instance", "demo-sim", "vox-staging", f"sipp-upstream={GATEWAY}", "simulated", stdin=URL)
    run("demo", "seed", "demo-sim")
    with SystemSession() as s:
        s.get(Tenant, ORG).demo = False                 # the directory no longer calls it a demo
        s.commit()
    with pytest.raises(SystemExit, match="only the demo"):
        run("demo", "remove")
    with SystemSession() as s:
        s.get(Tenant, ORG).demo = True
        s.execute(select(PbxInstance)).scalar_one().simulated = False
        s.commit()
    with pytest.raises(SystemExit, match="only the demo"):
        run("demo", "remove")
    assert len(_rows(PhoneSystem)) == 1 and _count(eng) > 0
