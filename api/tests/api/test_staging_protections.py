"""The protections version's rehearsal on staging (ARCHITECTURE §17 stage 5): staging's copy of the live domain (engine/staging/load_copy.py)
adopted, published as is, then protected exactly as planned for the live engine: ten-digit numbers to the carrier, the 911 address validated,
the hand-built routes in VOX_STAGING_RETIRE retired, PhotonVox's routes, gates and checks published through staging's vox-agent. Run only with
VOX_STAGING_PROTECT=1 (engine/staging/protect-rehearsal.sh runs it, then places the calls); the domain comes from the environment, never git.
No call to 911, 933 or 9911 is placed: the emergency route is read."""
from __future__ import annotations

import io
import json
import os
import re

import pytest
from sqlalchemy import create_engine, text

from app import manage
from app.engine.agent import HttpAgent
from app.routes import platform
from tests.api.conftest import auth

pytestmark = pytest.mark.skipif(os.environ.get("VOX_STAGING_PROTECT") != "1", reason="needs staging's copy (engine/staging/protect-rehearsal.sh)")


def test_the_protections_version_on_the_copy(client, world):
    eng = create_engine(os.environ.get("VOX_STAGING_RW_URL") or os.environ["VOX_STAGING_DB_URL"], connect_args={"client_encoding": "utf8"})
    agent = HttpAgent(os.environ["VOX_STAGING_AGENT_URL"], os.environ["VOX_STAGING_AGENT_SECRET"])
    connect = lambda instance: (eng, agent)       # noqa: E731
    client.app.dependency_overrides[platform.get_connect] = lambda: connect
    domain, retire = os.environ["VOX_STAGING_DOMAIN"], [n for n in os.environ["VOX_STAGING_RETIRE"].split("|") if n]

    def op(*a):
        o = io.StringIO()
        assert manage.main(list(a), io.StringIO(), o, connect) == 0
        return json.loads(o.getvalue())

    r = client.post("/platform/instances", headers=auth("staff"), json={
        "name": "staging-copy", "hostname": "vox-staging", "database_url": os.environ["VOX_STAGING_DB_URL"], "upstreams": [],
        "own_gateways": {"htc": os.environ["VOX_STAGING_GATEWAY"]}, "routing": {"national": ["htc"]}, "emergency_upstream": "htc",
        "agent_url": os.environ["VOX_STAGING_AGENT_URL"], "agent_secret": os.environ["VOX_STAGING_AGENT_SECRET"]})
    assert r.status_code == 201, r.text
    assert client.post(f"/platform/instances/{r.json()['id']}/adopt", headers=auth("staff"),
                       json={"tenant_id": world.a, "site_id": world.a1, "domain": domain}).status_code == 201
    assert op("publish", world.a, "the takeover")["state"] == "ready"
    op("set-format", "staging-copy", "htc=nanp10")
    dry = op("protect", world.a, "101", *retire)
    loc = client.post(f"/tenants/{world.a}/sites/{world.a1}/emergency-locations", headers=auth("a-owner"),
                      json={"key": "main", "street": "1 Church St", "city": "Hickory", "state": "PA", "zip": "15340"}).json()
    assert client.post(f"/platform/emergency-locations/{loc['id']}/validate", headers=auth("staff"), json={"ok": True}).status_code == 200
    op("protect-apply", world.a, *retire)
    published = op("publish", world.a, "the protections version")
    assert published["state"] == "ready", published
    assert all(c["ok"] for c in published["checks"]), [c for c in published["checks"] if not c["ok"]]
    assert not any("911" in c["number"] or "933" in c["number"] for c in published["checks"] if c["kind"] != "emergency, read")
    drift = op("drift", world.a)
    assert drift["changed"] == [] and drift["missing"] == [], drift
    with eng.connect() as c:
        left = sorted(c.execute(text("select dialplan_name from v_dialplans p join v_domains d using (domain_uuid) where d.domain_name = :n"),
                                {"n": domain}).scalars())
    eng.dispose()
    short = lambda s: re.sub(r"\d{10}", lambda m: "…" + m.group(0)[-4:], s)       # noqa: E731
    print("PROTECT-REHEARSAL " + json.dumps({
        "dry_run": {k: dry[k] for k in ("blocking_the_publish", "new_rows", "changed_rows", "changes", "new_dialplans", "retired", "retired_rows")},
        "calls_out": {n: {k: short(v) for k, v in w.items()} for n, w in dry["calls_out"].items()},
        "checks": [(c["kind"], short(c["number"]), c["ok"]) for c in published["checks"]], "dialplans_now": [short(n) for n in left]}))
