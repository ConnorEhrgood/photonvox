"""The customer dashboard's data (app/dashboard.py): GET /tenants/{id}/dashboard?site=<slug>. For anyone who may view the phone system; a
person limited to some sites sees only those (and the whole organization means their sites). Cached ten seconds per organization and site
choice, so a wall of open dashboards asks the engine once."""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import dashboard
from app.db import get_db
from app.deps import Ctx, require
from app.document.model import PhoneSystem as Document
from app.engine import service, upstreams
from app.models import EmergencyLocation, PhoneSystem, PhoneSystemVersion
from app.routes.phone_system import VIEW, _instance
from app.routes.platform import get_connect
from app.routes.tenants import visible_sites

router = APIRouter(prefix="/tenants/{tenant_id}")
CACHE_S = 10.0
_cache: Dict[Tuple[str, str, str], Tuple[float, Dict[str, Any]]] = {}
_lock = threading.Lock()


def _address(a: Dict[str, Any]) -> str:
    street = " ".join(x for x in (a.get("street"), a.get("unit")) if x)
    tail = " ".join(x for x in (a.get("state"), a.get("zip")) if x)
    return ", ".join(x for x in (street, a.get("city"), tail) if x)


@router.get("/dashboard")
def get_dashboard(site: Optional[str] = Query(None, max_length=80), ctx: Ctx = Depends(require(VIEW)), db: Session = Depends(get_db),
                  connect: service.Connect = Depends(get_connect)) -> Dict[str, Any]:
    sites = [{"id": str(s.id), "slug": s.slug, "name": s.name, "timezone": s.timezone or "America/New_York"} for s in visible_sites(db, ctx)]
    chosen: Optional[str] = None
    if site:
        chosen = next((s["id"] for s in sites if site in (s["slug"], s["id"])), None)
        if chosen is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "no_site", "detail": "No such site."})
    ps = db.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == ctx.tenant_id)).scalar_one_or_none()
    if ps is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "no_phone_system", "detail": "This organization has no phone system yet."})
    if ps.published_version is None:
        return {"published": False, "sites": [{"id": s["id"], "slug": s["slug"], "name": s["name"]} for s in sites], "site": chosen}
    key = (str(ctx.tenant_id), chosen or "", ",".join(sorted(s["id"] for s in sites)))
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_S:
            return hit[1]
    v = db.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.phone_system_id == ps.id,
                                                    PhoneSystemVersion.number == ps.published_version)).scalar_one()
    doc = Document.model_validate(v.document)
    instance = _instance(ps)
    carrier = {upstreams.gateway_uuid(str(instance.id), u["key"]) for u in instance.upstreams} | set((instance.own_gateways or {}).values())
    address = {}
    for loc in db.execute(select(EmergencyLocation).where(EmergencyLocation.tenant_id == ctx.tenant_id)).scalars():
        for sid, s in doc.sites.items():
            if str(loc.site_id) == sid and loc.key == s.emergency_location:
                address[sid] = _address(loc.address or {})
    now = datetime.now(timezone.utc)
    eng, agent = connect(instance)
    try:
        raw = dashboard.gather(eng, agent, ps.domain_name, str(ps.domain_uuid), now)
    finally:
        eng.dispose()
    out = dashboard.compute(doc, sites, chosen, raw, now, address, carrier)
    out.update({"published": True, "phone_system": {"status": ps.status, "version": ps.published_version}})
    with _lock:
        _cache[key] = (time.monotonic(), out)
        for k in [k for k, (t, _v) in _cache.items() if time.monotonic() - t > 60]:
            del _cache[k]
    return out
