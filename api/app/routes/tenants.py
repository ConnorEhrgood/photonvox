from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access
from app.access import Grant
from app.db import get_db
from app.deps import Ctx, require, tenant_ctx
from app.models import Access, Person, Site, Tenant
from app.roles import ROLES
from app.routes.me import scope_json

router = APIRouter(prefix="/tenants/{tenant_id}")

# What the customer sees in place of a partner's staff member (suite §5: partner access is shown as "Partner support" and is not editable there).
PARTNER_LABEL = "Partner support"


def visible_sites(db: Session, ctx: Ctx) -> List[Site]:
    rows = db.execute(select(Site).where(Site.tenant_id == ctx.tenant_id, Site.status == "active").order_by(Site.name)).scalars().all()
    keep = access.visible_site_ids(ctx.grant, {s.id for s in rows})     # row-level security already says the same; this keeps the rule in one place too
    return [s for s in rows if s.id in keep]


@router.get("")
def get_tenant(ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> Dict[str, Any]:
    t = db.get(Tenant, ctx.tenant_id)
    return {"id": str(t.id), "name": t.name, "status": t.status, "home_region": t.home_region,
            "role": ctx.grant.role, "scope": scope_json(ctx.grant), "source": ctx.grant.source, "capabilities": sorted(ctx.capabilities)}


@router.get("/sites")
def list_sites(ctx: Ctx = Depends(tenant_ctx), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    return [{"id": str(s.id), "slug": s.slug, "name": s.name, "address": s.address, "timezone": s.timezone} for s in visible_sites(db, ctx)]


@router.get("/members")
def list_members(ctx: Ctx = Depends(require("vox.members.view")), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """PhotonVox's view of the people the directory says have access here. People are added, removed and given roles in the directory ("Manage
    organization"); phone users (people who only have a phone) are PhotonVox's own and arrive with Step 3."""
    rows = db.execute(select(Access, Person).join(Person, Person.id == Access.person_id).where(Access.tenant_id == ctx.tenant_id)).all()
    out = []
    for a, p in rows:
        if not p.active or not access.sees_member(ctx.grant, Grant.from_row(a)):
            continue
        partner = a.source == "partner"
        out.append({"person_id": str(p.id), "name": PARTNER_LABEL if partner else p.name, "email": "" if partner else p.email, "role": a.role,
                    "scope": scope_json(Grant.from_row(a)), "source": a.source, "pending": p.sub is None})
    return sorted(out, key=lambda m: (-ROLES[m["role"]].rank, m["name"].lower()))
