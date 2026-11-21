"""An organization's phone system: the draft the integrator builds, publishing it (queued for the worker, which writes it and runs the check),
versions and undo, templates and bulk import, and the sites' emergency addresses with their numbers' state at the carrier (ARCHITECTURE §3,
§8, §11a). One phone system per organization (decision 4)."""
from __future__ import annotations

import re
import secrets
import string
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.compiler.compile import CompileError, compile_plan
from app.db import SystemSession, get_db
from app.deps import Ctx, load_ctx, require
from app.document import clone as cloning, importer, policy, templates
from app.document.model import PhoneSystem as Document
from app.document.validate import problems
from app.engine import service
from app.models import (CarrierRequest, EmergencyLocation, EmergencyNumber, HeldNumber, PbxInstance, PhoneSystem, PhoneSystemVersion, Tenant, utcnow)
from app.routes.tenants import visible_sites

router = APIRouter(prefix="/tenants/{tenant_id}")
VIEW, BUILD, EMERGENCY = "vox.phone_system.view", "vox.phone_system.build", "vox.site.emergency"


def _ps(db: Session, ctx: Ctx) -> PhoneSystem:
    ps = db.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == ctx.tenant_id)).scalar_one_or_none()
    if ps is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "no_phone_system", "detail": "This organization has no phone system yet."})
    return ps


def _instance(ps: PhoneSystem) -> PbxInstance:
    """The phone system's engine, read as the system: instances are Photon staff's, but compiling a draft needs its upstreams' names."""
    with SystemSession() as s:
        i = s.get(PbxInstance, ps.instance_id)
        s.expunge(i)
        return i


def _who(ctx: Ctx) -> Dict[str, Any]:
    return {"actor_id": ctx.who.id, "actor_label": ctx.who.label, "actor_source": ctx.grant.source, "tenant_id": ctx.tenant_id}


def _problems(db: Session, ps: PhoneSystem, doc: Document) -> List[Dict[str, str]]:
    ctx = service.context(db, ps, _instance(ps))
    found = problems(doc, ctx.validated_locations, ctx.assigned_numbers)
    return [{"path": p.path, "code": p.code, "message": p.message} for p in found]


UUIDS = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _shown(x: Optional[str]) -> Optional[str]:
    """A test call's finding without the engine's gateway ids (security review L4)."""
    return UUIDS.sub("…", x) if x else x


def _version(v: PhoneSystemVersion) -> Dict[str, Any]:
    results = (v.check or {}).get("results", [])
    return {"number": v.number, "state": v.state, "note": v.note, "error": v.error, "created_by": v.created_by_label,
            "created_at": v.created_at.isoformat(), "published_at": v.published_at.isoformat() if v.published_at else None,
            "checks": {"passed": sum(1 for r in results if r["ok"]), "total": len(results),
                       "failed": [{"kind": r["kind"], "number": r["number"], "expected": [_shown(x) for x in r["expect"]], "got": _shown(r["got"])}
                                  for r in results if not r["ok"]]}}


def _summary(db: Session, ps: PhoneSystem) -> Dict[str, Any]:
    doc = Document.model_validate(ps.draft)
    drift = ps.drift or {}
    return {"id": str(ps.id), "status": ps.status, "domain": ps.domain_name, "instance": _instance(ps).name,
            "published_version": ps.published_version, "draft": ps.draft, "draft_updated_at": ps.draft_updated_at.isoformat(),
            "problems": _problems(db, ps, doc),
            "drift": {"checked_at": drift.get("checked_at"), "changed": len(drift.get("changed", [])), "missing": len(drift.get("missing", [])),
                      "extra": drift.get("extra", [])}}


@router.get("/phone-system")
def get_phone_system(ctx: Ctx = Depends(require(VIEW, sites=True)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    return _summary(db, _ps(db, ctx))


@router.post("/phone-system", status_code=201)
def create_phone_system(ctx: Ctx = Depends(require(BUILD)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Start the organization's phone system, empty, on an active engine in its home region (placement is PhotonVox's, never the integrator's)."""
    if db.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == ctx.tenant_id)).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "exists", "detail": "This organization already has a phone system."})
    tenant = db.get(Tenant, ctx.tenant_id)
    with SystemSession() as s:        # instances are Photon's: the integrator may not read them, only be placed on one
        # The demo organization goes on a simulated engine, and nobody else does (docs/DEMO.md).
        rows = s.execute(select(PbxInstance).where(PbxInstance.role == "active", PbxInstance.simulated == bool(tenant.demo))
                         .order_by(PbxInstance.created_at)).scalars().all()
        chosen = next((i for i in rows if i.region == tenant.home_region), rows[0] if rows else None)
        instance_id = chosen.id if chosen else None
    if instance_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "no_instance", "detail": "No engine is available yet. Photon staff have been told."})
    name = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6)) + ".sip.photoninfra.xyz"
    ps = PhoneSystem(tenant_id=ctx.tenant_id, instance_id=instance_id, domain_name=name, domain_uuid=uuid.uuid4(), draft={"version": 1})
    db.add(ps)
    audit.record(db, **_who(ctx), action="phone_system.created", target_type="phone_system", target_id=ps.id, domain=name)
    db.commit()
    return _summary(db, ps)


class DraftIn(BaseModel):
    document: Dict[str, Any]


def _allowed(ctx: Ctx, old_raw: Dict[str, Any], new: Document) -> None:
    """Refuse a change this person may not make (app/document/policy.py: owners open up calling; site-limited people stay in their sites).
    The sites are those where the person may build: a site-limited admin who is a whole-organization user builds only at their sites."""
    reach = ctx.reach(BUILD)
    reason = policy.refusal(Document.model_validate(old_raw or {"version": 1}), new, ctx.can, reach.reach_all, {str(s) for s in reach.reach_sites})
    if reason:
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "not_allowed_change", "detail": reason})


def _kept(doc: Document, value: Optional[bool]) -> Document:
    """The document with `protections` as stored (audit VOX-A-1): switching an adopted system's protections on or off is Photon staff's step
    (`manage protect-apply`, `manage republish`), never a customer route's, whatever the document sent says or leaves out."""
    return doc if doc.protections == value else doc.model_copy(update={"protections": value})


def _stored(raw: Optional[Dict[str, Any]]) -> Optional[bool]:
    return (raw or {}).get("protections")


def _document(raw: Dict[str, Any]) -> Document:
    try:
        return Document.model_validate(raw)
    except ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "invalid_document", "detail": "The phone system has fields that are not valid.",
                            "errors": [{"path": ".".join(str(x) for x in err["loc"]), "message": err["msg"]} for err in e.errors()]})


@router.put("/phone-system/draft")
def save_draft(body: DraftIn, ctx: Ctx = Depends(require(BUILD, sites=True)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Save the draft. Problems (an unvalidated address, a dangling reference) do not stop saving; they stop publishing."""
    ps = _ps(db, ctx)
    doc = _kept(_document(body.document), _stored(ps.draft))
    _allowed(ctx, ps.draft, doc)
    ps.draft, ps.draft_updated_at = doc.model_dump(mode="json", exclude_defaults=False), utcnow()
    audit.record(db, **_who(ctx), action="phone_system.draft_saved", target_type="phone_system", target_id=ps.id)
    db.commit()
    return _summary(db, ps)


@router.post("/phone-system/publish", status_code=202)
def publish_draft(ctx: Ctx = Depends(require(BUILD, sites=True)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Queue the draft for publishing. Refused while it has problems or another version is still being published."""
    ps = _ps(db, ctx)
    return _queue(db, ctx, ps, ps.draft, "")


def _queue(db: Session, ctx: Ctx, ps: PhoneSystem, document: Dict[str, Any], note: str) -> Dict[str, Any]:
    busy = db.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.phone_system_id == ps.id,
                                                       PhoneSystemVersion.state.in_(("queued", "publishing")))).scalars().first()
    if busy:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "busy", "detail": f"Version {busy.number} is still being published."})
    doc = _document(document)
    _within_sites(db, ctx, ps, doc)
    try:
        compile_plan(doc, service.context(db, ps, _instance(ps)))
    except CompileError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "not_publishable", "detail": str(e),
                            "problems": [{"path": p.path, "code": p.code, "message": p.message} for p in e.problems]})
    v = service.queue(db, ps, document, ctx.who.id, ctx.who.label, note)
    db.flush()
    audit.record(db, **_who(ctx), action="phone_system.publish_requested", target_type="phone_system", target_id=ps.id, version=v.number, note=note)
    db.commit()
    return _version(v)


def _live(db: Session, ps: PhoneSystem) -> Optional[PhoneSystemVersion]:
    if ps.published_version is None:
        return None
    return db.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.phone_system_id == ps.id,
                                                       PhoneSystemVersion.number == ps.published_version)).scalar_one_or_none()


def _within_sites(db: Session, ctx: Ctx, ps: PhoneSystem, doc: Document) -> None:
    """A person who may build only at some sites publishes only changes to those sites (audit VOX-A-5): what the version would change against
    the live one, by the same test as a draft save (a draft may hold another admin's saved changes to other sites, or organization-wide ones)."""
    reach = ctx.reach(BUILD)
    if reach.reach_all:
        return
    live = _live(db, ps)
    touched = policy.touched_sites(Document.model_validate(live.document if live else {"version": 1}), doc)
    if "*" in touched or not touched <= {str(s) for s in reach.reach_sites}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "not_allowed_change", "detail":
                            "Your access is limited to some sites: this would publish changes to other sites or to the whole organization. "
                            "Ask an admin of the whole organization to publish it."})


@router.get("/phone-system/versions")
def versions(ctx: Ctx = Depends(require(VIEW, sites=True)), db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    ps = _ps(db, ctx)
    rows = db.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.phone_system_id == ps.id).order_by(PhoneSystemVersion.number.desc())).scalars()
    return [_version(v) for v in rows]


@router.post("/phone-system/versions/{number}/restore", status_code=202)
def restore(number: int, ctx: Ctx = Depends(require(BUILD, sites=True)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Undo: publish an earlier version's document again, as a new version. The draft becomes that document too, so the builder shows it."""
    ps = _ps(db, ctx)
    old = db.execute(select(PhoneSystemVersion).where(PhoneSystemVersion.phone_system_id == ps.id, PhoneSystemVersion.number == number)).scalar_one_or_none()
    if old is None or old.state not in ("ready", "superseded"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "no_version", "detail": f"There is no published version {number}."})
    # The undo brings back the earlier version's phone system, never its protections: those stay as the live version has them (VOX-A-1).
    live = _live(db, ps)
    document = {**old.document, "protections": _stored(live.document if live else ps.draft)}
    _allowed(ctx, {**(ps.draft or {"version": 1}), "protections": document["protections"]}, _document(document))
    out = _queue(db, ctx, ps, document, f"restored from version {number}")
    ps.draft, ps.draft_updated_at = document, utcnow()
    db.commit()
    return out


# ---- templates and bulk import ----

@router.get("/phone-system/templates")
def list_templates(ctx: Ctx = Depends(require(VIEW, sites=True))) -> List[Dict[str, str]]:
    return templates.catalog()


class TemplateIn(BaseModel):
    template: str
    site_id: str
    location: str = Field(min_length=1, max_length=40)
    main_number: str
    users: str = ""             # pasted rows (bulk import), optional


@router.post("/phone-system/draft/template")
def apply_template(body: TemplateIn, ctx: Ctx = Depends(require(BUILD, sites=True)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Replace the draft with a template built from the answers (and the pasted users). Only rows without problems are taken; the rest come back."""
    ps = _ps(db, ctx)
    if body.template not in templates.TEMPLATES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "no_template", "detail": "There is no such template."})
    sites = {str(s.id): s.name for s in visible_sites(db, ctx, BUILD)}
    if body.site_id not in sites:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "no_site", "detail": "There is no such site."})
    number = importer._number(body.main_number)
    rows = importer.preview(body.users, {"users": {}, "numbers": {number: {}}}, body.site_id, sites)
    users = {r["id"]: r["user"] for r in rows if not r["problems"]}
    if not users:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "no_users", "detail": "Add at least one user (one per line).", "rows": rows})
    doc = _kept(_document(templates.build(body.template, body.site_id, body.location, number, users)), _stored(ps.draft))
    _allowed(ctx, ps.draft, doc)
    ps.draft, ps.draft_updated_at = doc.model_dump(mode="json"), utcnow()
    audit.record(db, **_who(ctx), action="phone_system.template_applied", target_type="phone_system", target_id=ps.id, template=body.template,
                 users=len(users))
    db.commit()
    return {**_summary(db, ps), "rows": rows}


class CloneIn(BaseModel):
    from_tenant_id: uuid.UUID


@router.post("/phone-system/draft/clone")
def clone_draft(body: CloneIn, ctx: Ctx = Depends(require(BUILD, sites=True)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Copy another customer's call flows, hours, calling policy and features into this draft (the integrator must see both)."""
    ps = _ps(db, ctx)
    other = load_ctx(db, ctx.who, body.from_tenant_id)
    source = db.execute(select(PhoneSystem).where(PhoneSystem.tenant_id == body.from_tenant_id)).scalar_one_or_none() if other else None
    if other is None or not other.can(VIEW) or source is None or body.from_tenant_id == ctx.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "no_source", "detail": "There is no such phone system to copy from."})
    doc = _kept(_document(cloning.clone(source.draft, ps.draft)), _stored(ps.draft))
    _allowed(ctx, ps.draft, doc)
    ps.draft, ps.draft_updated_at = doc.model_dump(mode="json"), utcnow()
    audit.record(db, **_who(ctx), action="phone_system.cloned", target_type="phone_system", target_id=ps.id, source=str(body.from_tenant_id))
    db.commit()
    return _summary(db, ps)


class ImportIn(BaseModel):
    text: str = Field(max_length=200_000)
    site_id: str
    group: Optional[str] = None
    apply: bool = False


@router.post("/phone-system/import")
def import_users(body: ImportIn, ctx: Ctx = Depends(require(BUILD, sites=True)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Bulk import into the draft: with `apply` false, the review (each row with its problems); with `apply` true, the rows without problems
    are added (and to `group`, if named)."""
    ps = _ps(db, ctx)
    sites = {str(s.id): s.name for s in visible_sites(db, ctx, BUILD)}
    if body.site_id not in sites:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "no_site", "detail": "There is no such site."})
    rows = importer.preview(body.text, ps.draft, body.site_id, sites)
    out: Dict[str, Any] = {"rows": rows, "ready": sum(1 for r in rows if not r["problems"])}
    if body.apply:
        doc = _kept(_document(importer.apply(ps.draft, rows, body.group)), _stored(ps.draft))
        _allowed(ctx, ps.draft, doc)
        ps.draft, ps.draft_updated_at = doc.model_dump(mode="json"), utcnow()
        audit.record(db, **_who(ctx), action="phone_system.users_imported", target_type="phone_system", target_id=ps.id, users=out["ready"])
        db.commit()
        out["phone_system"] = _summary(db, ps)
    return out


# ---- emergency addresses and numbers' state with the carrier ----

TEXT = r"^[^\x00-\x1f\x7f<>]*$"      # no line breaks or control characters: these reach the carrier's 911 email (review M2)


class LocationIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    street: str = Field(min_length=3, max_length=200, pattern=TEXT)
    unit: str = Field("", max_length=60, pattern=TEXT)
    city: str = Field(min_length=2, max_length=100, pattern=TEXT)
    state: str = Field(pattern=r"^[A-Z]{2}$")
    zip: str = Field(pattern=r"^[0-9]{5}(-[0-9]{4})?$")


@router.post("/sites/{site_id}/emergency-locations", status_code=201)
def add_location(site_id: uuid.UUID, body: LocationIn, ctx: Ctx = Depends(require(EMERGENCY, sites=True)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """An emergency address for a site, pending until Photon staff validate it (the R1 staff queue, ARCHITECTURE §11)."""
    if not ctx.can(EMERGENCY, site_id) or str(site_id) not in {str(s.id) for s in visible_sites(db, ctx)}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    loc = EmergencyLocation(tenant_id=ctx.tenant_id, site_id=site_id, key=body.key,
                            address=body.model_dump(include={"street", "unit", "city", "state", "zip"}))
    db.add(loc)
    db.flush()
    audit.record(db, **_who(ctx), action="emergency_location.added", target_type="site", target_id=site_id, key=body.key)
    db.commit()
    return _location(loc)


def _location(loc: EmergencyLocation) -> Dict[str, Any]:
    return {"id": str(loc.id), "site_id": str(loc.site_id), "key": loc.key, "address": loc.address, "status": loc.status, "note": loc.note}


@router.get("/emergency")
def emergency(ctx: Ctx = Depends(require(VIEW, sites=True)), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Sites' emergency addresses, each number's 911 registration with the carrier, and the requests in flight (decision 31). A person who
    views only some sites sees those sites' addresses, numbers and request lines (audit VOX-A-5)."""
    locs = db.execute(select(EmergencyLocation).where(EmergencyLocation.tenant_id == ctx.tenant_id).order_by(EmergencyLocation.created_at)).scalars().all()
    nums = db.execute(select(EmergencyNumber).where(EmergencyNumber.tenant_id == ctx.tenant_id).order_by(EmergencyNumber.number)).scalars().all()
    reqs = db.execute(select(CarrierRequest).where(CarrierRequest.tenant_id == ctx.tenant_id).order_by(CarrierRequest.created_at.desc()).limit(20)).scalars().all()
    if not ctx.reach(VIEW).reach_all:
        sites = {s.id for s in visible_sites(db, ctx, VIEW)}
        locs = [x for x in locs if x.site_id in sites]
        mine = {x.id for x in locs}
        nums = [n for n in nums if (n.location_id or n.confirmed_location_id) in mine]
        numbers = {n.number for n in nums}
        reqs = [r for r in ({**_request(r), "items": [i for i in r.items if i["number"] in numbers]} for r in reqs) if r["items"]]
    else:
        reqs = [_request(r) for r in reqs]
    return {"locations": [_location(x) for x in locs],
            "numbers": [{"number": n.number, "status": n.status, "location_id": str(n.location_id) if n.location_id else None,
                         "confirmed_at": n.confirmed_at.isoformat() if n.confirmed_at else None} for n in nums],
            "requests": reqs}


def _request(r: CarrierRequest) -> Dict[str, Any]:
    return {"id": str(r.id), "status": r.status, "items": r.items, "reference": r.reference, "sent_at": r.sent_at.isoformat() if r.sent_at else None}


@router.get("/numbers")
def assigned_numbers(ctx: Ctx = Depends(require(VIEW, sites=True)), db: Session = Depends(get_db)) -> List[Dict[str, str]]:
    """The numbers Photon has assigned to this organization: the only ones its phone system may use (review C2)."""
    return [{"number": n.number, "carrier": n.carrier} for n in
            db.execute(select(HeldNumber).where(HeldNumber.tenant_id == ctx.tenant_id).order_by(HeldNumber.number)).scalars()]
