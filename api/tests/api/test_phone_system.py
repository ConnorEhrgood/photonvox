"""Step 3 end to end against a FusionPBX-shaped database: an integrator builds a phone system from a template and pasted users, Photon staff
validate the site's emergency address, the worker publishes it and runs the post-publish check; versions, undo, a failed check putting the
previous version back, hand edits found, and each number's 911 address sent to the carrier and confirmed (decision 31). The same publish is
proven with calls on the staging engine (engine/staging/prove-publish.sh)."""
from __future__ import annotations

import re
import uuid

import pytest
from sqlalchemy import select, text

from app import crypto, emergency
from app.config import settings
from app.db import SystemSession
from app.engine import service
from app.models import CarrierRequest, EmergencyNumber, EngineObject, EngineSecret, PhoneSystem, PhoneSystemVersion
from tests.api import fpbx
from tests.api.conftest import auth

USERS = "Name,Ext,Email\nAda Front,100,ada@example.com\nBen Office,,\n"
MAIN = "+17245550100"


class FakeAgent:
    """Plays vox-agent: the check reads the dial plans the adapter wrote and says what a synthetic call would find; `answers` forces one."""

    def __init__(self, eng):
        self.eng, self.answers, self.calls, self.fail_seed, self.fail_cache_after = eng, {}, [], False, None

    def seed_domain(self):
        self.calls.append("seed")
        if self.fail_seed:
            raise RuntimeError("engine unreachable")

    def clear_cache(self, keys):
        self.calls.append("cache")
        if self.fail_cache_after is not None and self.calls.count("cache") > self.fail_cache_after:
            raise RuntimeError("agent lost")

    def rescan(self, profiles, kill=()):
        self.calls.append("rescan")

    def reload_acl(self):
        self.calls.append("acl")

    def put_sound(self, domain_name, name, audio):
        self.calls.append(("sound", name, len(audio)))

    def _xml(self, c, domain_uuid, name):
        return c.execute(text("select dialplan_xml from v_dialplans where domain_uuid = :d and dialplan_name = :n"), {"d": domain_uuid, "n": name}).scalar()

    def check(self, kind, number, domain_name, domain_uuid, token):
        if number in self.answers:
            return self.answers[number]
        with self.eng.connect() as c:
            if kind == "inbound":
                data = c.execute(text("select destination_data from v_destinations where domain_uuid = :d and destination_number = :n"),
                                 {"d": domain_uuid, "n": number[2:]}).scalar()
                if data is None:
                    return None
                first = data.split(" ")[0]
                if first.startswith("hours-"):
                    xml = self._xml(c, domain_uuid, "photonvox.hours." + first[len("hours-"):])
                    first = re.findall(r'transfer" data="(\S+) XML', xml)[-1]       # closed, as at night
                return f"reached {first}"
            if number.endswith(("911", "933")):
                gws = re.search(r"gateways=([^\s\"]+)", self._xml(c, domain_uuid, "photonvox.emergency")).group(1)
                return f"emergency {gws} {number[-3:]}"
            return "blocked premium" if "photonvox_blocked=premium" in self._xml(c, domain_uuid, "photonvox.block") else None


@pytest.fixture()
def eng():
    e = fpbx.create()
    yield e
    fpbx.drop(e)


@pytest.fixture()
def agent(eng):
    return FakeAgent(eng)


@pytest.fixture()
def connect(eng, agent):
    return lambda instance: (eng, agent)


@pytest.fixture()
def built(client, world):
    """An instance, Cedar Works' phone system from the small-office template, the main site's emergency address validated."""
    r = client.post("/platform/instances", headers=auth("staff"), json={
        "name": "colo-a", "hostname": "vox-a", "database_url": "postgresql+psycopg://adapter:x@engine/fusionpbx",
        "agent_url": "http://10.2.1.21:8780", "agent_secret": "a" * 64,
        "upstreams": [{"key": "htc", "proxy": "198.51.100.5", "addresses": ["198.51.100.0/28"]}], "routing": {"national": ["htc"]},
        "emergency_upstream": "htc"})
    assert r.status_code == 201, r.text
    a = f"/tenants/{world.a}"
    assert client.post(f"{a}/phone-system", headers=auth("tech")).status_code == 201
    loc = client.post(f"{a}/sites/{world.a1}/emergency-locations", headers=auth("tech"),
                      json={"key": "main", "street": "100 Main St", "city": "Pittsburgh", "state": "PA", "zip": "15222"})
    assert loc.status_code == 201, loc.text
    assert client.post(f"/platform/emergency-locations/{loc.json()['id']}/validate", headers=auth("staff"), json={"ok": True}).json()["status"] == "validated"
    r = client.post(f"{a}/phone-system/draft/template", headers=auth("tech"),
                    json={"template": "ring-everyone", "site_id": world.a1, "location": "main", "main_number": "(724) 555-0100", "users": USERS})
    assert r.status_code == 200, r.text
    assert r.json()["problems"] == []
    return a


def ps_row(world):
    with SystemSession() as s:
        return s.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == uuid.UUID(world.a))).scalar_one()


def run(connect):
    with SystemSession() as s:
        return service.publish_queued(s, connect)


# ---- creating and building ----

def test_one_phone_system_per_organization_placed_on_an_engine(client, world, built):
    assert client.post(f"{built}/phone-system", headers=auth("tech")).status_code == 409
    got = client.get(f"{built}/phone-system", headers=auth("a-admin")).json()
    assert got["status"] == "new" and got["instance"] == "colo-a" and got["domain"].endswith(".sip.photoninfra.xyz")
    assert set(got["draft"]["users"]) == {"u-ada-front", "u-ben-office"}
    assert got["draft"]["groups"]["everyone"]["members"] == ["u-ada-front", "u-ben-office"]


def test_without_an_engine_no_phone_system_can_start(client, world):
    r = client.post(f"/tenants/{world.a}/phone-system", headers=auth("tech"))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_instance"


def test_users_and_strangers_cannot_see_or_build_it(client, world, built):
    assert client.get(f"{built}/phone-system", headers=auth("a-user")).status_code == 403
    assert client.put(f"{built}/phone-system/draft", headers=auth("a-user"), json={"document": {}}).status_code == 403
    assert client.get(f"{built}/phone-system", headers=auth("b-owner")).status_code == 404


def test_the_draft_saves_with_problems_but_does_not_publish(client, world, built):
    d = client.get(f"{built}/phone-system", headers=auth("tech")).json()["draft"]
    d["sites"][world.a1]["emergency_location"] = "floor-2"          # not validated
    r = client.put(f"{built}/phone-system/draft", headers=auth("tech"), json={"document": d})
    assert r.status_code == 200 and [p["code"] for p in r.json()["problems"]] == ["emergency_location_unvalidated"]
    r = client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_publishable"
    bad = client.put(f"{built}/phone-system/draft", headers=auth("tech"), json={"document": {"users": {"x": {"name": "X"}}}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_document"


def test_bulk_import_reviews_then_adds_the_good_rows(client, world, built):
    text_ = "Cy Annex\t200\tcy@example.com\t\tAnnex\nDee\t100\n"
    r = client.post(f"{built}/phone-system/import", headers=auth("tech"), json={"text": text_, "site_id": world.a1}).json()
    assert [row["problems"] for row in r["rows"]] == [[], ["extension 100 is taken"]] and r["rows"][0]["user"]["site"] == world.a2
    r = client.post(f"{built}/phone-system/import", headers=auth("tech"), json={"text": text_, "site_id": world.a1, "group": "everyone", "apply": True}).json()
    draft = r["phone_system"]["draft"]
    assert "u-cy-annex" in draft["users"] and "u-dee" not in draft["users"] and "u-cy-annex" in draft["groups"]["everyone"]["members"]
    assert client.post(f"{built}/phone-system/import", headers=auth("tech"), json={"text": "x", "site_id": str(uuid.uuid4())}).status_code == 404


def test_a_template_needs_a_known_template_site_and_users(client, world, built):
    body = {"template": "ring-everyone", "site_id": world.a1, "location": "main", "main_number": MAIN, "users": ""}
    assert client.post(f"{built}/phone-system/draft/template", headers=auth("tech"), json={**body, "template": "x"}).status_code == 404
    assert client.post(f"{built}/phone-system/draft/template", headers=auth("tech"), json={**body, "site_id": world.b1}).status_code == 404
    r = client.post(f"{built}/phone-system/draft/template", headers=auth("tech"), json=body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "no_users"
    assert {t["key"] for t in client.get(f"{built}/phone-system/templates", headers=auth("tech")).json()} == {"ring-everyone", "front-desk-menu"}


def test_the_menu_template_builds_a_menu(client, world, built):
    r = client.post(f"{built}/phone-system/draft/template", headers=auth("tech"),
                    json={"template": "front-desk-menu", "site_id": world.a1, "location": "main", "main_number": MAIN, "users": USERS}).json()
    assert r["draft"]["numbers"][MAIN]["open"] == {"menu": "main"} and r["problems"] == []


# ---- publishing, the check, versions ----

def test_publish_writes_checks_and_records_it(client, world, built, connect, agent, eng):
    r = client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    assert r.status_code == 202 and r.json()["state"] == "queued" and r.json()["number"] == 1
    assert client.post(f"{built}/phone-system/publish", headers=auth("tech")).status_code == 409       # one at a time
    assert run(connect) == 1
    ps = ps_row(world)
    assert ps.status == "ready" and ps.published_version == 1
    v = client.get(f"{built}/phone-system/versions", headers=auth("tech")).json()[0]
    assert v["state"] == "ready" and v["checks"]["passed"] == v["checks"]["total"] == 4 and v["checks"]["failed"] == []   # 1 number, 911, 933, premium
    assert agent.calls[0] == "seed"
    with SystemSession() as s:
        objs = s.execute(select(EngineObject).where(EngineObject.phone_system_id == ps.id)).scalars().all()
        secrets_ = {x.label: crypto.unseal(x.sealed) for x in s.execute(select(EngineSecret).where(EngineSecret.phone_system_id == ps.id)).scalars()}
    with eng.connect() as c:
        on_engine = c.execute(text("select count(*) from v_extensions where domain_uuid = :d"), {"d": str(ps.domain_uuid)}).scalar()
        pw = c.execute(text("select password from v_extensions where extension = '100'")).scalar()
    assert len(objs) > 20 and on_engine == 2 and secrets_["extension:100"] == pw and len(secrets_["voicemail:100"]) == 4


def test_a_failed_check_puts_the_previous_version_back(client, world, built, connect, agent, eng):
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    run(connect)
    d = client.get(f"{built}/phone-system", headers=auth("tech")).json()["draft"]
    d["users"]["u-ben-office"]["name"] = "Ben Renamed"
    client.put(f"{built}/phone-system/draft", headers=auth("tech"), json={"document": d})
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    agent.answers["911"] = "national htc"            # 911 would leave by the wrong route
    run(connect)
    v2, v1 = client.get(f"{built}/phone-system/versions", headers=auth("tech")).json()
    assert v2["state"] == "failed" and "1 of 4 checks failed" in v2["error"] and "version 1 restored" in v2["error"]
    assert v2["checks"]["failed"] == [{"kind": "route", "number": "911", "expected": [v2["checks"]["failed"][0]["expected"][0]], "got": "national htc"}]
    assert v1["state"] == "ready"
    ps = ps_row(world)
    assert ps.status == "failed" and ps.published_version == 1
    with eng.connect() as c:
        assert c.execute(text("select effective_caller_id_name from v_extensions where extension = '101'")).scalar() == "Ben Office"


def test_a_failed_first_publish_removes_what_it_wrote(client, world, built, connect, agent, eng):
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    agent.answers[MAIN] = None
    run(connect)
    v = client.get(f"{built}/phone-system/versions", headers=auth("tech")).json()[0]
    assert v["state"] == "failed" and "removed what it had written" in v["error"]
    with eng.connect() as c:
        assert c.execute(text("select count(*) from v_extensions")).scalar() == 0
    with SystemSession() as s:
        assert s.execute(select(EngineObject)).first() is None


def test_an_engine_that_fails_leaves_an_honest_record(client, world, built, connect, agent):
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    agent.fail_seed = True
    run(connect)
    v = client.get(f"{built}/phone-system/versions", headers=auth("tech")).json()[0]
    assert v["state"] == "failed" and "engine unreachable" in v["error"]


def test_a_version_that_became_unpublishable_in_the_queue_fails_without_touching_the_engine(client, world, built, connect, agent):
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    with SystemSession() as s:
        s.execute(text("update emergency_location set status = 'rejected'"))
        s.commit()
    run(connect)
    v = client.get(f"{built}/phone-system/versions", headers=auth("tech")).json()[0]
    assert v["state"] == "failed" and v["error"].startswith("not publishable") and agent.calls == []


def test_undo_publishes_an_earlier_version_again(client, world, built, connect, eng):
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    run(connect)
    d = client.get(f"{built}/phone-system", headers=auth("tech")).json()["draft"]
    d["users"].pop("u-ben-office")
    d["groups"]["everyone"]["members"] = ["u-ada-front"]
    client.put(f"{built}/phone-system/draft", headers=auth("tech"), json={"document": d})
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    run(connect)
    with eng.connect() as c:
        assert c.execute(text("select count(*) from v_extensions")).scalar() == 1
    r = client.post(f"{built}/phone-system/versions/1/restore", headers=auth("tech"))
    assert r.status_code == 202 and r.json()["note"] == "restored from version 1" and r.json()["number"] == 3
    run(connect)
    states = [(v["number"], v["state"]) for v in client.get(f"{built}/phone-system/versions", headers=auth("tech")).json()]
    assert states == [(3, "ready"), (2, "superseded"), (1, "superseded")]
    with eng.connect() as c:
        assert c.execute(text("select count(*) from v_extensions")).scalar() == 2
    assert "u-ben-office" in client.get(f"{built}/phone-system", headers=auth("tech")).json()["draft"]["users"]
    assert client.post(f"{built}/phone-system/versions/9/restore", headers=auth("tech")).status_code == 404


# ---- hand edits ----

def test_hand_edits_are_found_and_the_next_publish_replaces_them(client, world, built, connect, eng):
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    run(connect)
    ps = ps_row(world)
    with SystemSession() as s:
        assert service.check_drift(s, s.get(PhoneSystem, ps.id), connect)["changed"] == []
    with eng.begin() as c:
        c.execute(text("update v_extensions set effective_caller_id_name = 'Hand Edit' where extension = '100'"))
        c.execute(text("delete from v_voicemails where voicemail_id = '101'"))
        c.execute(text("insert into v_extensions (extension_uuid, domain_uuid, extension) values (:u, :d, '555')"), {"u": str(uuid.uuid4()), "d": str(ps.domain_uuid)})
        c.execute(text("insert into v_dialplans (dialplan_uuid, domain_uuid, app_uuid, dialplan_name, dialplan_enabled) values (:u, :d, :a, 'eavesdrop', true)"),
                  {"u": str(uuid.uuid4()), "d": str(ps.domain_uuid), "a": "e944af7e-8fcc-429b-a32f-0dcdce1585d8"})
    with SystemSession() as s:
        found = service.check_all_drift(s, connect)
    assert found == 1
    summary = client.get(f"{built}/phone-system", headers=auth("tech")).json()
    assert summary["status"] == "changed" and summary["drift"]["changed"] == 2 and summary["drift"]["missing"] == 1
    assert [x["label"] for x in summary["drift"]["extra"]] == ["555"]
    drift = ps_row(world).drift
    assert {(c["table"], tuple(c["columns"])) for c in drift["changed"]} == {("v_extensions", ("effective_caller_id_name",)),
                                                                            ("v_dialplans", ("dialplan_enabled",))}
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    run(connect)
    with eng.connect() as c:
        assert c.execute(text("select effective_caller_id_name from v_extensions where extension = '100'")).scalar() == "Ada Front"
        assert c.execute(text("select dialplan_enabled from v_dialplans where dialplan_name = 'eavesdrop'")).scalar() is False
    assert ps_row(world).status == "ready" and ps_row(world).drift == {}


# ---- 911 addresses with the carrier (decision 31) ----

def test_each_number_is_registered_with_the_carrier_and_unconfirmed_until_it_says_so(client, world, built, connect, monkeypatch):
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    run(connect)
    e = client.get(f"/tenants/{world.a}/emergency", headers=auth("tech")).json()
    assert [(n["number"], n["status"]) for n in e["numbers"]] == [(MAIN, "unconfirmed")]
    req = e["requests"][0]
    assert req["status"] == "open" and req["items"][0]["action"] == "add" and req["items"][0]["address"]["street"] == "100 Main St"
    sent = []
    monkeypatch.setattr(settings, "htc_e911_email", "911@htc.example")
    with SystemSession() as s:
        assert emergency.send_open(s, lambda to, subject, body: sent.append((to, subject, body)) or "msg-1") == 1
    to, subject, body = sent[0]
    assert to == "911@htc.example" and "Cedar Works" in subject and f"Add     {MAIN}  at  100 Main St, Pittsburgh, PA 15222" in body
    assert client.get(f"/tenants/{world.a}/emergency", headers=auth("tech")).json()["numbers"][0]["status"] == "requested"
    queue = client.get("/platform/carrier-requests", headers=auth("staff")).json()
    assert queue[0]["reference"] == "msg-1" and queue[0]["email"]["subject"] == subject
    assert client.post(f"/platform/carrier-requests/{req['id']}/close", headers=auth("staff"), json={"ok": True, "note": "done"}).json()["status"] == "confirmed"
    assert client.get(f"/tenants/{world.a}/emergency", headers=auth("tech")).json()["numbers"][0]["status"] == "confirmed"
    assert client.post(f"/platform/carrier-requests/{req['id']}/close", headers=auth("staff"), json={"ok": True}).status_code == 404
    assert client.get("/platform/carrier-requests", headers=auth("tech")).status_code == 403


def _confirm_all():
    with SystemSession() as s:
        for req in s.execute(select(CarrierRequest).where(CarrierRequest.status.in_(("open", "sent")))).scalars().all():
            emergency.close(s, req, True, "staff")
        s.commit()


def test_a_number_moved_to_another_address_or_given_up_makes_a_new_request(client, world, built, connect):
    d = client.get(f"{built}/phone-system", headers=auth("tech")).json()["draft"]
    d["numbers"]["+17245550111"] = {"site": world.a1, "open": {"user": "u-ada-front"}}
    client.put(f"{built}/phone-system/draft", headers=auth("tech"), json={"document": d})
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    run(connect)
    _confirm_all()
    loc = client.post(f"{built}/sites/{world.a1}/emergency-locations", headers=auth("tech"),
                      json={"key": "floor-2", "street": "100 Main St", "unit": "Floor 2", "city": "Pittsburgh", "state": "PA", "zip": "15222"}).json()
    client.post(f"/platform/emergency-locations/{loc['id']}/validate", headers=auth("staff"), json={"ok": True})
    d["sites"][world.a1]["emergency_location"] = "floor-2"
    d["numbers"].pop("+17245550111")
    client.put(f"{built}/phone-system/draft", headers=auth("tech"), json={"document": d})
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    run(connect)
    e = client.get(f"/tenants/{world.a}/emergency", headers=auth("tech")).json()
    items = {i["number"]: (i["action"], (i["address"] or {}).get("unit")) for i in e["requests"][0]["items"]}
    assert items == {MAIN: ("change", "Floor 2"), "+17245550111": ("remove", None)}
    assert {n["number"]: n["status"] for n in e["numbers"]} == {MAIN: "unconfirmed", "+17245550111": "unconfirmed"}
    _confirm_all()
    e = client.get(f"/tenants/{world.a}/emergency", headers=auth("tech")).json()
    assert [(n["number"], n["status"]) for n in e["numbers"]] == [(MAIN, "confirmed")]       # the removed number is forgotten


def test_a_rejected_request_leaves_its_numbers_unconfirmed_and_staff_can_send_by_hand(client, world, built, connect):
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    run(connect)
    req = client.get(f"/tenants/{world.a}/emergency", headers=auth("tech")).json()["requests"][0]
    assert client.post(f"/platform/carrier-requests/{req['id']}/sent", headers=auth("staff"), json={"ok": True, "reference": "HTC-4411"}).json()["status"] == "sent"
    with SystemSession() as s:
        r = s.get(CarrierRequest, uuid.UUID(req["id"]))
        assert (r.method, r.reference) == ("ticket", "HTC-4411")
    client.post(f"/platform/carrier-requests/{req['id']}/close", headers=auth("staff"), json={"ok": False, "note": "address not in MSAG"})
    with SystemSession() as s:
        n = s.get(EmergencyNumber, MAIN)
        assert (n.status, n.request_id) == ("unconfirmed", None)
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))        # republishing asks again
    run(connect)
    assert client.get(f"/tenants/{world.a}/emergency", headers=auth("tech")).json()["requests"][0]["status"] == "open"


def test_an_unsent_request_is_folded_into_the_next_and_nothing_is_sent_without_a_carrier_address(client, world, built, connect):
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    run(connect)
    with SystemSession() as s:
        assert emergency.send_open(s, lambda *a: "never") == 0                    # no carrier address configured
    d = client.get(f"{built}/phone-system", headers=auth("tech")).json()["draft"]
    d["numbers"]["+17245550111"] = {"site": world.a1, "open": {"user": "u-ada-front"}}
    client.put(f"{built}/phone-system/draft", headers=auth("tech"), json={"document": d})
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    run(connect)
    reqs = client.get(f"/tenants/{world.a}/emergency", headers=auth("tech")).json()["requests"]
    assert [r["status"] for r in reqs] == ["open", "superseded"]
    assert sorted(i["number"] for i in reqs[0]["items"]) == [MAIN, "+17245550111"]


def test_staff_queue_and_validation_need_staff(client, world, built):
    assert client.get("/platform/emergency-locations", headers=auth("tech")).status_code == 403
    assert client.get("/platform/emergency-locations", headers=auth("staff")).json() == []
    assert client.post(f"/platform/emergency-locations/{uuid.uuid4()}/validate", headers=auth("staff"), json={"ok": True}).status_code == 404
    assert client.post(f"/tenants/{world.a}/sites/{world.a2}/emergency-locations", headers=auth("a-admin-s1"),
                       json={"key": "x", "street": "1 A St", "city": "Xx", "state": "PA", "zip": "15222"}).status_code == 404


def test_an_instance_must_route_through_its_own_upstreams(client, world):
    body = {"name": "bad", "hostname": "h", "database_url": "postgresql://x/y", "agent_url": "http://e:8780", "agent_secret": "a" * 40,
            "upstreams": [{"key": "htc", "proxy": "p.example", "addresses": ["198.51.100.0/28"]}], "routing": {"national": ["other"]}, "emergency_upstream": "htc"}
    r = client.post("/platform/instances", headers=auth("staff"), json=body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_routing"
    assert client.get("/platform/instances", headers=auth("staff")).json() == []


def test_if_putting_the_previous_version_back_fails_too_it_says_so(client, world, built, connect, agent):
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    agent.answers["911"] = None
    agent.fail_cache_after = 1                        # the publish clears the cache; the restore's clear fails
    run(connect)
    v = client.get(f"{built}/phone-system/versions", headers=auth("tech")).json()[0]
    assert v["state"] == "failed" and "restoring failed too: RuntimeError: agent lost" in v["error"]


def test_an_organization_without_a_phone_system_is_told_so(client, world):
    r = client.get(f"/tenants/{world.b}/phone-system", headers=auth("b-owner"))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_phone_system"


def test_the_worker_publishes_queued_versions(client, world, built, connect):
    from app import worker
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    state = {}
    worker.engine_jobs(state, 0.0, connect)
    assert ps_row(world).status == "ready" and "drift" in state


def test_an_instance_is_reached_through_its_sealed_login_and_its_agent(client, world, built):
    from app.engine.agent import HttpAgent
    from app.models import PbxInstance
    with SystemSession() as s:
        i = s.execute(select(PbxInstance)).scalar_one()
        assert "adapter:x@engine" not in i.database_url_sealed
        eng, a = service.connect(i)
        assert str(eng.url).startswith("postgresql+psycopg://adapter:") and isinstance(a, HttpAgent) and a.url == "http://10.2.1.21:8780"
        assert "a" * 64 not in i.agent_secret_sealed and a.secret == "a" * 64
        i.agent = {}
        with pytest.raises(RuntimeError, match="no agent"):
            service.connect(i)


def test_drift_on_a_failed_phone_system_is_recorded_without_changing_its_state(client, world, built, connect, eng):
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    run(connect)
    ps = ps_row(world)
    with eng.begin() as c:        # a feature dial plan already as PhotonVox wants it is not a change
        c.execute(text("insert into v_dialplans (dialplan_uuid, domain_uuid, app_uuid, dialplan_name, dialplan_enabled) values (:u, :d, :a, 'eavesdrop', false)"),
                  {"u": str(uuid.uuid4()), "d": str(ps.domain_uuid), "a": "e944af7e-8fcc-429b-a32f-0dcdce1585d8"})
    with SystemSession() as s:
        s.execute(text("update phone_system set status = 'failed'"))
        s.commit()
        got = service.check_drift(s, s.get(PhoneSystem, ps.id), connect)
    assert got["changed"] == [] and ps_row(world).status == "failed"


def test_a_customers_call_flows_can_be_cloned_by_someone_who_sees_both(client, world, built):
    b = f"/tenants/{world.b}"
    assert client.post(f"{built}/phone-system/draft/clone", headers=auth("tech"), json={"from_tenant_id": world.b}).status_code == 404  # B has none yet
    assert client.post(f"{b}/phone-system", headers=auth("tech")).status_code == 201
    r = client.post(f"{b}/phone-system/draft/clone", headers=auth("tech"), json={"from_tenant_id": world.a})
    assert r.status_code == 200, r.text
    d = r.json()["draft"]
    assert d["hours"]["office"]["holidays"] == "us-federal" and "everyone" not in d["groups"]        # B has nobody with A's extensions yet
    assert client.post(f"{b}/phone-system/draft/clone", headers=auth("b-owner"), json={"from_tenant_id": world.a}).status_code == 404   # cannot see A
    assert client.post(f"{built}/phone-system/draft/clone", headers=auth("tech"), json={"from_tenant_id": world.a}).status_code == 404  # itself
    assert client.post(f"{b}/phone-system/draft/clone", headers=auth("tech"), json={"from_tenant_id": str(uuid.uuid4())}).status_code == 404


# ---- an instance's own settings: upstreams and outgoing mail ----

@pytest.fixture()
def staff_connect(client, connect):
    """On the client's own app: another test reloads app.main, so `from app.main import app` may be a different object than the one serving."""
    from app.routes import platform
    client.app.dependency_overrides[platform.get_connect] = lambda: connect
    yield
    client.app.dependency_overrides.pop(platform.get_connect, None)


def test_an_instances_upstreams_and_mail_are_put_on_its_engine(client, world, built, staff_connect, eng, agent):
    iid = client.get("/platform/instances", headers=auth("staff")).json()[0]["id"]
    body = {"host": "smtp.postmarkapp.com", "port": 587, "secure": "tls", "username": "pm-token", "password": "pm-token", "from": "voicemail@photonind.com",
            "from_name": "Voicemail"}
    got = client.put(f"/platform/instances/{iid}/email", headers=auth("staff"), json=body).json()
    assert got["email"]["host"] == "smtp.postmarkapp.com" and got["email_password_set"] and "password" not in got["email"]
    with eng.begin() as c:
        c.execute(text("insert into v_access_controls values (gen_random_uuid(), 'providers')"))
    r = client.post(f"/platform/instances/{iid}/apply", headers=auth("staff"))
    assert r.status_code == 200 and r.json() == {"gateways": ["htc"], "removed": 0, "email": True}, r.text
    assert agent.calls == ["cache", "rescan", "acl"]
    with eng.connect() as c:
        rows = dict(c.execute(text("select default_setting_subcategory, default_setting_value from v_default_settings where default_setting_category = 'email'")).all())
        gw = c.execute(text("select gateway, proxy from v_gateways")).all()
    assert rows == {"smtp_host": "smtp.postmarkapp.com", "smtp_port": "587", "smtp_secure": "tls", "smtp_auth": "true", "smtp_username": "pm-token",
                    "smtp_password": "pm-token", "smtp_from": "voicemail@photonind.com", "smtp_from_name": "Voicemail"}
    assert gw == [("htc", "198.51.100.5")]
    client.put(f"/platform/instances/{iid}/email", headers=auth("staff"), json={**body, "password": "", "username": ""})
    client.post(f"/platform/instances/{iid}/apply", headers=auth("staff"))
    with eng.connect() as c:
        rows = dict(c.execute(text("select default_setting_subcategory, default_setting_value from v_default_settings where default_setting_category = 'email'")).all())
    assert rows["smtp_password"] == "pm-token" and rows["smtp_auth"] == "false"          # an empty password keeps the one set


def test_an_instance_without_mail_or_an_engine_that_fails(client, world, built, staff_connect, agent, eng):
    iid = client.get("/platform/instances", headers=auth("staff")).json()[0]["id"]
    with eng.begin() as c:
        c.execute(text("insert into v_access_controls values (gen_random_uuid(), 'providers')"))
    assert client.post(f"/platform/instances/{iid}/apply", headers=auth("staff")).json()["email"] is False
    agent.fail_cache_after = 0
    r = client.post(f"/platform/instances/{iid}/apply", headers=auth("staff"))
    assert r.status_code == 502 and r.json()["detail"]["code"] == "engine_failed"
    for path in (f"/platform/instances/{uuid.uuid4()}/apply",):
        assert client.post(path, headers=auth("staff")).status_code == 404
    assert client.put(f"/platform/instances/{uuid.uuid4()}/email", headers=auth("staff"),
                      json={"host": "smtp.example", "from": "a@b.co"}).status_code == 404
    assert client.post(f"/platform/instances/{iid}/apply", headers=auth("tech")).status_code == 403


def test_with_a_mail_password_set_once_and_none_given_later_it_still_writes_nothing_new(client, world, built, staff_connect, eng):
    iid = client.get("/platform/instances", headers=auth("staff")).json()[0]["id"]
    client.put(f"/platform/instances/{iid}/email", headers=auth("staff"), json={"host": "10.10.0.80", "port": 2525, "secure": "none", "from": "vm@vox.test"})
    with eng.begin() as c:
        c.execute(text("insert into v_access_controls values (gen_random_uuid(), 'providers')"))
    client.post(f"/platform/instances/{iid}/apply", headers=auth("staff"))
    with eng.connect() as c:
        rows = dict(c.execute(text("select default_setting_subcategory, default_setting_value from v_default_settings where default_setting_category = 'email'")).all())
    assert rows["smtp_password"] == "" and rows["smtp_secure"] == "none" and rows["smtp_port"] == "2525"


def test_routes_reach_engines_through_the_real_connection_unless_a_test_says_otherwise():
    from app.routes import platform
    assert platform.get_connect() is service.connect


# ---- greetings spoken at publish (decision 30) ----

class FakeSpeech:
    def __init__(self):
        self.spoken = []

    def synthesize(self, text, voice):
        self.spoken.append((text, voice))
        return b"RIFF\x24\x00\x00\x00WAVE" + text.encode()


def test_greetings_are_spoken_once_cached_and_named_by_their_menus(client, world, built, connect, agent, eng, monkeypatch):
    from app import speech as sp
    from app.models import SpeechAudio
    fake = FakeSpeech()
    monkeypatch.setattr(service, "get_speech", lambda: fake)
    client.post(f"{built}/phone-system/draft/template", headers=auth("tech"),
                json={"template": "front-desk-menu", "site_id": world.a1, "location": "main", "main_number": MAIN, "users": USERS})
    d = client.get(f"{built}/phone-system", headers=auth("tech")).json()["draft"]
    d["voice"] = "en-US-Chirp3-HD-Charon"
    client.put(f"{built}/phone-system/draft", headers=auth("tech"), json={"document": d})
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    run(connect)
    greeting = d["menus"]["main"]["greeting"]
    name = sp.file_name(greeting, "en-US-Chirp3-HD-Charon")
    assert fake.spoken == [(greeting, "en-US-Chirp3-HD-Charon")]
    assert ("sound", name, len(fake.synthesize(greeting, "x"))) in agent.calls
    with eng.connect() as c:
        assert c.execute(text("select ivr_menu_greet_long from v_ivr_menus")).scalar() == name
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    run(connect)
    assert len(fake.spoken) == 2          # the second was this test's own call above: the republish took the audio from the cache
    with SystemSession() as s:
        assert [(a.voice, a.characters) for a in s.execute(select(SpeechAudio)).scalars()] == [("en-US-Chirp3-HD-Charon", len(greeting))]
    assert client.get(f"{built}/phone-system/versions", headers=auth("tech")).json()[0]["state"] == "ready"


def test_without_a_provider_menus_publish_without_a_greeting(client, world, built, connect, eng):
    client.post(f"{built}/phone-system/draft/template", headers=auth("tech"),
                json={"template": "front-desk-menu", "site_id": world.a1, "location": "main", "main_number": MAIN, "users": USERS})
    client.post(f"{built}/phone-system/publish", headers=auth("tech"))
    run(connect)
    with eng.connect() as c:
        assert c.execute(text("select ivr_menu_greet_long from v_ivr_menus")).scalar() is None


def test_the_provider_is_google_when_a_key_is_set(monkeypatch):
    from app.config import settings
    from app.speech.google import GoogleSpeech
    assert service.get_speech() is None
    monkeypatch.setattr(settings, "google_tts_api_key", "k")
    assert isinstance(service.get_speech(), GoogleSpeech)
