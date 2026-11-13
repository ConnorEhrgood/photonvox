from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access
from app.access import Grant
from app.db import get_db
from app.deps import Who, current_person
from app.models import Access, Tenant, utcnow

router = APIRouter()


def scope_json(grant: Grant) -> Dict[str, Any]:
    return {"all": True} if grant.scope_all else {"sites": sorted(str(s) for s in grant.site_ids)}


@router.get("/me")
def me(who: Who = Depends(current_person), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Who you are and, for each organization where you have live access, what you may do there. The web app gates its buttons on `capabilities`;
    the API checks again on every request. Partner staff (integrators) see every customer of their partner here, with `source: partner`."""
    now = utcnow()
    tenants: List[Dict[str, Any]] = []
    rows = db.execute(select(Access, Tenant).join(Tenant, Tenant.id == Access.tenant_id).where(Access.person_id == who.id).order_by(Tenant.name)).all()
    for a, t in rows:
        grant = Grant.from_row(a)
        if not access.is_active(grant, now) or t.status == "removed":
            continue
        tenants.append({
            "id": str(t.id), "name": t.name, "status": t.status, "partner_id": str(t.partner_id) if t.partner_id else None, "role": grant.role,
            "scope": scope_json(grant), "source": grant.source, "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
            "capabilities": sorted(access.capabilities(grant, now)),
        })
    return {"id": str(who.id), "name": who.name, "email": who.email, "is_staff": who.is_staff, "is_platform_admin": who.is_platform_admin,
            "tenants": tenants}
