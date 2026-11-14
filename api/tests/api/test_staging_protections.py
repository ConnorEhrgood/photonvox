"""The protections version's rehearsal on staging (ARCHITECTURE §17 stage 5): staging's copy of the live domain (engine/staging/load_copy.py)
adopted, published as is, then protected exactly as planned for the live engine: ten-digit numbers to the carrier, the 911 address validated,
the hand-built routes in VOX_STAGING_RETIRE retired, PhotonVox's routes, gates and checks published through staging's vox-agent. Run only with
VOX_STAGING_PROTECT=1 (then engine/staging/protect-calls.sh places the calls); with VOX_STAGING_UNDO=1 the undo follows: version 1 published
again, and the engine's rows of the domain must be the takeover's exactly (then engine/staging/takeover-calls.sh). The domain comes from the
environment, never git.
No call to 911, 933 or 9911 is placed: the emergency route is read."""
from __future__ import annotations

import io
import json
import os
import re

import pytest
from sqlalchemy import create_engine, select, text

from app import manage
from app.db import SystemSession
from app.engine import fusionpbx, service, takeover
from app.models import PhoneSystem, PhoneSystemVersion
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
    takeover_rows = rows_of(eng, domain)
    op("set-format", "staging-copy", "htc=nanp10")
    assert retire, "VOX_STAGING_RETIRE is empty"
    dry = op("protect", world.a, "101", *retire)
    loc = client.post(f"/tenants/{world.a}/sites/{world.a1}/emergency-locations", headers=auth("a-owner"),
                      json={"key": "main", "street": "1 Church St", "city": "Hickory", "state": "PA", "zip": "15340"}).json()
    assert client.post(f"/platform/emergency-locations/{loc['id']}/validate", headers=auth("staff"), json={"ok": True}).status_code == 200
    assert op("protect-apply", world.a, *retire)["retire"] == retire
    published = op("publish", world.a, "the protections version")
    print("PROTECT-CHECKS " + json.dumps([(c["kind"], c["number"][-4:], c.get("got"), c["expect"], c["ok"]) for c in published["checks"]]))
    assert published["state"] == "ready", published["error"]
    assert all(c["ok"] for c in published["checks"]), [c for c in published["checks"] if not c["ok"]]
    assert not any("911" in c["number"] or "933" in c["number"] for c in published["checks"] if c["kind"] != "emergency, read")
    drift = op("drift", world.a)
    assert drift["changed"] == [] and drift["missing"] == [], drift
    with eng.connect() as c:
        left = sorted(c.execute(text("select dialplan_name from v_dialplans p join v_domains d using (domain_uuid) where d.domain_name = :n"),
                                {"n": domain}).scalars())
    undo = None
    if os.environ.get("VOX_STAGING_UNDO") == "1":
        # The undo: version 1 (the takeover's document) published again. Every row of the domain as the takeover left it; PhotonVox's routes gone.
        with SystemSession() as s:
            ps = s.execute(select(PhoneSystem)).scalar_one()
            v = service.queue(s, ps, s.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.number == 1)).scalar_one().document, None, "test", "undo")
            s.commit()
            assert service.publish_version(s, v.id, connect) == "ready"
        after = rows_of(eng, domain)
        assert after == takeover_rows, sorted(set(after.items()) ^ set(takeover_rows.items()))[:6]
        assert op("drift", world.a)["changed"] == []
        undo = {"rows_as_after_the_takeover": len(after)}
    eng.dispose()
    short = lambda s: re.sub(r"\d{10}", lambda m: "…" + m.group(0)[-4:], s)       # noqa: E731
    print("PROTECT-REHEARSAL " + json.dumps({
        "dry_run": {k: dry[k] for k in ("blocking_the_publish", "new_rows", "changed_rows", "changes", "new_dialplans", "retired")},
        "calls_out": {n: {k: short(v) for k, v in w.items()} for n, w in dry["calls_out"].items()},
        "checks": [(c["kind"], short(c["number"]), c["ok"]) for c in published["checks"]], "dialplans_now": [short(n) for n in left], "undo": undo}))


def rows_of(eng, domain):
    """Every row of the domain in the tables PhotonVox writes, without FusionPBX's bookkeeping columns: {"table:id": its fingerprint}."""
    with eng.connect() as c:
        export = takeover.read_domain(c, domain)
    return {f"{t}:{r[fusionpbx.KEYS[t]]}": json.dumps({k: v for k, v in r.items() if k not in fusionpbx.AUDIT}, sort_keys=True, default=str)
            for t in fusionpbx.TABLES for r in export["tables"].get(t) or []}
