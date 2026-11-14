"""GET /tenants/{id}/dashboard (app/routes/dashboard.py): who may see it, a site-limited person sees only their sites, the engine's call records,
voicemail and live view come through, a part the engine cannot give is named and the rest still shows, and the answer is cached briefly."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text

from app.db import SystemSession
from app.models import Site
from app.routes import dashboard as route
from app.routes import platform
from tests.api.conftest import auth
from tests.api.test_phone_system import FakeAgent, built, eng, ps_row   # noqa: F401 - fixtures


class LiveAgent(FakeAgent):
    available = True

    def __init__(self, eng):
        super().__init__(eng)
        self.view = {"registrations": [], "channels": [], "gateways": []}
        self.asked = 0

    def live(self, domain_name):
        self.asked += 1
        if self.view is None:
            raise RuntimeError("404 no such operation")
        return self.view


@pytest.fixture()
def board(client, world, built, eng):
    """Cedar Works published (the small-office template on the main site); the engine has call records and voicemail messages."""
    with eng.begin() as c:
        c.execute(text("create table if not exists v_xml_cdr (xml_cdr_uuid uuid primary key, domain_uuid uuid, direction text, leg text, "
                       "caller_id_number text, caller_destination text, destination_number text, start_epoch numeric, answer_epoch numeric, "
                       "end_epoch numeric, billsec numeric, status text, missed_call boolean, voicemail_message boolean, extension_uuid uuid, "
                       "hangup_cause text)"))
        c.execute(text("create table if not exists v_voicemail_messages (voicemail_message_uuid uuid primary key, domain_uuid uuid, "
                       "voicemail_uuid uuid, created_epoch numeric, message_status text)"))
    agent = LiveAgent(eng)
    conn = lambda i: (eng, agent)       # noqa: E731
    client.app.dependency_overrides[platform.get_connect] = lambda: conn
    assert client.post(f"{built}/phone-system/publish", headers=auth("tech")).status_code == 202
    with SystemSession() as s:
        from app.engine import service
        service.publish_queued(s, conn)
    ps = ps_row(world)
    assert ps.published_version == 1, ps.status
    route._cache.clear()
    return {"agent": agent, "ps": ps, "base": built, "eng": eng}


def _record(eng, ps, **kw):
    now = int(time.time())
    row = {"id": kw.pop("id"), "d": str(ps.domain_uuid), "dir": "inbound", "leg": "a", "cid": "4125550188", "cdest": "7245550100",
           "dest": "100", "s": now - 600, "a": now - 590, "e": now - 470, "b": 120, "st": "answered", "mc": False, "vm": False, "ext": None,
           "hc": "NORMAL_CLEARING"}
    row.update(kw)
    with eng.begin() as c:
        c.execute(text("insert into v_xml_cdr values (:id, :d, :dir, :leg, :cid, :cdest, :dest, :s, :a, :e, :b, :st, :mc, :vm, :ext, :hc)"), row)


def test_who_may_see_it(client, world, board):
    for who in ("a-owner", "a-admin", "tech", "a-admin-s1"):
        assert client.get(f"{board['base']}/dashboard", headers=auth(who)).status_code == 200, who
    for who in ("a-user", "b-owner", "stranger"):
        assert client.get(f"{board['base']}/dashboard", headers=auth(who)).status_code in (403, 404), who


def test_the_engines_records_and_live_view_reach_the_page(client, world, board):
    ps, eng = board["ps"], board["eng"]
    _record(eng, ps, id="0b5e8c1a-0000-4000-8000-0000000000c1")
    _record(eng, ps, id="0b5e8c1a-0000-4000-8000-0000000000c2", st="missed", b=0, a=None, mc=True)
    _record(eng, ps, id="0b5e8c1a-0000-4000-8000-0000000000c3", leg="b")                  # a B leg is not a second call
    with eng.begin() as c:
        ext100 = c.execute(text("select extension_uuid from v_extensions where extension = '100' and domain_uuid = :d"),
                           {"d": str(ps.domain_uuid)}).scalar()
        box = c.execute(text("select voicemail_uuid from v_voicemails where voicemail_id = '100' and domain_uuid = :d"), {"d": str(ps.domain_uuid)}).scalar()
        c.execute(text("insert into v_voicemail_messages values (gen_random_uuid(), :d, :v, :t, '')"), {"d": str(ps.domain_uuid), "v": box, "t": int(time.time())})
    assert ext100 is not None and box is not None
    board["agent"].view = {"registrations": [{"extension": "100", "agent": "Grandstream"}], "gateways": [],
                           "channels": [{"uuid": "x", "call": "x", "direction": "inbound", "gateway": False, "cid_num": "100", "dest": "101",
                                         "callstate": "ACTIVE", "presence": "100", "created": int(time.time()) - 30}]}
    r = client.get(f"{board['base']}/dashboard", headers=auth("a-admin"))
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["published"] is True and p["phone_system"] == {"status": "ready", "version": 1} and p["unavailable"] == []
    assert (p["today"]["calls"], p["today"]["missed"], p["today"]["in_progress"]) == (3, 1, 1)     # two records and the call in progress
    assert p["now"]["count"] == 1 and p["now"]["calls"][0]["kind"] == "internal"
    assert p["phones"]["online"] == 1 and p["phones"]["total"] >= 2
    assert p["voicemail"]["new"] == 1 and p["voicemail"]["boxes"][0]["box"] == "100"
    assert [n["number"] for n in p["numbers"]] == ["+17245550100"] and p["numbers"][0]["calls_today"] == 2
    assert p["sites"][0]["slug"] == "cw-main" and p["timezone"]


def test_a_site_by_slug_and_a_site_limited_person(client, world, board):
    with SystemSession() as s:
        a2 = s.execute(select(Site.slug).where(Site.id == world.a2)).scalar_one()
    assert client.get(f"{board['base']}/dashboard?site=cw-main", headers=auth("a-admin")).json()["site"] == world.a1
    assert client.get(f"{board['base']}/dashboard?site={a2}", headers=auth("a-admin-s1")).status_code == 404     # not one of their sites
    assert client.get(f"{board['base']}/dashboard?site=nope", headers=auth("a-admin")).status_code == 404
    mine = client.get(f"{board['base']}/dashboard", headers=auth("a-admin-s1")).json()
    assert [s["id"] for s in mine["sites"]] == [world.a1]


def test_without_the_live_view_or_voicemail_the_rest_still_shows(client, world, board):
    board["agent"].view = None
    with board["eng"].begin() as c:
        c.execute(text("drop table v_voicemail_messages"))
    p = client.get(f"{board['base']}/dashboard", headers=auth("a-admin")).json()
    assert p["unavailable"] == ["live", "voicemail"] and p["now"] is None and p["phones"] is None and p["today"]["calls"] == 0
    assert p["trunk"]["state"] == "unknown"


def test_cached_for_ten_seconds_per_choice(client, world, board):
    client.get(f"{board['base']}/dashboard", headers=auth("a-admin"))
    client.get(f"{board['base']}/dashboard", headers=auth("a-owner"))
    assert board["agent"].asked == 1
    client.get(f"{board['base']}/dashboard?site=cw-main", headers=auth("a-admin"))
    assert board["agent"].asked == 2


def test_nothing_published_yet(client, world, built):
    r = client.get(f"/tenants/{world.a}/dashboard", headers=auth("a-admin"))
    assert r.status_code == 200 and r.json()["published"] is False
    assert client.get(f"/tenants/{world.b}/dashboard", headers=auth("b-owner")).json()["detail"]["code"] == "no_phone_system"
