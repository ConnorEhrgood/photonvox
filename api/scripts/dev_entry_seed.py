"""Seed the dev PhotonVox (scripts/dev-stack.sh seed) for PhotonEntry's integration tests. Runs inside the dev API container, given URL (the
staging engine's adapter login) and SECRET (staging's vox-agent) by the caller, never on a command line. Idempotent: run again, it republishes.

One test organization with one site, two people, a ring group, one number (fictional, 555), and two doors on the staging engine (CT 610):
"front" (extension 150) rings the front desk, "side" (151) rings the lobby group. Published through vox-agent with the post-publish check.
Prints the ids and a new PhotonEntry token (shown once; earlier dev tokens stay until revoked). Never production."""
import hashlib
import json
import secrets
import uuid

from sqlalchemy import select

from app import crypto
from app.db import SystemSession
from app.engine import service
from app.models import EmergencyLocation, HeldNumber, IntegrationToken, PbxInstance, PhoneSystem, PhoneSystemVersion, Site, Tenant, utcnow

ORG = uuid.UUID("e0e0e0e0-0000-4000-8000-0000000000a1")
SITE = uuid.UUID("e0e0e0e0-0000-4000-8000-0000000000b1")
INSTANCE = uuid.UUID("7a6b0000-0000-4000-8000-000000000001")      # the staging instance's id, so its gateway rows on CT 610 are the same ones
DOMAIN, DOMAIN_UUID = "entry.vox.test", uuid.UUID("e0e0e0e0-0000-4000-8000-0000000000d1")
NUMBER = "+12125550500"
S = str(SITE)
DOC = {
    "version": 1,
    "sites": {S: {"emergency_location": "main", "emergency_number": NUMBER, "caller_id": NUMBER}},
    "numbers": {NUMBER: {"site": S, "open": {"user": "u-desk"}}},
    "users": {"u-desk": {"name": "Front desk", "site": S, "extension": "100", "email": "frontdesk@example.test"},
              "u-guard": {"name": "Guard station", "site": S, "extension": "101"}},
    "groups": {"lobby": {"members": ["u-desk", "u-guard"], "strategy": "simultaneous", "ring_seconds": 25}},
    "doors": {"front": {"name": "Front door", "site": S, "extension": "150", "open": {"user": "u-desk"}},
              "side": {"name": "Side door", "site": S, "extension": "151", "open": {"group": "lobby"}}},
}

with SystemSession() as s:
    s.merge(Tenant(id=ORG, name="PhotonEntry test (dev)", slug="photonentry-test", status="active", products=["vox"]))
    s.merge(Site(id=SITE, tenant_id=ORG, slug="photonentry-test-main", name="Main", timezone="America/New_York", status="active"))
    s.merge(HeldNumber(number=NUMBER, tenant_id=ORG, carrier="htc", note="dev: PhotonEntry tests (fictional 555 number)"))
    loc = s.execute(select(EmergencyLocation).where(EmergencyLocation.site_id == SITE, EmergencyLocation.key == "main")).scalar_one_or_none()
    if loc is None:
        s.add(EmergencyLocation(tenant_id=ORG, site_id=SITE, key="main", status="validated", validated_by_label="dev seed", validated_at=utcnow(),
                                address={"street": "1 Test St", "city": "Pittsburgh", "state": "PA", "zip": "15222"}))
    i = s.get(PbxInstance, INSTANCE) or PbxInstance(id=INSTANCE, name="staging", hostname="vox-staging")
    i.database_url_sealed, i.agent, i.agent_secret_sealed = crypto.seal(URL), {"kind": "http", "url": "http://10.10.0.60:8780"}, crypto.seal(SECRET)  # noqa: F821
    i.upstreams = [{"key": "sipp-upstream", "proxy": "10.10.0.80:5071", "addresses": ["10.10.0.80/32"]}]
    i.routing, i.emergency_upstream = {"national": ["sipp-upstream"]}, "sipp-upstream"
    # The test domain does not resolve: an intercom on the bench sends its SIP straight to the staging engine.
    i.sip_access = {"port": 5060, "transport": "udp", "outbound_proxy": "10.10.0.60:5060"}
    s.merge(i)
    s.flush()
    ps = s.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == ORG)).scalar_one_or_none()
    if ps is None:
        ps = PhoneSystem(tenant_id=ORG, instance_id=INSTANCE, domain_name=DOMAIN, domain_uuid=DOMAIN_UUID, draft=DOC)
        s.add(ps)
    ps.draft = DOC
    s.flush()
    v = service.queue(s, ps, DOC, None, "dev seed", "dev: PhotonEntry test doors")
    s.commit()
    state = service.publish_version(s, v.id)
    v = s.get(PhoneSystemVersion, v.id)
    token = "pvx_entry_" + secrets.token_urlsafe(32)
    s.add(IntegrationToken(tenant_id=ORG, scope="vox:entry", label="PhotonEntry (dev)", token_hash=hashlib.sha256(token.encode()).hexdigest(),
                           hint=token[-4:]))
    s.commit()
    print(json.dumps({"organization_id": str(ORG), "site_id": str(SITE), "domain": DOMAIN, "doors": {"front": "150", "side": "151"},
                      "version": v.number, "state": state, "error": v.error,
                      "checks": [(c["kind"], c["number"][-4:], c["ok"]) for c in (v.check or {}).get("results", [])], "token": token}))
