"""GET /v1/summary: PhotonVox's one-line status for the suite's home dashboard (photonid docs/HOME-PLAN.md; the contract is photonid's
directory/contract/summary.schema.json, copied in tests/directory_contract). Called by the PhotonID account app with the person's own token, so a
token issued to that app is accepted here, and only here (app/deps.py).

What it says comes from what PhotonVox already keeps (never a call to an engine on the request): each phone system's state, its published
version and its last hand-edit check. Phone registrations and the trunk are not monitored yet (they come with the monitoring pane and vox-agent
on each engine), so the line says so instead of guessing. Cached 30 seconds per organization (and per person for the line across organizations).
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access
from app.access import Grant
from app.db import SystemSession, get_db
from app.deps import Who, current_person_any_app
from app.models import Access, PhoneSystem, Tenant, utcnow

router = APIRouter(prefix="/v1")
CACHE_S = 30
_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
NOT_MONITORED = "phones not monitored yet"


def _line(ps: Optional[PhoneSystem]) -> Tuple[str, str]:
    """(state, summary) for one organization's phone system."""
    if ps is None:
        return "unknown", "No phone system yet"
    if ps.status == "ready":
        return "ok", f"Phone system up to date (version {ps.published_version}) · {NOT_MONITORED}"
    if ps.status == "changed":
        return "attention", "Changes made outside PhotonVox were found · " + NOT_MONITORED
    if ps.status == "failed":
        return "attention", "The last change could not be published · " + NOT_MONITORED
    if ps.status == "publishing":
        return "ok", "A change is being published · " + NOT_MONITORED
    return "unknown", "Being set up"


def _reachable(db: Session, who: Who) -> List[uuid.UUID]:
    now = utcnow()
    rows = db.execute(select(Access, Tenant).join(Tenant, Tenant.id == Access.tenant_id).where(Access.person_id == who.id)).all()
    return [t.id for a, t in rows if access.is_active(Grant.from_row(a), now) and t.status != "removed"]


def _cached(key: Tuple[str, str], build) -> Dict[str, Any]:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    value = build()
    _cache[key] = (time.monotonic(), value)
    return value


@router.get("/summary")
def summary(response: Response, organization: Optional[uuid.UUID] = Query(None), who: Who = Depends(current_person_any_app),
            db: Session = Depends(get_db)) -> Dict[str, Any]:
    response.headers["Cache-Control"] = f"private, max-age={CACHE_S}"
    reachable = _reachable(db, who)
    if organization is not None:
        if organization not in reachable and not who.is_staff:
            raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "no_access", "detail": "No access to this organization in PhotonVox."})

        def one() -> Dict[str, Any]:
            with SystemSession() as s:      # the person's access was checked above; the line is the organization's, the same for everyone
                st, line = _line(s.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == organization)).scalar_one_or_none())
            return {"product": "vox", "organization_id": str(organization), "as_of": utcnow().isoformat(), "state": st, "summary": line, "sites": []}
        return _cached(("org", str(organization)), one)

    def across() -> Dict[str, Any]:
        with SystemSession() as s:
            # The demo organization is not counted across organizations (docs/DEMO.md): its own line above still answers.
            demos = set(s.execute(select(Tenant.id).where(Tenant.id.in_(reachable), Tenant.demo.is_(True))).scalars()) if reachable else set()
            counted = [t for t in reachable if t not in demos]
            systems = s.execute(select(PhoneSystem).where(PhoneSystem.tenant_id.in_(counted))).scalars().all() if counted else []
        states = [_line(ps)[0] for ps in systems]
        n, orgs = len(systems), len(counted)
        if not orgs:
            st, line = "unknown", "No organizations in PhotonVox"
        elif n == 0:
            st, line = "unknown", f"No phone systems yet across {orgs} organization{'s' if orgs != 1 else ''}"
        else:
            need = states.count("attention")
            st = "attention" if need else ("ok" if "ok" in states else "unknown")
            head = f"{need} of {n} phone systems need attention" if need else f"{n} phone system{'s' if n != 1 else ''} up to date"
            line = f"{head} across {orgs} organization{'s' if orgs != 1 else ''} · {NOT_MONITORED}"
        return {"product": "vox", "organization_id": None, "as_of": utcnow().isoformat(), "state": st, "summary": line[:120], "sites": []}
    return _cached(("person", str(who.id)), across)
