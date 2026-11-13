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
    eng = create_engine(os.environ["VOX_STAGING_DB_URL"], connect_args={"client_encoding": "utf8"})
    connect = lambda instance: (eng, service.NoAgent())          # noqa: E731 - the live engine has no vox-agent: neither does this run
    client.app.dependency_overrides[platform.get_connect] = lambda: connect
    domain = os.environ["VOX_STAGING_DOMAIN"]
    with eng.connect() as c:
        d = str(c.execute(text("select domain_uuid from v_domains where domain_name = :n"), {"n": domain}).scalar_one())
    before = snapshot(eng, d)
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
    after = snapshot(eng, d)
    assert after == before, [t for t in TABLES if after[t] != before[t]]
    with SystemSession() as s:
        service.check_all_drift(s, connect)
        ps = s.execute(select(PhoneSystem)).scalar_one()
        drift = ps.drift
    assert ps.status == "ready" and drift["changed"] == [] and drift["missing"] == [] and drift["hand_built_changed"] == [], drift
    eng.dispose()
    print("TAKEOVER-REHEARSAL " + json.dumps({"objects": adopted["objects"], "rows": adopted["rows"], "extras": adopted["extras"],
                                               "understanding": len(adopted["understanding"]), "decide": [i["what"] for i in adopted["report"] if i["outcome"] == "decide"],
                                               "rows_on_engine": {t: len(before[t]) for t in TABLES if before[t]}, "identical_after_publish": after == before,
                                               "drift": ps.status}))
