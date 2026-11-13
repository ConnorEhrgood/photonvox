"""BUILD-GUIDE Step 3's build test, against the real staging engine (run only with VOX_STAGING_E2E=1; engine/staging/build-test.sh runs it,
then proves the result with SIPp calls). Everything an integrator does goes through the API exactly as the web app's screens send it:
the wizard (a site and its 911 address, the main number and a template, 30 people pasted), the second site (Sites), three more numbers
(Numbers), a ring group for the second site (Call flows), Photon staff validating both addresses, Publish. The worker then publishes to the
engine through vox-agent and runs the post-publish check. Then someone edits the engine by hand: the drift check must find it and the next
publish must put PhotonVox's version back."""
from __future__ import annotations

import json
import os
import time
import uuid

import pytest
from sqlalchemy import create_engine, select, text

from app import crypto
from app.db import SystemSession
from app.engine import service
from app.models import PbxInstance, PhoneSystem, PhoneSystemVersion
from tests.api.conftest import auth

pytestmark = pytest.mark.skipif(os.environ.get("VOX_STAGING_E2E") != "1", reason="needs the staging engine (engine/staging/build-test.sh)")

INSTANCE = uuid.UUID("7a6b0000-0000-4000-8000-000000000001")       # the staging instance, as the harness names it
DOMAIN, DOMAIN_UUID = "build.vox.test", uuid.UUID("7a6b0000-0000-4000-8000-0000000000b1")
PHONE_SYSTEM = uuid.UUID("7a6b0000-0000-4000-8000-0000000000b2")    # fixed too: every row's id derives from it, so a rerun updates in place
MAIN, ANNEX, DIRECT, MAILBOX = "+12125550400", "+12125550401", "+12125550402", "+12125550403"


def people() -> str:
    rows = ["Name,Ext,Email,Direct number,Site"]
    for i in range(30):
        site = "Annex" if i >= 20 else "Main office"
        rows.append(f"Person {i:02d},,person{i:02d}@example.test,{'(212) 555-0402' if i == 2 else ''},{site}")
    return "\n".join(rows)


def test_build_publish_check_and_hand_edit_on_staging(client, world):
    steps = []
    t0 = time.monotonic()

    def call(method, path, who="tech", **kw):
        r = client.request(method, path, headers=auth(who), **kw)
        assert r.status_code < 300, (path, r.status_code, r.text)
        steps.append(path)
        return r.json()

    # Photon's side, once: the staging instance and its own settings (upstream: SIPp on LXC 800; mail: Mailpit there).
    with SystemSession() as s:
        s.add(PbxInstance(id=INSTANCE, name="staging", hostname="vox-staging", database_url_sealed=crypto.seal(os.environ["VOX_STAGING_DB_URL"]),
                          agent={"kind": "http", "url": os.environ["VOX_STAGING_AGENT_URL"]}, agent_secret_sealed=crypto.seal(os.environ["VOX_STAGING_AGENT_SECRET"]),
                          upstreams=[{"key": "sipp-upstream", "proxy": "10.10.0.80:5071", "addresses": ["10.10.0.80/32"]}],
                          routing={"national": ["sipp-upstream"]}, emergency_upstream="sipp-upstream",
                          email={"host": "10.10.0.80", "port": 2525, "secure": "none", "from": "voicemail@vox-staging.test"}))
        s.commit()
        service.apply_instance(s.get(PbxInstance, INSTANCE))

    a = f"/tenants/{world.a}"
    for n in (MAIN, ANNEX, DIRECT, MAILBOX):     # Photon assigns the organization's numbers (security review C2)
        call("PUT", f"/platform/numbers/{n}", who="staff", json={"tenant_id": world.a})
    # The wizard.
    call("POST", f"{a}/phone-system")
    with SystemSession() as s:      # one fixed domain on staging, so each run republishes it instead of adding another
        ps = s.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == uuid.UUID(world.a))).scalar_one()
        ps.domain_name, ps.domain_uuid = DOMAIN, DOMAIN_UUID
        s.flush()
        s.execute(text("update phone_system set id = :fixed where id = :id"), {"fixed": PHONE_SYSTEM, "id": ps.id})
        s.commit()
    call("GET", f"{a}/emergency")
    loc1 = call("POST", f"{a}/sites/{world.a1}/emergency-locations", json={"key": "main", "street": "100 Main St", "city": "Asheville", "state": "NC", "zip": "28801"})
    preview = call("POST", f"{a}/phone-system/import", json={"text": people(), "site_id": world.a1})
    assert preview["ready"] == 29 and preview["rows"][2]["problems"] == ["+12125550402 is not one of the organization's numbers"]
    call("POST", f"{a}/phone-system/draft/template", json={"template": "front-desk-menu", "site_id": world.a1, "location": "main",
                                                           "main_number": MAIN, "users": people()})
    # Numbers, the second site, its ring group (Numbers, Sites and Call flows send the whole draft).
    d = call("GET", f"{a}/phone-system")["draft"]
    annex_people = sorted(k for k, u in d["users"].items() if u["site"] == world.a2)
    d["numbers"][ANNEX] = {"site": world.a2, "open": {"group": "annex"}}
    d["numbers"][DIRECT] = {"site": world.a1, "open": {"user": "u-person-02"}}
    d["numbers"][MAILBOX] = {"site": world.a1, "open": {"voicemail": "general"}}
    d["groups"]["annex"] = {"members": annex_people, "strategy": "simultaneous", "ring_seconds": 20, "then": {"voicemail": "general"}}
    call("PUT", f"{a}/phone-system/draft", json={"document": d})
    loc2 = call("POST", f"{a}/sites/{world.a2}/emergency-locations", json={"key": "main", "street": "2 Mill Road", "city": "Asheville", "state": "NC", "zip": "28801"})
    d["sites"][world.a2] = {"emergency_location": "main", "emergency_number": ANNEX, "caller_id": ANNEX, "hours": "office"}
    # The person who did not import (their direct number was not held yet) is added now that it is, as Users → Import would.
    call("POST", f"{a}/phone-system/import", json={"text": "Person 02,,person02@example.test,(212) 555-0402,Main office", "site_id": world.a1, "apply": False})
    d["users"]["u-person-02"] = {"name": "Person 02", "site": world.a1, "extension": "130", "email": "person02@example.test",
                                 "direct_number": DIRECT, "show": "direct"}
    summary = call("PUT", f"{a}/phone-system/draft", json={"document": d})
    integrator_s = time.monotonic() - t0
    assert [p["code"] for p in summary["problems"]] == ["emergency_location_unvalidated"] * 2
    # Photon staff check both addresses (the R1 queue).
    for loc in (loc1, loc2):
        call("POST", f"/platform/emergency-locations/{loc['id']}/validate", who="staff", json={"ok": True})
    assert call("GET", f"{a}/phone-system")["problems"] == []
    v = call("POST", f"{a}/phone-system/publish")
    assert v["number"] == 1 and len(d["users"]) == 30 and len(d["numbers"]) == 4

    # The worker: publish to the engine through vox-agent, then the check's synthetic calls.
    t1 = time.monotonic()
    with SystemSession() as s:
        assert service.publish_queued(s) == 1
    publish_s = time.monotonic() - t1
    got = client.get(f"{a}/phone-system/versions", headers=auth("tech")).json()[0]
    assert got["state"] == "ready", got
    assert got["checks"]["passed"] == got["checks"]["total"] == 4 + 2 + 1         # four numbers; 911 and 933 (no outside prefix); a premium number

    # Someone edits the engine by hand.
    engine = create_engine(os.environ["VOX_STAGING_DB_URL"], connect_args={"client_encoding": "utf8"})
    with engine.begin() as c:
        c.execute(text("update v_extensions set effective_caller_id_name = 'Hand Edit' where extension = '100' and domain_uuid = :d"), {"d": str(DOMAIN_UUID)})
    with SystemSession() as s:
        drift = service.check_drift(s, s.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == uuid.UUID(world.a))).scalar_one())
    assert [(x["table"], x["columns"]) for x in drift["changed"]] == [("v_extensions", ["effective_caller_id_name"])]
    assert client.get(f"{a}/phone-system", headers=auth("tech")).json()["status"] == "changed"
    call("POST", f"{a}/phone-system/publish")
    with SystemSession() as s:
        service.publish_queued(s)
        assert service.check_drift(s, s.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == uuid.UUID(world.a))).scalar_one())["changed"] == []
    with engine.connect() as c:
        assert c.execute(text("select effective_caller_id_name from v_extensions where extension = '100' and domain_uuid = :d"),
                         {"d": str(DOMAIN_UUID)}).scalar() == "Person 00"
    with SystemSession() as s:
        v2 = s.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.number == 2)).scalar_one()
        assert v2.state == "ready", (v2.error, [r for r in v2.check.get("results", []) if not r["ok"]])
    engine.dispose()

    print("BUILD-TEST " + json.dumps({
        "domain": DOMAIN, "main": MAIN, "annex": ANNEX, "direct": DIRECT, "mailbox": MAILBOX, "users": len(d["users"]),
        "annex_extensions": sorted(d["users"][k]["extension"] for k in annex_people), "direct_extension": "130",
        "requests": len(steps), "integrator_api_seconds": round(integrator_s, 1), "publish_and_check_seconds": round(publish_s, 1)}))
