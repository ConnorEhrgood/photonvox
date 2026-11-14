from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, crypto, emergency
from app.engine import service
from app.db import SystemSession, get_db
from app.deps import Who, platform_admin
from app.document.model import E164
from app.models import CarrierRequest, EmergencyLocation, HeldNumber, PbxInstance, SyncState, Tenant, utcnow

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


# ---- engines (instances) ----

class UpstreamIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")
    proxy: str = Field(min_length=3, max_length=120)
    addresses: List[str] = Field(min_length=1)


class InstanceIn(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    region: str = "us-east"
    role: str = Field("active", pattern=r"^(active|standby|draining)$")
    hostname: str = Field(min_length=1, max_length=120)
    database_url: str = Field(min_length=10)
    # No agent: an engine whose domains are only adopted (decision 32) until vox-agent is installed there.
    agent_url: Optional[str] = Field(None, pattern=r"^https?://[A-Za-z0-9.:\[\]-]+(:[0-9]+)?/?$")
    agent_secret: Optional[str] = Field(None, min_length=32, max_length=200)
    upstreams: List[UpstreamIn]
    routing: Dict[str, List[str]]
    emergency_upstream: str
    # The engine's own gateways, hand-built (the live engine, decision 32): routing then names them by key, PhotonVox writes no upstream and
    # Apply refuses the instance. Key -> the existing gateway's id.
    own_gateways: Dict[str, uuid.UUID] = Field(default_factory=dict)
    # Its phones and calls are simulated (staging, for the demo organization only): set when it is registered, never changed after.
    simulated: bool = False


def _instance_json(i: PbxInstance) -> Dict[str, Any]:
    return {"id": str(i.id), "name": i.name, "region": i.region, "role": i.role, "hostname": i.hostname, "agent_kind": (i.agent or {}).get("kind"),
            "upstreams": i.upstreams, "own_gateways": i.own_gateways or {}, "simulated": bool(i.simulated), "routing": i.routing, "emergency_upstream": i.emergency_upstream, "versions": i.versions,
            "email": {k: v for k, v in (i.email or {}).items()}, "email_password_set": bool(i.email_password_sealed)}


@router.get("/instances")
def instances(who: Who = Depends(platform_admin), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    return [_instance_json(i) for i in db.execute(select(PbxInstance).order_by(PbxInstance.name)).scalars()]


@router.post("/instances", status_code=201)
def add_instance(body: InstanceIn, who: Who = Depends(platform_admin), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Register an engine. Its database login and its vox-agent secret are sealed at once and never shown again."""
    if bool(body.agent_url) != bool(body.agent_secret):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "bad_agent", "detail": "An agent needs both its address and its secret."})
    if body.own_gateways and body.upstreams:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "bad_routing", "detail": "An instance's upstreams are either PhotonVox's or its own, not both."})
    keys = {u.key for u in body.upstreams} | set(body.own_gateways)
    if body.emergency_upstream not in keys or not body.routing.get("national") or any(k not in keys for ks in body.routing.values() for k in ks):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "bad_routing", "detail": "Routing and 911 must name upstreams of this instance, with one for national calls."})
    i = PbxInstance(name=body.name, region=body.region, role=body.role, hostname=body.hostname, database_url_sealed=crypto.seal(body.database_url),
                    agent={"kind": "http", "url": body.agent_url} if body.agent_url else {"kind": "none"},
                    agent_secret_sealed=crypto.seal(body.agent_secret) if body.agent_secret else "",
                    upstreams=[u.model_dump() for u in body.upstreams], routing=body.routing, emergency_upstream=body.emergency_upstream,
                    own_gateways={k: str(v) for k, v in body.own_gateways.items()}, simulated=body.simulated)
    db.add(i)
    db.flush()
    audit.record(db, actor_id=who.id, actor_label=who.label, actor_source="platform", action="instance.added", target_type="pbx_instance", target_id=i.id,
                 name=i.name)
    db.commit()
    return _instance_json(i)


# ---- the emergency address queue (R1: validated by hand) and requests to carriers (decision 31) ----

@router.get("/emergency-locations")
def pending_locations(who: Who = Depends(platform_admin), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    rows = db.execute(select(EmergencyLocation, Tenant.name).join(Tenant, Tenant.id == EmergencyLocation.tenant_id)
                      .where(EmergencyLocation.status == "pending").order_by(EmergencyLocation.created_at)).all()
    return [{"id": str(loc.id), "organization": name, "site_id": str(loc.site_id), "key": loc.key, "address": loc.address} for loc, name in rows]


class Verdict(BaseModel):
    ok: bool
    note: str = Field("", max_length=1000)
    reference: str = Field("", max_length=200)


@router.post("/emergency-locations/{location_id}/validate")
def validate_location(location_id: uuid.UUID, body: Verdict, who: Who = Depends(platform_admin)) -> Dict[str, Any]:
    """Staff's answer on an address. As the system, like every staff change to a customer's records: the audit entry names the organization,
    which staff are not members of, and must commit with the change."""
    with SystemSession() as s:
        loc = s.get(EmergencyLocation, location_id)
        if loc is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        loc.status, loc.note, loc.validated_by_label, loc.validated_at = ("validated" if body.ok else "rejected"), body.note, who.label, utcnow()
        audit.record(s, actor_id=who.id, actor_label=who.label, actor_source="platform", action="emergency_location.validated" if body.ok else
                     "emergency_location.rejected", tenant_id=loc.tenant_id, target_type="emergency_location", target_id=loc.id)
        s.commit()
        return {"id": str(loc.id), "status": loc.status}


@router.get("/carrier-requests")
def carrier_requests(who: Who = Depends(platform_admin), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    rows = db.execute(select(CarrierRequest, Tenant.name).join(Tenant, Tenant.id == CarrierRequest.tenant_id)
                      .where(CarrierRequest.status.in_(("open", "sent"))).order_by(CarrierRequest.created_at)).all()
    return [{"id": str(r.id), "organization": name, "carrier": r.carrier, "method": r.method, "status": r.status, "items": r.items,
             "reference": r.reference, "created_at": r.created_at.isoformat(), "sent_at": r.sent_at.isoformat() if r.sent_at else None,
             "email": emergency.compose(r, name)} for r, name in rows]


def _request(db: Session, request_id: uuid.UUID, statuses: tuple) -> CarrierRequest:
    req = db.get(CarrierRequest, request_id)
    if req is None or req.status not in statuses:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "no_request", "detail": "There is no such request waiting."})
    return req


@router.post("/carrier-requests/{request_id}/sent")
def request_sent(request_id: uuid.UUID, body: Verdict, who: Who = Depends(platform_admin)) -> Dict[str, Any]:
    """Staff sent it themselves (the carrier's portal or by hand): the ticket number or a note goes in `reference`."""
    with SystemSession() as s:     # the numbers' state is the system's to change (the app role only reads it)
        req = _request(s, request_id, ("open",))
        emergency.mark_sent(s, req, body.reference or "sent by hand", method="ticket" if body.reference else None)
        audit.record(s, actor_id=who.id, actor_label=who.label, actor_source="platform", action="carrier_request.sent", tenant_id=req.tenant_id,
                     target_type="carrier_request", target_id=req.id, reference=body.reference)
        s.commit()
        return {"id": str(req.id), "status": req.status}


@router.post("/carrier-requests/{request_id}/close")
def request_closed(request_id: uuid.UUID, body: Verdict, who: Who = Depends(platform_admin)) -> Dict[str, Any]:
    """The carrier's answer: confirmed (`ok`) or rejected, with a note."""
    with SystemSession() as s:
        req = _request(s, request_id, ("open", "sent"))
        emergency.close(s, req, body.ok, who.label, body.note)
        audit.record(s, actor_id=who.id, actor_label=who.label, actor_source="platform", action="carrier_request.confirmed" if body.ok else
                     "carrier_request.rejected", tenant_id=req.tenant_id, target_type="carrier_request", target_id=req.id)
        s.commit()
        return {"id": str(req.id), "status": req.status}


class EmailIn(BaseModel):
    host: str = Field(min_length=3, max_length=200)
    port: int = Field(587, ge=1, le=65535)
    secure: str = Field("tls", pattern=r"^(tls|ssl|none)$")
    username: str = Field("", max_length=200)
    password: str = Field("", max_length=500)
    from_: str = Field(alias="from", pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    from_name: str = Field("", max_length=100)


def get_connect() -> service.Connect:  # overridden in tests
    return service.connect


@router.put("/instances/{instance_id}/email")
def set_email(instance_id: uuid.UUID, body: EmailIn, who: Who = Depends(platform_admin), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """The instance's outgoing mail (voicemail to email). The password (a Postmark server token) is sealed; leaving it empty keeps the one set."""
    i = db.get(PbxInstance, instance_id)
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    i.email = {"host": body.host, "port": body.port, "secure": body.secure, "username": body.username, "from": body.from_, "from_name": body.from_name}
    if body.password:
        i.email_password_sealed = crypto.seal(body.password)
    audit.record(db, actor_id=who.id, actor_label=who.label, actor_source="platform", action="instance.email_set", target_type="pbx_instance",
                 target_id=i.id, host=body.host)
    db.commit()
    return _instance_json(i)


@router.post("/instances/{instance_id}/apply")
def apply_instance(instance_id: uuid.UUID, who: Who = Depends(platform_admin), db: Session = Depends(get_db),
                   connect: service.Connect = Depends(get_connect)) -> Dict[str, Any]:
    """Put the instance's upstreams and outgoing mail on its engine now."""
    i = db.get(PbxInstance, instance_id)
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not i.upstreams:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "hand_built", "detail": "This instance's upstreams are its own (hand-built): PhotonVox applies nothing to it."})
    try:
        out = service.apply_instance(i, connect)
    except Exception as e:  # noqa: BLE001 - the engine or its agent failed: say so, in a sentence
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, {"code": "engine_failed", "detail": f"The engine did not take it: {type(e).__name__}."})
    audit.record(db, actor_id=who.id, actor_label=who.label, actor_source="platform", action="instance.applied", target_type="pbx_instance",
                 target_id=i.id, **out)
    db.commit()
    return out


class AdoptIn(BaseModel):
    tenant_id: uuid.UUID
    site_id: uuid.UUID
    domain: str = Field(min_length=1, max_length=200, pattern=r"^[a-z0-9.-]+$")


@router.post("/instances/{instance_id}/adopt", status_code=201)
def adopt_domain(instance_id: uuid.UUID, body: AdoptIn, who: Who = Depends(platform_admin), connect: service.Connect = Depends(get_connect)) -> Dict[str, Any]:
    """Take a hand-built domain over in place (decision 32, ARCHITECTURE §17): read it, import it, prove its first publish changes nothing, and
    keep it as the organization's phone system (its draft is the imported document; its numbers are assigned to it). Nothing is written to the
    engine. Refused, with the reason, when the proof fails. The report lists everything that could not be expressed."""
    from app.engine import takeover
    with SystemSession() as s:          # as the system, like assigning numbers: only staff take a domain over
        i = s.get(PbxInstance, instance_id)
        if i is None or s.get(Tenant, body.tenant_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        eng, _agent = connect(i)
        try:
            with eng.connect() as conn:
                out = takeover.adopt(s, i, body.tenant_id, body.site_id, body.domain, conn)
        except takeover.TakeoverError as e:
            s.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, {"code": "not_adopted", "detail": str(e)})
        finally:
            eng.dispose()
        audit.record(s, actor_id=who.id, actor_label=who.label, actor_source="platform", action="phone_system.adopted", tenant_id=body.tenant_id,
                     target_type="phone_system", target_id=out["phone_system_id"], instance=str(i.id), objects=out["objects"], extras=out["extras"])
        s.commit()
        return out


# ---- held numbers (security review C2): Photon's stock, and which organization each is assigned to ----

class NumberIn(BaseModel):
    tenant_id: Optional[uuid.UUID] = None      # None: Photon's stock
    carrier: str = Field("htc", pattern=r"^[a-z0-9-]{1,40}$")
    note: str = Field("", max_length=200)


@router.get("/numbers")
def held_numbers(who: Who = Depends(platform_admin), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    rows = db.execute(select(HeldNumber, Tenant.name).outerjoin(Tenant, Tenant.id == HeldNumber.tenant_id).order_by(HeldNumber.number)).all()
    return [{"number": n.number, "tenant_id": str(n.tenant_id) if n.tenant_id else None, "organization": name, "carrier": n.carrier, "note": n.note}
            for n, name in rows]


@router.put("/numbers/{number}")
def put_number(number: str, body: NumberIn, who: Who = Depends(platform_admin)) -> Dict[str, Any]:
    """Add a number to Photon's stock, or assign it to an organization (or back to the stock). As the system: only staff assign numbers."""
    if not re.match(E164, number):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "bad_number", "detail": "A North American number in +1 form."})
    with SystemSession() as s:
        n = s.get(HeldNumber, number) or HeldNumber(number=number)
        before = n.tenant_id
        n.tenant_id, n.carrier, n.note = body.tenant_id, body.carrier, body.note
        s.add(n)
        audit.record(s, actor_id=who.id, actor_label=who.label, actor_source="platform", action="number.assigned", tenant_id=body.tenant_id or before,
                     target_type="number", target_id=number, before=str(before) if before else None, after=str(body.tenant_id) if body.tenant_id else None)
        s.commit()
        return {"number": number, "tenant_id": str(n.tenant_id) if n.tenant_id else None}


@router.delete("/numbers/{number}", status_code=204)
def release_number(number: str, who: Who = Depends(platform_admin)) -> None:
    """Give a number back to the carrier: only once it is assigned to no organization."""
    with SystemSession() as s:
        n = s.get(HeldNumber, number)
        if n is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        if n.tenant_id is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, {"code": "assigned", "detail": "Unassign it from its organization first."})
        s.delete(n)
        audit.record(s, actor_id=who.id, actor_label=who.label, actor_source="platform", action="number.released", target_type="number", target_id=number)
        s.commit()
