from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SystemSession, get_db
from app.deps import Who, platform_admin
from app.models import SyncState, Tenant

router = APIRouter(prefix="/platform")


@router.get("/organizations")
def organizations(who: Who = Depends(platform_admin), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """PhotonVox's view of every organization entitled to it. Platform staff see that they exist, not their phone systems or people: to look inside
    a customer they need a grant there like anyone else (as partner "Photon"), and that is audited (suite §5)."""
    return [{"id": str(t.id), "name": t.name, "status": t.status, "plan_key": t.plan_key, "home_region": t.home_region, "products": list(t.products or []),
             "partner_id": str(t.partner_id) if t.partner_id else None}
            for t in db.execute(select(Tenant).order_by(Tenant.name)).scalars()]


@router.get("/directory")
def directory_status(who: Who = Depends(platform_admin)) -> Dict[str, Any]:
    """How current our copy of the directory is. Read as the system: `sync_state` is the sync's own and the app role cannot see it."""
    with SystemSession() as s:
        st = s.get(SyncState, 1)
        if st is None:
            return {"cursor": 0, "last_pull_at": None, "last_ok_at": None, "last_error": None}
        return {"cursor": st.cursor, "last_pull_at": st.last_pull_at.isoformat() if st.last_pull_at else None,
                "last_ok_at": st.last_ok_at.isoformat() if st.last_ok_at else None, "last_error": st.last_error}
