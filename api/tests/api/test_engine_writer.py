"""The FusionPBX writer and upstreams (app/engine/writer.py, upstreams.py, publish.py) against a database shaped like FusionPBX's: tables made
from the builder's own columns in a schema of their own, plus the columns FusionPBX and phone users set that PhotonVox must leave alone.
The same code is proven against the real engine, with calls, on staging (engine/staging/prove-publish.sh)."""
from __future__ import annotations

import copy
import uuid

import pytest
from sqlalchemy import text

from app.engine import fusionpbx, publish, upstreams, writer
from app.engine.fusionpbx import KEYS, TABLES, Target
from tests.api import fpbx
from tests.unit.test_compiler import plan
from tests.unit.test_document import SAMPLE

PS = "0b5e8c1a-0000-4000-8000-000000000001"
DOMAIN = "0b5e8c1a-0000-4000-8000-0000000000d0"
OTHER = "0b5e8c1a-0000-4000-8000-0000000000d9"
INSTANCE = "0b5e8c1a-0000-4000-8000-00000000e000"
GW = {"htc": "0b5e8c1a-0000-4000-8000-0000000000a1", "upstream-b": "0b5e8c1a-0000-4000-8000-0000000000a2"}
TARGET = Target(PS, DOMAIN, GW)


@pytest.fixture()
def eng():
    e = fpbx.create()
    yield e
    fpbx.drop(e)


def count(c, table, domain=DOMAIN):
    return c.execute(text(f"select count(*) from {table} where domain_uuid = :d"), {"d": domain}).scalar()


def write(e, d=None, previous=()):
    with e.begin() as c:
        return writer.write(c, fusionpbx.build(plan(d), TARGET), DOMAIN, previous)


# ---- the domain ----

def test_a_missing_domain_is_created_and_an_existing_one_is_left_alone(eng):
    with eng.begin() as c:
        assert writer.ensure_domain(c, DOMAIN, "a.example") is True
        assert writer.ensure_domain(c, DOMAIN, "a.example") is False
        with pytest.raises(ValueError, match="not 'b.example'"):
            writer.ensure_domain(c, DOMAIN, "b.example")


# ---- writing ----

def test_the_first_publish_inserts_everything_with_new_secrets(eng):
    res = write(eng)
    b = fusionpbx.build(plan(), TARGET)
    assert res.inserted == sum(len(b.rows[t]) for t in TABLES) and res.updated == 0 and res.removed == 0
    assert set(res.new_secrets) == {"extension:100", "extension:101", "extension:102", "extension:200", "voicemail:100", "voicemail:101",
                                    "voicemail:102", "voicemail:200", "voicemail:9901"}
    assert len(res.new_secrets["extension:100"]) == 24 and res.new_secrets["extension:100"].isalnum()
    assert len(res.new_secrets["voicemail:100"]) == 4 and res.new_secrets["voicemail:100"].isdigit()
    assert res.manifest == b.manifest() and res.cache == sorted(set(b.cache))
    with eng.connect() as c:
        assert c.execute(text("select password from v_extensions where extension = '100'")).scalar() == res.new_secrets["extension:100"]
        assert c.execute(text("select insert_date is not null from v_dialplans limit 1")).scalar()
        assert c.execute(text("select destination_actions->0->>'destination_app' from v_destinations limit 1")).scalar() == "transfer"


def test_a_republish_updates_in_place_keeps_secrets_and_what_phone_users_set(eng):
    first = write(eng)
    with eng.begin() as c:
        c.execute(text("update v_extensions set forward_all_enabled = true, do_not_disturb = 'true' where extension = '100'"))
    again = write(eng, previous=first.manifest)
    assert again.inserted == 0 and again.removed == 0 and again.updated == first.inserted and again.new_secrets == {}
    with eng.connect() as c:
        row = c.execute(text("select password, forward_all_enabled, do_not_disturb, update_date is not null as upd from v_extensions "
                             "where extension = '100'")).first()
    assert row.password == first.new_secrets["extension:100"] and row.forward_all_enabled and row.do_not_disturb == "true" and row.upd


def test_what_left_the_plan_is_removed_with_its_cache_entries(eng):
    first = write(eng)
    d = copy.deepcopy(SAMPLE)
    d["users"].pop("u-cy")
    d["groups"]["annex"]["members"] = ["u-ada"]
    d["groups"]["annex"]["then"] = {"voicemail": "general"}
    d["numbers"].pop("+17245550123")
    d["users"]["u-pastor"].pop("direct_number")
    d["users"]["u-pastor"]["show"] = "site"
    d["menus"]["main"]["options"].pop("2")
    res = write(eng, d, previous=first.manifest)
    assert res.removed > 0
    assert "directory.200@k3x9q2.sip.photoninfra.xyz" in res.cache
    assert {"dialplan.public.+17245550123", "dialplan.public.17245550123", "dialplan.public.7245550123"} <= set(res.cache)
    with eng.connect() as c:
        assert c.execute(text("select count(*) from v_extensions where extension = '200'")).scalar() == 0
        assert c.execute(text("select count(*) from v_destinations where destination_number = '7245550123'")).scalar() == 0
        assert c.execute(text("select count(*) from v_dialplans where dialplan_name = '+17245550123'")).scalar() == 0
        assert c.execute(text("select count(*) from v_ivr_menu_options")).scalar() == 1
        assert count(c, "v_extensions") == 3


def test_another_domains_rows_are_never_changed_or_removed(eng):
    first = write(eng)
    victim = first.manifest[0]
    table, key = victim["table"], KEYS[victim["table"]]
    with eng.begin() as c:     # the same id in another domain (uuid5 makes it impossible; the writer must not rely on that)
        c.execute(text(f"update {table} set domain_uuid = :o where {key} = :u"), {"o": OTHER, "u": victim["uuid"]})
    with pytest.raises(ValueError, match="belongs to another domain"):
        write(eng, previous=first.manifest)
    b = fusionpbx.build(plan(), TARGET)
    b.rows[table] = [r for r in b.rows[table] if r[key] != victim["uuid"]]
    with eng.begin() as c:     # removal is scoped too: the previous manifest names the row, but it is in the other domain now
        writer.write(c, b, DOMAIN, previous=first.manifest)
        assert c.execute(text(f"select count(*) from {table} where {key} = :u and domain_uuid = :o"), {"u": victim["uuid"], "o": OTHER}).scalar() == 1


def test_a_build_row_outside_the_domain_is_refused_before_anything_is_written(eng):
    b = fusionpbx.build(plan(), TARGET)
    b.rows["v_dialplans"][3]["domain_uuid"] = OTHER
    with eng.begin() as c:
        with pytest.raises(ValueError, match="not in domain"):
            writer.write(c, b, DOMAIN)
        assert count(c, "v_extensions") == 0


def test_eavesdrop_and_intercept_are_switched_off_in_the_domain_only(eng):
    eaves = fusionpbx.FEATURE_APPS["eavesdrop"][0]
    with eng.begin() as c:
        for d in (DOMAIN, OTHER):
            c.execute(text("insert into v_dialplans (dialplan_uuid, domain_uuid, app_uuid, dialplan_name, dialplan_enabled) "
                           "values (:u, :d, :a, 'eavesdrop', true)"), {"u": str(uuid.uuid4()), "d": d, "a": eaves})
    write(eng)
    with eng.connect() as c:
        got = dict(c.execute(text("select domain_uuid::text, dialplan_enabled from v_dialplans where dialplan_name = 'eavesdrop'")).all())
    assert got == {DOMAIN: False, OTHER: True}


def test_new_secrets_have_the_right_shape():
    assert len(writer.new_secret("sip")) == 24 and writer.new_secret("pin").isdigit() and len(writer.new_secret("pin")) == 4
    assert writer.new_secret("sip") != writer.new_secret("sip")


# ---- the instance's upstreams ----

def test_upstreams_become_gateways_and_providers_entries_and_removed_ones_are_killed(eng):
    with eng.begin() as c:
        c.execute(text("insert into v_access_controls values ('0b5e8c1a-0000-4000-8000-0000000000ac', 'providers')"))
        c.execute(text("insert into v_access_control_nodes (access_control_node_uuid, access_control_uuid, node_type, node_cidr, node_description) "
                       "values ('0b5e8c1a-0000-4000-8000-0000000000ad', '0b5e8c1a-0000-4000-8000-0000000000ac', 'allow', '192.0.2.9/32', 'by hand')"))
        c.execute(text("insert into v_gateways (gateway_uuid, gateway, description) values ('0b5e8c1a-0000-4000-8000-0000000000ae', 'by-hand', 'mine')"))
        out = upstreams.write_upstreams(c, INSTANCE, "vox-staging", [
            upstreams.Upstream("htc", "198.51.100.5", ("198.51.100.0/28",)), upstreams.Upstream("b", "203.0.113.7:5080", ("203.0.113.7",))])
    assert set(out["gateways"]) == {"htc", "b"} and out["kill"] == [] and out["rescan"] == ["external"] and out["reload_acl"]
    assert out["cache"] == ["vox-staging.configuration.sofia.conf", "configuration.acl.conf"]
    with eng.begin() as c:
        out2 = upstreams.write_upstreams(c, INSTANCE, "vox-staging", [upstreams.Upstream("htc", "198.51.100.6", ("198.51.100.0/28",))])
        gws = dict(c.execute(text("select gateway, proxy from v_gateways")).all())
        nodes = sorted(r[0] for r in c.execute(text("select node_cidr from v_access_control_nodes")))
    assert out2["kill"] == [out["gateways"]["b"]]
    assert gws == {"htc": "198.51.100.6", "by-hand": None}                    # someone else's gateway is left alone
    assert nodes == ["192.0.2.9/32", "198.51.100.0/28"]                       # and so is their providers entry


def test_upstreams_need_the_providers_list(eng):
    with eng.begin() as c:
        with pytest.raises(ValueError, match="no providers"):
            upstreams.write_upstreams(c, INSTANCE, "h", [])


# ---- publishing ----

class FakeAgent:
    def __init__(self):
        self.calls = []

    def seed_domain(self):
        self.calls.append("seed")

    def clear_cache(self, keys):
        self.calls.append(("cache", len(keys)))

    def rescan(self, profiles, kill=()):
        self.calls.append("rescan")

    def reload_acl(self):
        self.calls.append("acl")


def test_publish_creates_and_seeds_the_domain_once_then_writes_and_clears_the_cache(eng):
    agent = FakeAgent()
    first = publish.publish(eng, agent, plan(), TARGET)
    assert agent.calls[0] == "seed" and agent.calls[1] == ("cache", len(first.cache))
    agent.calls.clear()
    publish.publish(eng, agent, plan(), TARGET, first.manifest)
    assert agent.calls == [("cache", len(first.cache))]
