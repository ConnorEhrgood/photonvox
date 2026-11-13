"""Step 7's rehearsal on staging (ARCHITECTURE §17.5): the takeover of staging's copy of a live domain (engine/staging/load_copy.py) through the
API and the worker, exactly as it will run on the live engine: an instance with its own gateway and no vox-agent, the adoption, the first
publish. Every row of the domain on the engine must be the same afterwards, to the last date. Run only with VOX_STAGING_TAKEOVER=1
(engine/staging/takeover-rehearsal.sh runs it); the domain and its gateway come from the environment, never from git."""
from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import create_engine, select, text

from app.db import SystemSession
from app.engine import service
from app.models import PhoneSystem
from app.routes import platform
from tests.api.conftest import auth

pytestmark = pytest.mark.skipif(os.environ.get("VOX_STAGING_TAKEOVER") != "1", reason="needs staging's copy (engine/staging/takeover-rehearsal.sh)")
TABLES = ("v_extensions", "v_voicemails", "v_destinations", "v_dialplans", "v_dialplan_details", "v_ivr_menus", "v_ivr_menu_options", "v_ring_groups",
          "v_ring_group_destinations")


def snapshot(eng, domain_uuid):
    with eng.connect() as c:
        return {t: sorted(json.dumps(dict(r), sort_keys=True, default=str) for r in c.execute(text(f"select * from {t} where domain_uuid = :d"), {"d": domain_uuid}).mappings())
                for t in TABLES}


def test_the_takeover_of_the_copy_changes_nothing_on_the_engine(client, world):
    # PhotonVox logs in as the write role, as it will on the live engine (VOX_STAGING_RW_URL); the snapshots read as staging's adapter.
    admin = create_engine(os.environ["VOX_STAGING_DB_URL"], connect_args={"client_encoding": "utf8"})
    eng = create_engine(os.environ.get("VOX_STAGING_RW_URL") or os.environ["VOX_STAGING_DB_URL"], connect_args={"client_encoding": "utf8"})
    connect = lambda instance: (eng, service.NoAgent())          # noqa: E731 - the live engine has no vox-agent: neither does this run
    client.app.dependency_overrides[platform.get_connect] = lambda: connect
    domain = os.environ["VOX_STAGING_DOMAIN"]
    with admin.connect() as c:
        d = str(c.execute(text("select domain_uuid from v_domains where domain_name = :n"), {"n": domain}).scalar_one())
    before = snapshot(admin, d)
    r = client.post("/platform/instances", headers=auth("staff"), json={
        "name": "staging-copy", "hostname": "vox-staging", "database_url": os.environ["VOX_STAGING_DB_URL"], "upstreams": [],
        "own_gateways": {"htc": os.environ["VOX_STAGING_GATEWAY"]}, "routing": {"national": ["htc"]}, "emergency_upstream": "htc"})
    assert r.status_code == 201, r.text
    r = client.post(f"/platform/instances/{r.json()['id']}/adopt", headers=auth("staff"), json={"tenant_id": world.a, "site_id": world.a1, "domain": domain})
    assert r.status_code == 201, r.text
    adopted = r.json()
    assert client.post(f"/tenants/{world.a}/phone-system/publish", headers=auth("a-owner")).status_code == 202
    with SystemSession() as s:
        assert service.publish_queued(s, connect) == 1
    v = client.get(f"/tenants/{world.a}/phone-system/versions", headers=auth("a-owner")).json()[0]
    assert v["state"] == "ready", v
    after = snapshot(admin, d)
    assert after == before, [t for t in TABLES if after[t] != before[t]]
    with SystemSession() as s:
        service.check_all_drift(s, connect)
        ps = s.execute(select(PhoneSystem)).scalar_one()
        drift = ps.drift
    assert ps.status == "ready" and drift["changed"] == [] and drift["missing"] == [] and drift["hand_built_changed"] == [], drift
    # A hand edit put back, through the write role and staging's vox-agent (the live engine will need its own for this): a real write.
    wrote = None
    if os.environ.get("VOX_STAGING_AGENT_URL") and os.environ.get("VOX_STAGING_AGENT_SECRET"):
        from app.engine.agent import HttpAgent
        with admin.begin() as c:
            c.execute(text("update v_extensions set effective_caller_id_name = 'Hand Edit' where domain_uuid = :d and extension = '101'"), {"d": d})
        agent = HttpAgent(os.environ["VOX_STAGING_AGENT_URL"], os.environ["VOX_STAGING_AGENT_SECRET"])
        with_agent = lambda instance: (eng, agent)          # noqa: E731
        assert client.post(f"/tenants/{world.a}/phone-system/publish", headers=auth("a-owner")).status_code == 202
        with SystemSession() as s:
            assert service.publish_queued(s, with_agent) == 1
        v2 = client.get(f"/tenants/{world.a}/phone-system/versions", headers=auth("a-owner")).json()[0]
        assert v2["state"] == "ready", v2
        with admin.connect() as c:
            name = c.execute(text("select effective_caller_id_name from v_extensions where domain_uuid = :d and extension = '101'"), {"d": d}).scalar()
        restored = {t: v for t, v in snapshot(admin, d).items() if t != "v_extensions"}
        assert name != "Hand Edit" and restored == {t: v for t, v in before.items() if t != "v_extensions"}
        wrote = True
    eng.dispose()
    admin.dispose()
    print("TAKEOVER-REHEARSAL " + json.dumps({"objects": adopted["objects"], "rows": adopted["rows"], "extras": adopted["extras"],
                                               "understanding": len(adopted["understanding"]), "decide": [i["what"] for i in adopted["report"] if i["outcome"] == "decide"],
                                               "rows_on_engine": {t: len(before[t]) for t in TABLES if before[t]}, "identical_after_publish": after == before,
                                               "drift": ps.status, "hand_edit_put_back_as_write_role": wrote}))
