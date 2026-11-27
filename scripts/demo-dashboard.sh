#!/usr/bin/env bash
# The demo's dashboard as the dev PhotonVox on LXC 800 computes it (docs/DEMO.md §3), written as the answers file web/scripts/dashboard-shots.mjs
# reads: the whole organization and each site. Read only: the same reading and computation as GET /tenants/<id>/dashboard, run in the dev stack's
# api container. Fictional data only (the demo), so the output may be shown to anyone.
#   scripts/demo-dashboard.sh > answers.json && (cd web && node scripts/dashboard-shots.mjs answers.json <output dir>)
set -euo pipefail
ssh lxc800 "cd /root/vox-dev && docker compose -f docker-compose.yml -f docker-compose.dev-lxc.yml exec -T api python -" <<'EOF'
import json, uuid
from datetime import datetime, timezone
from sqlalchemy import select
from app import dashboard, demo
from app.db import SystemSession
from app.document.model import PhoneSystem as Document
from app.engine import service, upstreams
from app.models import EmergencyLocation, PbxInstance, PhoneSystem, PhoneSystemVersion, Site, Tenant
from app.routes.dashboard import _address

TENANT = uuid.UUID(demo.ORG)
with SystemSession() as s:
    t = s.get(Tenant, TENANT)
    assert t is not None and t.demo, "only the demo"
    ps = s.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == TENANT)).scalar_one()
    v = s.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.phone_system_id == ps.id,
                                                   PhoneSystemVersion.number == ps.published_version)).scalar_one()
    doc = Document.model_validate(v.document)
    sites = [{"id": str(x.id), "slug": x.slug, "name": x.name, "timezone": x.timezone or "America/New_York"} for x in
             s.execute(select(Site).where(Site.tenant_id == TENANT, Site.status == "active").order_by(Site.name)).scalars()]
    instance = s.get(PbxInstance, ps.instance_id)
    carrier = {upstreams.gateway_uuid(str(instance.id), u["key"]) for u in instance.upstreams} | set((instance.own_gateways or {}).values())
    address = {}
    for loc in s.execute(select(EmergencyLocation).where(EmergencyLocation.tenant_id == TENANT)).scalars():
        for sid, site in doc.sites.items():
            if str(loc.site_id) == sid and loc.key == site.emergency_location:
                address[sid] = _address(loc.address or {})
    now = datetime.now(timezone.utc)
    eng, agent = service.connect(instance)
    try:
        raw = dashboard.gather(eng, agent, ps.domain_name, str(ps.domain_uuid), now)
    finally:
        eng.dispose()
    pages = {}
    for site in [None] + sites:
        p = dashboard.compute(doc, sites, site and site["id"], raw, now, address, carrier)
        p.update({"published": True, "phone_system": {"status": ps.status, "version": ps.published_version}})
        pages[site["slug"] if site else ""] = p
    print(json.dumps({"org": {"name": t.name, "slug": t.slug}, "pages": pages}))
EOF
