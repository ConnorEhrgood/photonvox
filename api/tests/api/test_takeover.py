"""The takeover in place, through the API and the worker (decision 32, ARCHITECTURE §17), against a hand-built FusionPBX domain in a database of
its own shape (tests/takeover_fixture.py): adopt, publish (nothing written), hand edits found on adopted and hand-built rows, and the refusals."""
import json
import os

import pytest
from sqlalchemy import create_engine, select, text

from app.db import SystemSession
from app.engine import service
from app.engine.fusionpbx import KEYS
from app.models import CarrierRequest, EmergencyNumber, EngineObject, HeldNumber, PhoneSystem
from app.routes import platform
from tests import takeover_fixture as F
from tests.api.conftest import auth

SCHEMA = "fpbx_hand"


def _type(col, values):
    if col.endswith("_uuid"):
        return "uuid"
    v = next((x for x in values if x is not None), None)
    return {bool: "boolean", int: "numeric", list: "json", dict: "json"}.get(type(v), "text")


@pytest.fixture()
def eng():
    """The hand-built domain, in tables shaped by its own rows (FusionPBX has more columns than PhotonVox writes)."""
    e = create_engine(os.environ["MIGRATE_DATABASE_URL"], connect_args={"options": f"-c search_path={SCHEMA}"})
    export = F.hand_built()
    with e.begin() as c:
        c.execute(text(f"drop schema if exists {SCHEMA} cascade; create schema {SCHEMA}"))
        c.execute(text("create table v_domains (domain_uuid uuid primary key, domain_name text, domain_enabled boolean)"))
        c.execute(text("insert into v_domains values (:d, :n, true), (:o, 'other.example.test', true)"), {"d": F.D, "n": F.DOMAIN, "o": F.OTHER})
        for t, rows in export["tables"].items():
            cols = {}
            for r in rows:
                for k, v in r.items():
                    cols.setdefault(k, []).append(v)
            cols.setdefault("domain_uuid", [None])
            if t == "v_extensions":
                cols.setdefault("password", ["x"])
            if t == "v_voicemails":
                cols.setdefault("voicemail_password", ["x"])
            if t == "v_ring_groups":
                cols.setdefault("ring_group_extension", [None])        # empty here, but every FusionPBX has the column
            key = KEYS.get(t) or next(k for k in cols if k.endswith("_uuid") and k.startswith(t[2:].rstrip("s").split("_")[0]))
            cols.setdefault(key, [None])
            body = ", ".join(f"{k} {'timestamptz' if k.endswith('_date') else _type(k, v)}" + (" primary key" if k == key else "") for k, v in cols.items())
            c.execute(text(f"create table {t} ({body})"))
            for r in rows:
                names = list(r)
                c.execute(text(f"insert into {t} ({', '.join(names)}) values ({', '.join('cast(:' + n + ' as json)' if isinstance(r[n], (list, dict)) else ':' + n for n in names)})"),
                          {n: json.dumps(v) if isinstance(v, (list, dict)) else v for n, v in r.items()})
        c.execute(text("update v_extensions set password = 'sip-secret-' || extension; update v_voicemails set voicemail_password = '1234'"))
    yield e
    with e.begin() as c:
        c.execute(text(f"drop schema {SCHEMA} cascade"))
    e.dispose()


@pytest.fixture()
def connect(eng):
    return lambda instance: (eng, service.NoAgent())


@pytest.fixture()
def instance(client, connect):
    client.app.dependency_overrides[platform.get_connect] = lambda: connect
    r = client.post("/platform/instances", headers=auth("staff"), json={
        "name": "live-a", "hostname": "fusionpbx", "database_url": "postgresql+psycopg://photonvox_rw:x@10.10.0.21/fusionpbx",
        "upstreams": [], "own_gateways": {"htc": F.GATEWAY}, "routing": {"national": ["htc"]}, "emergency_upstream": "htc"})
    assert r.status_code == 201, r.text
    yield r.json()
    client.app.dependency_overrides.pop(platform.get_connect, None)


def snapshot(eng):
    with eng.connect() as c:
        return {t: sorted(json.dumps(dict(r), sort_keys=True, default=str) for r in c.execute(text(f"select * from {t}")).mappings())
                for t in ("v_extensions", "v_voicemails", "v_destinations", "v_dialplans", "v_dialplan_details", "v_ivr_menus", "v_ivr_menu_options")}


def adopt(client, world, instance, **over):
    body = {"tenant_id": world.a, "site_id": world.a1, "domain": F.DOMAIN, **over}
    return client.post(f"/platform/instances/{instance['id']}/adopt", headers=auth("staff"), json=body)


def run(connect):
    with SystemSession() as s:
        return service.publish_queued(s, connect)


def test_an_engine_with_its_own_gateways_and_no_agent_is_registered_and_never_applied(client, world, instance):
    assert instance["agent_kind"] == "none" and instance["own_gateways"] == {"htc": F.GATEWAY} and instance["upstreams"] == []
    r = client.post(f"/platform/instances/{instance['id']}/apply", headers=auth("staff"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "hand_built"
    base = {"name": "x", "hostname": "h", "database_url": "postgresql+psycopg://a:b@c/d", "routing": {"national": ["htc"]}, "emergency_upstream": "htc"}
    half = client.post("/platform/instances", headers=auth("staff"), json={**base, "agent_url": "http://10.2.1.9:8780", "upstreams": [], "own_gateways": {"htc": F.GATEWAY}})
    assert half.status_code == 422 and half.json()["detail"]["code"] == "bad_agent"
    both = client.post("/platform/instances", headers=auth("staff"), json={**base, "own_gateways": {"htc": F.GATEWAY},
                       "upstreams": [{"key": "htc", "proxy": "198.51.100.5", "addresses": ["198.51.100.0/28"]}]})
    assert both.status_code == 422 and both.json()["detail"]["code"] == "bad_routing"
    with SystemSession() as s:
        from app.models import PbxInstance
        with pytest.raises(ValueError, match="its own"):
            service.apply_instance(s.get(PbxInstance, __import__("uuid").UUID(instance["id"])))


def test_adopting_proves_a_no_op_keeps_the_document_and_assigns_the_numbers(client, world, instance, eng):
    assert client.post(f"/platform/instances/{instance['id']}/adopt", headers=auth("a-owner"), json={"tenant_id": world.a, "site_id": world.a1,
                       "domain": F.DOMAIN}).status_code == 403
    before = snapshot(eng)
    r = adopt(client, world, instance)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["objects"] == 8 and out["extras"] == 4 and len(out["understanding"]) == 2
    assert {i["what"] for i in out["report"] if i["outcome"] == "decide"} == {"extension 102"}
    assert snapshot(eng) == before                                            # adopting reads only
    got = client.get(f"/tenants/{world.a}/phone-system", headers=auth("a-owner")).json()
    assert got["status"] == "new" and got["draft"]["menus"]["main"]["greeting"] == "recording:MainMenu.wav"
    with SystemSession() as s:
        held = {h.number: str(h.tenant_id) for h in s.execute(select(HeldNumber)).scalars()}
        assert held == {"+1" + n: world.a for n in (F.MAIN, F.SECOND, F.DIRECT)}
        ps = s.execute(select(PhoneSystem)).scalar_one()
        assert ps.domain_name == F.DOMAIN and str(ps.domain_uuid) == F.D and len(ps.adoption["extras"]) == 4
        assert "password" not in json.dumps(ps.adoption)                      # the secrets were never read
    assert adopt(client, world, instance).json()["detail"]["code"] == "not_adopted"           # once only


def test_adoption_is_refused_with_a_reason(client, world, instance, eng):
    assert adopt(client, world, instance, domain="nowhere.example.test").json()["detail"]["detail"] == "the engine has no domain 'nowhere.example.test'"
    assert adopt(client, world, instance, tenant_id="5c0a0000-0000-4000-8000-00000000dead").status_code == 404
    assert client.put(f"/platform/numbers/+1{F.MAIN}", headers=auth("staff"), json={"tenant_id": world.b}).status_code == 200
    r = adopt(client, world, instance)
    assert r.status_code == 409 and "assigned to another organization" in r.json()["detail"]["detail"]
    client.put(f"/platform/numbers/+1{F.MAIN}", headers=auth("staff"), json={})               # back to Photon's stock: adoption takes it
    assert adopt(client, world, instance).status_code == 201
    with SystemSession() as s:
        ps = s.execute(select(PhoneSystem)).scalar_one()
        other = PhoneSystem(tenant_id=__import__("uuid").UUID(world.b), instance_id=ps.instance_id, domain_name="x", domain_uuid=ps.domain_uuid)
        s.add(other)
        with pytest.raises(Exception):
            s.flush()                                                          # one phone system per domain (a unique column)
        s.rollback()
    assert adopt(client, world, instance, tenant_id=world.b).json()["detail"]["detail"] == "this domain already belongs to a phone system"


def test_the_first_publish_writes_nothing_and_registers_no_911_numbers(client, world, instance, eng, connect):
    assert adopt(client, world, instance).status_code == 201
    before = snapshot(eng)
    assert client.post(f"/tenants/{world.a}/phone-system/publish", headers=auth("a-owner")).status_code == 202
    assert run(connect) == 1
    v = client.get(f"/tenants/{world.a}/phone-system/versions", headers=auth("a-owner")).json()[0]
    assert v["state"] == "ready" and v["checks"]["total"] == 0
    assert snapshot(eng) == before                                            # not one row written, not even a date
    with SystemSession() as s:
        assert len(s.execute(select(EngineObject)).scalars().all()) == 21     # the adopted rows: 4 + 4 phones' rows, 3 + 3 + 2 numbers', 5 the menu's
        assert s.execute(select(EmergencyNumber)).first() is None and s.execute(select(CarrierRequest)).first() is None
    with SystemSession() as s:
        assert service.check_all_drift(s, connect) == 1
    got = client.get(f"/tenants/{world.a}/phone-system", headers=auth("a-owner")).json()
    assert got["status"] == "ready"


def test_hand_edits_are_found_on_adopted_and_hand_built_rows(client, world, instance, eng, connect):
    adopt(client, world, instance)
    client.post(f"/tenants/{world.a}/phone-system/publish", headers=auth("a-owner"))
    run(connect)
    with eng.begin() as c:
        c.execute(text("update v_dialplans set dialplan_xml = '<extension name=\"edited\"/>', update_date = now() where dialplan_uuid = :u"), {"u": F._u(36)})
        c.execute(text("delete from v_dialplans where dialplan_uuid = :u"), {"u": F._u(37)})
    with SystemSession() as s:
        ps = s.execute(select(PhoneSystem)).scalar_one()
        found = service.check_drift(s, ps, connect)
    assert found["changed"] == [] and sorted((x["uuid"], x["kind"]) for x in found["hand_built_changed"]) == [(F._u(36), "changed"), (F._u(37), "removed")]
    assert client.get(f"/tenants/{world.a}/phone-system", headers=auth("a-owner")).json()["status"] == "changed"
    with eng.begin() as c:                                                     # an adopted user renamed in FusionPBX's screens
        c.execute(text("update v_extensions set effective_caller_id_name = 'Hand Edit' where extension = '101'"))
    with SystemSession() as s:
        found = service.check_drift(s, s.execute(select(PhoneSystem)).scalar_one(), connect)
    assert [(x["table"], x["columns"]) for x in found["changed"]] == [("v_extensions", ["effective_caller_id_name"])]
    # Putting it back needs the engine's cache cleared: without vox-agent the publish fails cleanly and says why.
    client.post(f"/tenants/{world.a}/phone-system/publish", headers=auth("a-owner"))
    run(connect)
    v = client.get(f"/tenants/{world.a}/phone-system/versions", headers=auth("a-owner")).json()[0]
    assert v["state"] == "failed"
    with eng.connect() as c:
        assert c.execute(text("select effective_caller_id_name from v_extensions where extension = '101'")).scalar() == "Hand Edit"


def test_a_put_back_with_an_agent_rewrites_the_row_and_clears_its_cache(client, world, instance, eng):
    cleared = []

    class Agent:
        def clear_cache(self, entries):
            cleared.extend(entries)

    agent = Agent()
    with_agent = lambda i: (eng, agent)     # noqa: E731
    adopt(client, world, instance)
    client.post(f"/tenants/{world.a}/phone-system/publish", headers=auth("a-owner"))
    run(with_agent)
    assert cleared == []
    with eng.begin() as c:
        c.execute(text("update v_extensions set effective_caller_id_name = 'Hand Edit' where extension = '101'"))
    client.post(f"/tenants/{world.a}/phone-system/publish", headers=auth("a-owner"))
    run(with_agent)
    assert cleared == [f"directory.101@{F.DOMAIN}"]
    with eng.connect() as c:
        row = c.execute(text("select effective_caller_id_name, password from v_extensions where extension = '101'")).first()
    assert row.effective_caller_id_name == "Pastor" and row.password == "sip-secret-101"          # the live value back, the secret untouched


def test_the_operator_commands_do_the_takeover_without_a_browser(client, world, eng):
    import io
    from app import manage
    conn = lambda i: (eng, service.NoAgent())         # noqa: E731
    run_ = lambda *a, stdin="": (lambda o: (manage.main(list(a), io.StringIO(stdin), o, conn), json.loads(o.getvalue() or "null") if o.getvalue().strip().startswith(("{", "[")) else o.getvalue()))(io.StringIO())   # noqa: E731
    with pytest.raises(SystemExit, match="standard input"):
        run_("add-instance", "live-a", "fusionpbx", f"htc={F.GATEWAY}", stdin="nonsense\n")
    rc, added = run_("add-instance", "live-a", "fusionpbx", f"htc={F.GATEWAY}", stdin="postgresql+psycopg://photonvox_rw:x@10.10.0.21/fusionpbx\n")
    assert rc == 0 and added["own_gateways"] == {"htc": F.GATEWAY}
    with pytest.raises(SystemExit, match="no phone system"):
        run_("show", world.a)
    before = snapshot(eng)
    rc, adopted = run_("adopt", "live-a", world.a, world.a1, F.DOMAIN)
    assert rc == 0 and adopted["objects"] == 8
    rc, published = run_("publish", world.a, "the takeover, behavior unchanged")
    assert rc == 0 and published["state"] == "ready" and published["checks"] == [] and not published["error"]
    assert snapshot(eng) == before
    rc, drift = run_("drift", world.a)
    assert drift["changed"] == [] and drift["hand_built_changed"] == []
    rc, shown = run_("show", world.a)
    assert shown["status"] == "ready" and shown["adopted"] and [(v["number"], v["state"]) for v in shown["versions"]] == [(1, "ready")]
    assert run_("nonsense")[0] == 2 and run_()[0] == 2
    with SystemSession() as s:
        from app.models import AuditLog
        actions = [a.action for a in s.execute(select(AuditLog).where(AuditLog.actor_label == manage.OPERATOR)).scalars()]
    assert actions == ["instance.added", "phone_system.adopted", "phone_system.publish_requested", "phone_system.published"] or \
        set(actions) >= {"instance.added", "phone_system.adopted", "phone_system.publish_requested"}


class EngineAgent:
    """Answers the post-publish check from what is on the (test) engine, and records the cache it was asked to clear. Never 911 or 933."""
    available = True

    def __init__(self, eng):
        self.eng, self.cleared = eng, []

    def clear_cache(self, entries):
        self.cleared += list(entries)

    def check(self, kind, number, domain, domain_uuid, token):
        assert "911" not in number and "933" not in number
        with self.eng.connect() as c:
            if kind == "inbound":
                data = c.execute(text("select destination_data from v_destinations where domain_uuid = :d and destination_number = :n"),
                                 {"d": domain_uuid, "n": number[-10:]}).scalar()
                return f"reached {data.split(' ')[0]}" if data else None
            xml = c.execute(text("select dialplan_xml from v_dialplans where domain_uuid = :d and dialplan_name = 'photonvox.block'"), {"d": domain_uuid}).scalar()
            return "blocked premium" if xml and "photonvox_blocked=premium" in xml else None


def test_the_protections_version_dry_run_then_published(client, world, instance, eng):
    import io
    from app import manage
    agent = EngineAgent(eng)
    conn = lambda i: (eng, agent)            # noqa: E731
    def run_(*a):
        o = io.StringIO()
        rc = manage.main(list(a), io.StringIO(), o, conn)
        return rc, json.loads(o.getvalue())
    assert adopt(client, world, instance).status_code == 201
    client.post(f"/tenants/{world.a}/phone-system/publish", headers=auth("a-owner"))
    with SystemSession() as s:
        service.publish_queued(s, lambda i: (eng, service.NoAgent()))
    rc, again = run_("readopt", world.a)
    assert rc == 0 and again["objects"] == 8
    before = snapshot(eng)
    with pytest.raises(SystemExit, match="e164 or nanp10"):
        run_("set-format", "live-a", "htc=10")
    rc, fmt = run_("set-format", "live-a", "htc=nanp10")                # as the hand-built routes send HTC today: ten digits
    assert fmt["dial_formats"] == {"htc": "nanp10"}
    rc, dry = run_("protect", world.a, "101", "Outbound NANP", "Block-premium")
    assert dry["blocking_the_publish"][0]["code"] == "emergency_location_unvalidated"         # the 911 address is not validated yet
    assert dry["changes"] == ["v_extensions emergency_caller_id_number, toll_allow"] and dry["retired"] == ["Block-premium", "Outbound NANP"]
    assert {"photonvox.emergency", "photonvox.block", "photonvox.national", "photonvox.service", "photonvox.toll_free"} <= set(dry["new_dialplans"])
    calls = dry["calls_out"]
    assert calls["9005550100"]["now"].startswith("Block-premium") and calls["9005550100"]["after"].startswith("photonvox.block")
    assert calls["2125550123"]["now"].startswith("Outbound NANP") and calls["2125550123"]["after"].startswith("photonvox.national")
    assert calls["2125550123"]["after"].endswith("gateway/…/2125550123") and calls["+12125550123"]["after"].endswith("gateway/…/2125550123")
    assert calls["988"]["now"] == "no route (the call fails)" and calls["988"]["after"].startswith("photonvox.service")
    assert calls["911"]["after"].startswith("photonvox.emergency") and "911" not in "".join(dry["checks"])
    assert snapshot(eng) == before                                                             # a dry run writes nothing
    with pytest.raises(Exception, match="not a hand-built dial plan"):
        run_("protect", world.a, "101", "photonvox.national")
    loc = client.post(f"/tenants/{world.a}/sites/{world.a1}/emergency-locations", headers=auth("a-owner"),
                      json={"key": "main", "street": "1 Church St", "city": "Hickory", "state": "PA", "zip": "15340"}).json()
    assert client.post(f"/platform/emergency-locations/{loc['id']}/validate", headers=auth("staff"), json={"ok": True}).status_code == 200
    rc, applied = run_("protect-apply", world.a, "Outbound NANP", "Block-premium")
    assert applied == {"protected": True, "retire": ["Outbound NANP", "Block-premium"]} and snapshot(eng) == before
    rc, published = run_("publish", world.a, "the protections version")
    assert published["state"] == "ready", published
    assert all(c["ok"] for c in published["checks"]) and {c["kind"] for c in published["checks"]} == {"inbound", "route", "emergency, read"}
    with eng.connect() as c:
        names = set(c.execute(text("select dialplan_name from v_dialplans where domain_uuid = :d"), {"d": F.D}).scalars())
        ext = {r.extension: r for r in c.execute(text("select extension, toll_allow, emergency_caller_id_number, hold_music, call_timeout, password "
                                                      "from v_extensions"))}
        details = c.execute(text("select count(*) from v_dialplan_details where dialplan_uuid = :u"), {"u": F._u(36)}).scalar()
    assert "Outbound NANP" not in names and "Block-premium" not in names and details == 0 and "old route" in names     # retired; the rest left
    assert ext["701"].toll_allow == "national:service:toll_free" and ext["701"].emergency_caller_id_number == "+1" + F.SECOND
    assert ext["100"].emergency_caller_id_number == "+1" + F.MAIN and str(ext["701"].call_timeout) == "120"          # what the document doesn't say stays
    assert ext["100"].hold_music == f"/{F.DOMAIN}/Music.wav" and ext["101"].password == "sip-secret-101"
    assert f"dialplan.{F.DOMAIN}" in agent.cleared and f"directory.701@{F.DOMAIN}" in agent.cleared
