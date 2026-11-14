"""PhotonEntry's connection to PhotonVox (photonaccess docs/VOX.md, contract/vox/): the organization's admins make a token with scope
`vox:entry` (shown once, kept as a hash, revocable), and PhotonEntry reads with it, never writing anything:

    GET /integrations/entry/v1/door-stations                          the published door stations, each with the SIP account its intercom uses
    GET /integrations/entry/v1/door-calls?station=&at=&window_s=      the station's call in progress at `at` (else the last one that ended within
                                                                      window_s before it) and who answered it

Door calls come from the engine: when each started and was answered, and by whom, from the lines the door's dial plan logs (vox-agent reads
them); when each ended, from FusionPBX's call records (imported a few seconds after the hangup, so a call just ended may still read as in
progress). Call records are CPNI: a token reads only its own organization's door stations.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import audit, crypto
from app.db import SystemSession, get_db
from app.deps import Ctx, require
from app.document.model import PhoneSystem as Document
from app.engine import service
from app.models import Access, EngineSecret, IntegrationToken, PbxInstance, Person, PhoneSystem, PhoneSystemVersion, utcnow
from app.routes.phone_system import _who
from app.routes.platform import get_connect

MANAGE, SCOPE, PREFIX = "vox.entry.manage", "vox:entry", "pvx_entry_"
manage = APIRouter(prefix="/tenants/{tenant_id}/integrations")
entry = APIRouter(prefix="/integrations/entry/v1")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---- the organization's admins: make, list and revoke tokens ----

class NewToken(BaseModel):
    label: str = Field("PhotonEntry", min_length=1, max_length=100, pattern=r"^[^<>%\x00-\x1f\x7f]+$")


def _token_json(t: IntegrationToken) -> Dict[str, Any]:
    return {"id": str(t.id), "label": t.label, "scope": t.scope, "hint": t.hint, "created_at": t.created_at.isoformat(),
            "revoked_at": t.revoked_at.isoformat() if t.revoked_at else None, "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None}


@manage.get("/entry-tokens")
def list_tokens(ctx: Ctx = Depends(require(MANAGE)), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    rows = db.execute(select(IntegrationToken).where(IntegrationToken.tenant_id == ctx.tenant_id, IntegrationToken.scope == SCOPE)
                      .order_by(IntegrationToken.created_at)).scalars()
    return [_token_json(t) for t in rows]


@manage.post("/entry-tokens", status_code=201)
def make_token(body: NewToken, ctx: Ctx = Depends(require(MANAGE)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """The token is in this answer only: PhotonVox keeps its hash."""
    token = PREFIX + secrets.token_urlsafe(32)
    t = IntegrationToken(tenant_id=ctx.tenant_id, scope=SCOPE, label=body.label, token_hash=_hash(token), hint=token[-4:], created_by=ctx.who.id)
    db.add(t)
    db.flush()
    audit.record(db, **_who(ctx), action="integration.token_made", target_type="integration_token", target_id=t.id, scope=SCOPE, label=body.label)
    db.commit()
    return {**_token_json(t), "token": token}


@manage.delete("/entry-tokens/{token_id}")
def revoke_token(token_id: uuid.UUID, ctx: Ctx = Depends(require(MANAGE)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    t = db.get(IntegrationToken, token_id)
    if t is None or t.tenant_id != ctx.tenant_id or t.scope != SCOPE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if t.revoked_at is None:
        t.revoked_at = utcnow()
        audit.record(db, **_who(ctx), action="integration.token_revoked", target_type="integration_token", target_id=t.id)
        db.commit()
    return _token_json(t)


# ---- PhotonEntry, with its token ----

def entry_tenant(authorization: Optional[str] = Header(None)) -> uuid.UUID:
    """The organization a live `vox:entry` token belongs to: 401 for none, an unknown or a revoked one; 403 for a token of another scope."""
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized", headers={"WWW-Authenticate": "Bearer"})
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise unauthorized
    with SystemSession() as s:
        t = s.execute(select(IntegrationToken).where(IntegrationToken.token_hash == _hash(token.strip()))).scalar_one_or_none()
        if t is None or t.revoked_at is not None:
            raise unauthorized
        if t.scope != SCOPE:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This token is not for PhotonEntry")
        now = utcnow()
        if t.last_used_at is None or now - t.last_used_at > timedelta(minutes=1):
            t.last_used_at = now
            s.commit()
        return t.tenant_id


def _published(s: Session, tenant_id: uuid.UUID):
    """The organization's phone system, its engine and its published document (what is on the engine), or Nones."""
    ps = s.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == tenant_id)).scalar_one_or_none()
    if ps is None or ps.published_version is None:
        return None, None, None
    v = s.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.phone_system_id == ps.id,
                                                   PhoneSystemVersion.number == ps.published_version)).scalar_one()
    return ps, s.get(PbxInstance, ps.instance_id), (Document.model_validate(v.document), v)


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


@entry.get("/door-stations")
def door_stations(tenant_id: uuid.UUID = Depends(entry_tenant)) -> Dict[str, Any]:
    with SystemSession() as s:
        ps, instance, pub = _published(s, tenant_id)
        stations: List[Dict[str, Any]] = []
        if ps is not None:
            doc, version = pub
            sip = instance.sip_access or {}
            secrets_ = {e.label: e for e in s.execute(select(EngineSecret).where(EngineSecret.phone_system_id == ps.id)).scalars()}
            for key, d in sorted(doc.doors.items()):
                secret = secrets_.get(f"extension:{d.extension}")
                if secret is None:              # not on the engine yet (its first publish makes its password)
                    continue
                stations.append({"id": key, "name": d.name, "site_id": d.site, "extension": d.extension,
                                 "sip": {"server": ps.domain_name, "port": int(sip.get("port", 5060)), "transport": sip.get("transport", "udp"),
                                         "username": d.extension, "password": crypto.unseal(secret.sealed),
                                         "outbound_proxy": sip.get("outbound_proxy")},
                                 "updated_at": _iso(max(secret.created_at, version.created_at))})
        return {"organization_id": str(tenant_id), "stations": stations}


AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$")


@entry.get("/door-calls")
def door_calls(station: str = Query(..., max_length=64), at: str = Query(..., max_length=40), window_s: int = Query(60),
               tenant_id: uuid.UUID = Depends(entry_tenant), connect: service.Connect = Depends(get_connect)) -> Dict[str, Any]:
    if not AT.match(at) or not 1 <= window_s <= 600:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "at: an ISO 8601 UTC time; window_s: 1 to 600")
    when = datetime.fromisoformat(at.replace("Z", "+00:00"))
    moment = int(when.timestamp())
    with SystemSession() as s:
        ps, instance, pub = _published(s, tenant_id)
        door = pub[0].doors.get(station) if ps is not None else None
        if door is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        doc = pub[0]
        eng, agent = connect(instance)
        try:
            logged = agent.door_calls(ps.domain_name, door.extension, moment - 3600)
            with eng.connect() as c:
                ext_id = c.execute(text("select extension_uuid from v_extensions where domain_uuid = :d and extension = :e"),
                                   {"d": str(ps.domain_uuid), "e": door.extension}).scalar()
                ids = [x["call"] for x in logged]
                records = c.execute(text(
                    "select xml_cdr_uuid::text as call, start_epoch, answer_epoch, end_epoch from v_xml_cdr where domain_uuid = :d and "
                    "(xml_cdr_uuid::text = any(:ids) or (extension_uuid = :x and end_epoch >= :lo and start_epoch <= :hi))"),
                    {"d": str(ps.domain_uuid), "ids": ids, "x": ext_id, "lo": moment - window_s, "hi": moment}).mappings().all()
        except Exception as e:  # noqa: BLE001 - the engine or its agent did not answer: PhotonEntry asks again
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The phone system's engine did not answer; ask again.") from e
        finally:
            eng.dispose()
        calls: Dict[str, Dict[str, Any]] = {}
        for x in logged:
            calls[x["call"]] = {"call": x["call"], "start": x["started"] or x["answered"], "answer": x["answered"], "end": None,
                                "user": x["user"], "dest": x["dest"]}
        for r in records:
            c = calls.setdefault(r["call"], {"call": r["call"], "user": None, "dest": None})
            c["start"] = int(r["start_epoch"]) if r["start_epoch"] else c.get("start")
            c["answer"] = int(r["answer_epoch"]) if r["answer_epoch"] else c.get("answer")
            c["end"] = int(r["end_epoch"]) if r["end_epoch"] else None
        live = [c for c in calls.values() if c.get("start") is not None and c["start"] <= moment and (c["end"] is None or c["end"] >= moment)]
        ended = [c for c in calls.values() if c.get("end") is not None and moment - window_s <= c["end"] < moment]
        chosen = max(live, key=lambda c: c["start"]) if live else (max(ended, key=lambda c: c["end"]) if ended else None)
        if chosen is None:
            return {"organization_id": str(tenant_id), "station_id": station, "call": None}
        epoch = lambda t: _iso(datetime.fromtimestamp(t, timezone.utc)) if t else None       # noqa: E731
        return {"organization_id": str(tenant_id), "station_id": station,
                "call": {"id": chosen["call"], "started_at": epoch(chosen["start"]), "answered_at": epoch(chosen.get("answer")),
                         "ended_at": epoch(chosen.get("end")), "answered_by": _answered_by(s, tenant_id, doc, chosen)}}


def _answered_by(s: Session, tenant_id: uuid.UUID, doc: Document, c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The extension that answered, its name and its directory person (by the user's email, among the organization's people); an outside number
    as its last four digits, never whole."""
    if c.get("user"):
        user = next((u for u in doc.users.values() if u.extension == c["user"]), None)
        person = None
        if user is not None and user.email:
            person = s.execute(select(Person.id).join(Access, Access.person_id == Person.id)
                               .where(Access.tenant_id == tenant_id, func.lower(Person.email) == user.email.lower())).scalars().first()
        return {"extension": c["user"], "name": user.name if user else f"Extension {c['user']}", "person_id": str(person) if person else None}
    digits = re.sub(r"\D", "", c.get("dest") or "")
    if len(digits) >= 7:
        return {"extension": "…" + digits[-4:], "name": "Outside number", "person_id": None}
    return None
