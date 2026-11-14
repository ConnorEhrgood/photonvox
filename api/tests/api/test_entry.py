"""PhotonEntry's connection (app/routes/integrations.py; photonaccess docs/VOX.md and contract/vox/): the organization's token, the door stations
with their SIP accounts, and who answered a door's call. Answers are checked against PhotonEntry's own schemas (contract/vox/ in photonaccess,
copied into tests/entry_contract)."""
from __future__ import annotations

import json
import pathlib
import uuid
from datetime import datetime, timezone

import jsonschema
import pytest
from sqlalchemy import select, text

from app.db import SystemSession
from app.models import AuditLog, IntegrationToken, PbxInstance
from app.routes import platform
from tests.api.conftest import auth
from tests.api.test_phone_system import FakeAgent, built, eng, ps_row   # noqa: F401 - fixtures

CONTRACT = pathlib.Path(__file__).resolve().parents[1] / "entry_contract"
SCHEMA = {n: json.loads((CONTRACT / f"{n}.schema.json").read_text()) for n in ("door-stations", "door-call")}
CALL_A, CALL_B = "0b5e8c1a-0000-4000-8000-00000000ca11", "0b5e8c1a-0000-4000-8000-00000000ca12"


class DoorAgent(FakeAgent):
    """The engine's vox-agent for these tests: the checks as in test_phone_system, and the door's log lines are what `log` holds."""
    available = True

    def __init__(self, eng):
        super().__init__(eng)
        self.log, self.asked = [], []

    def door_calls(self, domain_name, extension, since):
        self.asked.append((domain_name, extension, since))
        return list(self.log)


def _valid(name, body):
    jsonschema.Draft202012Validator(SCHEMA[name], format_checker=jsonschema.FormatChecker()).validate(body)


@pytest.fixture()
def doors(client, world, built, eng):
    """Cedar Works' phone system with a front door (ringing the office group; Ada after hours), published; the engine has call records."""
    with SystemSession() as s:
        draft = ps_row(world).draft
    users = {k: u for k, u in draft["users"].items()}
    first = sorted(users, key=lambda k: users[k]["extension"])[0]
    users[first]["email"] = "A-Admin@example.com"                   # the directory person a-admin, matched by email
    draft["doors"] = {"front": {"name": "Front door", "site": world.a1, "extension": "701", "open": {"user": first}}}
    r = client.put(f"{built}/phone-system/draft", headers=auth("tech"), json={"document": draft})
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    with eng.begin() as c:
        c.execute(text("create table v_xml_cdr (xml_cdr_uuid uuid primary key, domain_uuid uuid, extension_uuid uuid, start_epoch numeric, "
                       "answer_epoch numeric, end_epoch numeric)"))
    agent = DoorAgent(eng)
    conn = lambda i: (eng, agent)       # noqa: E731
    client.app.dependency_overrides[platform.get_connect] = lambda: conn
    assert client.post(f"{built}/phone-system/publish", headers=auth("tech")).status_code == 202
    with SystemSession() as s:
        from app.engine import service
        service.publish_queued(s, conn)
    ps = ps_row(world)
    assert ps.published_version == 1, ps.status
    return {"agent": agent, "ps": ps, "first": users[first], "base": built}


def _token(client, world, who="a-admin"):
    r = client.post(f"/tenants/{world.a}/integrations/entry-tokens", headers=auth(who), json={"label": "PhotonEntry"})
    assert r.status_code == 201, r.text
    return r.json()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_admins_make_list_and_revoke_tokens_shown_once(client, world):
    for who in ("a-user", "b-owner", "stranger"):
        assert client.post(f"/tenants/{world.a}/integrations/entry-tokens", headers=auth(who), json={}).status_code in (403, 404)
    t = _token(client, world)
    assert t["token"].startswith("pvx_entry_") and len(t["token"]) > 40 and t["hint"] == t["token"][-4:] and t["scope"] == "vox:entry"
    listed = client.get(f"/tenants/{world.a}/integrations/entry-tokens", headers=auth("a-owner")).json()
    assert [x["id"] for x in listed] == [t["id"]] and "token" not in listed[0]
    with SystemSession() as s:
        row = s.get(IntegrationToken, uuid.UUID(t["id"]))
        assert row.token_hash != t["token"] and t["token"] not in json.dumps(listed)
    assert client.get(f"/tenants/{world.b}/integrations/entry-tokens", headers=auth("b-owner")).json() == []     # another organization's: unseen
    assert client.delete(f"/tenants/{world.b}/integrations/entry-tokens/{t['id']}", headers=auth("b-owner")).status_code == 404
    assert client.get("/integrations/entry/v1/door-stations", headers=bearer(t["token"])).status_code == 200
    r = client.delete(f"/tenants/{world.a}/integrations/entry-tokens/{t['id']}", headers=auth("a-admin"))
    assert r.status_code == 200 and r.json()["revoked_at"]
    assert client.delete(f"/tenants/{world.a}/integrations/entry-tokens/{t['id']}", headers=auth("a-admin")).json()["revoked_at"] == r.json()["revoked_at"]
    assert client.get("/integrations/entry/v1/door-stations", headers=bearer(t["token"])).status_code == 401
    with SystemSession() as s:
        actions = [a.action for a in s.execute(select(AuditLog).where(AuditLog.action.like("integration.%"))).scalars()]
    assert actions == ["integration.token_made", "integration.token_revoked"]


def test_unknown_missing_and_other_scope_tokens(client, world):
    for h in ({}, {"Authorization": "Basic x"}, {"Authorization": "Bearer "}, bearer("pvx_entry_nope")):
        r = client.get("/integrations/entry/v1/door-stations", headers=h)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert client.get("/integrations/entry/v1/door-stations", headers=auth("a-owner")).status_code == 401      # a person's sign-in is not a token
    t = _token(client, world)
    with SystemSession() as s:
        s.get(IntegrationToken, uuid.UUID(t["id"])).scope = "vox:read"
        s.commit()
    assert client.get("/integrations/entry/v1/door-stations", headers=bearer(t["token"])).status_code == 403


def test_no_phone_system_or_nothing_published_means_no_stations(client, world):
    t = _token(client, world)
    body = client.get("/integrations/entry/v1/door-stations", headers=bearer(t["token"])).json()
    assert body == {"organization_id": world.a, "stations": []}
    _valid("door-stations", body)


def test_the_published_door_stations_with_their_sip_accounts(client, world, doors, eng):
    t = _token(client, world)
    body = client.get("/integrations/entry/v1/door-stations", headers=bearer(t["token"])).json()
    _valid("door-stations", body)
    ps = doors["ps"]
    with eng.connect() as c:
        pw = c.execute(text("select password from v_extensions where extension = '701'")).scalar()
        assert c.execute(text("select toll_allow from v_extensions where extension = '701'")).scalar() == "door:701"
    [st] = body["stations"]
    assert st["id"] == "front" and st["extension"] == "701" and st["site_id"] == world.a1 and st["name"] == "Front door"
    assert st["sip"] == {"server": ps.domain_name, "port": 5060, "transport": "udp", "username": "701", "password": pw, "outbound_proxy": None}
    with SystemSession() as s:
        s.get(PbxInstance, ps.instance_id).sip_access = {"port": 5061, "transport": "tls", "outbound_proxy": "sbc.example.net:5061"}
        s.commit()
    sip = client.get("/integrations/entry/v1/door-stations", headers=bearer(t["token"])).json()["stations"][0]["sip"]
    assert (sip["port"], sip["transport"], sip["outbound_proxy"]) == (5061, "tls", "sbc.example.net:5061")
    # A door added to the draft, not published: not listed (its intercom would have nothing to register to).
    draft = ps_row(world).draft
    draft["doors"]["side"] = {**draft["doors"]["front"], "extension": "702"}
    assert client.put(f"{doors['base']}/phone-system/draft", headers=auth("tech"), json={"document": draft}).status_code == 200
    assert [x["id"] for x in client.get("/integrations/entry/v1/door-stations", headers=bearer(t["token"])).json()["stations"]] == ["front"]
    other = client.post(f"/tenants/{world.b}/integrations/entry-tokens", headers=auth("b-owner"), json={}).json()
    assert client.get("/integrations/entry/v1/door-stations", headers=bearer(other["token"])).json() == {"organization_id": world.b, "stations": []}


def _epoch(s):
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def test_who_answered_a_door_call(client, world, doors, eng):
    t = bearer(_token(client, world)["token"])
    agent, ps = doors["agent"], doors["ps"]
    url = "/integrations/entry/v1/door-calls"
    at = "2026-11-14T15:02:20Z"
    T = _epoch(at)
    with eng.connect() as c:
        ext_id = c.execute(text("select extension_uuid from v_extensions where extension = '701'")).scalar()

    # In progress (no call record yet): from the door's log lines; answered by Ada, who is the directory's a-admin.
    agent.log = [{"call": CALL_A, "started": T - 8, "answered": T - 3, "user": doors["first"]["extension"], "dest": doors["first"]["extension"]}]
    body = client.get(url, headers=t, params={"station": "front", "at": at, "window_s": 60}).json()
    _valid("door-call", body)
    c = body["call"]
    assert c["id"] == CALL_A and c["ended_at"] is None and _epoch(c["started_at"]) == T - 8 and _epoch(c["answered_at"]) == T - 3
    assert c["answered_by"] == {"extension": doors["first"]["extension"], "name": doors["first"]["name"], "person_id": world.people["a-admin"]}
    assert agent.asked[-1] == (ps.domain_name, "701", T - 3600)

    # Ended a little before `at`: the call record gives the end; the log gives who.
    with eng.begin() as conn:
        conn.execute(text("insert into v_xml_cdr values (:u, :d, :x, :s, :a, :e)"),
                     {"u": CALL_A, "d": str(ps.domain_uuid), "x": ext_id, "s": T - 8, "a": T - 3, "e": T - 1})
    agent.log = [{"call": CALL_A, "started": T - 8, "answered": T - 3, "user": doors["first"]["extension"], "dest": doors["first"]["extension"]}]
    c = client.get(url, headers=t, params={"station": "front", "at": at, "window_s": 60}).json()["call"]
    assert c["id"] == CALL_A and _epoch(c["ended_at"]) == T - 1

    # Too long ago for the window: none. A call answered by an outside number: its last four digits only. Unanswered: nobody.
    agent.log = []
    assert client.get(url, headers=t, params={"station": "front", "at": "2026-11-14T15:10:00Z", "window_s": 30}).json()["call"] is None
    agent.log = [{"call": CALL_B, "started": T + 100, "answered": T + 104, "user": None, "dest": "7245550199"}]
    c = client.get(url, headers=t, params={"station": "front", "at": "2026-11-14T15:04:10Z", "window_s": 10}).json()["call"]
    assert c["answered_by"] == {"extension": "…0199", "name": "Outside number", "person_id": None} and "7245550199" not in json.dumps(c)
    agent.log = [{"call": CALL_B, "started": T + 100, "answered": None, "user": None, "dest": None}]
    c = client.get(url, headers=t, params={"station": "front", "at": "2026-11-14T15:04:10Z", "window_s": 10}).json()["call"]
    assert c["answered_by"] is None and c["answered_at"] is None
    agent.log = [{"call": CALL_B, "started": T + 100, "answered": T + 101, "user": "555", "dest": "555"}]   # an extension not in the document
    c = client.get(url, headers=t, params={"station": "front", "at": "2026-11-14T15:04:10Z", "window_s": 10}).json()["call"]
    assert c["answered_by"] == {"extension": "555", "name": "Extension 555", "person_id": None}
    # Only a call record (the log has rotated away): its times, and nobody named.
    with eng.begin() as conn:
        conn.execute(text("insert into v_xml_cdr values (:u, :d, :x, :s, :a, :e)"),
                     {"u": CALL_B, "d": str(ps.domain_uuid), "x": ext_id, "s": T + 200, "a": None, "e": T + 230})
    agent.log = []
    c = client.get(url, headers=t, params={"station": "front", "at": "2026-11-14T15:06:20Z", "window_s": 600}).json()["call"]
    assert c["id"] == CALL_B and c["answered_at"] is None and c["answered_by"] is None


def test_door_call_questions_that_are_refused(client, world, doors, eng):
    t = bearer(_token(client, world)["token"])
    url = "/integrations/entry/v1/door-calls"
    for params in ({"station": "front", "at": "yesterday"}, {"station": "front", "at": "2026-11-14T15:00:00+02:00"},
                   {"station": "front", "at": "2026-11-14T15:00:00Z", "window_s": 0}, {"station": "front", "at": "2026-11-14T15:00:00Z", "window_s": 601}):
        assert client.get(url, headers=t, params=params).status_code == 400, params
    assert client.get(url, headers=t, params={"station": "back", "at": "2026-11-14T15:00:00Z"}).status_code == 404
    other = bearer(client.post(f"/tenants/{world.b}/integrations/entry-tokens", headers=auth("b-owner"), json={}).json()["token"])
    assert client.get(url, headers=other, params={"station": "front", "at": "2026-11-14T15:00:00Z"}).status_code == 404    # another's door
    assert client.get(url, params={"station": "front", "at": "2026-11-14T15:00:00Z"}).status_code == 401

    def broken(*_a):
        raise RuntimeError("agent unreachable")
    doors["agent"].door_calls = broken
    r = client.get(url, headers=t, params={"station": "front", "at": "2026-11-14T15:00:00Z"})
    assert r.status_code == 503 and "unreachable" not in r.text
