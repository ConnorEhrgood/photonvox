"""Numbers' 911 addresses with their carrier (ARCHITECTURE §11a, decision 31). CRITICAL module (100% branch coverage): it decides what Hickory is
told about where each number is.

After each publish, `sync_numbers` compares the numbers the organization holds (each at its site's validated emergency location) with what is
registered, and turns any difference into one carrier request. `send_open` emails open requests to the carrier; `close` records the carrier's
answer, and the numbers follow it. A number is unconfirmed from the moment its address differs from what the carrier last confirmed.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import mail
from app.config import settings
from app.models import CarrierRequest, EmergencyLocation, EmergencyNumber, PhoneSystem, Tenant, utcnow


def address_line(a: Mapping[str, Any]) -> str:
    unit = f", {a['unit']}" if a.get("unit") else ""
    return f"{a.get('street', '')}{unit}, {a.get('city', '')}, {a.get('state', '')} {a.get('zip', '')}".strip()


def sync_numbers(db: Session, ps: PhoneSystem, document: Mapping[str, Any], carrier: str = "htc") -> Optional[CarrierRequest]:
    """Register every number of the published document at its site's emergency location; returns the carrier request made, if any."""
    locs = {(str(loc.site_id), loc.key): loc for loc in db.execute(
        select(EmergencyLocation).where(EmergencyLocation.tenant_id == ps.tenant_id, EmergencyLocation.status == "validated")).scalars()}
    desired: Dict[str, EmergencyLocation] = {}
    for number, n in document.get("numbers", {}).items():
        site = document["sites"][n["site"]]
        desired[number] = locs[(n["site"], site["emergency_location"])]       # the compiler refused any site without a validated location
    rows = {r.number: r for r in db.execute(select(EmergencyNumber).where(EmergencyNumber.tenant_id == ps.tenant_id)).scalars()}
    items: List[Dict[str, Any]] = []
    for number, loc in sorted(desired.items()):
        row = rows.get(number)
        if row is None:
            row = EmergencyNumber(number=number, tenant_id=ps.tenant_id, carrier=carrier, status="unconfirmed")
            db.add(row)
        if row.location_id == loc.id and (row.request_id is not None or row.status == "confirmed"):
            continue                                       # already asked for (or confirmed at) this address
        row.location_id = loc.id
        if row.confirmed_location_id == loc.id:
            row.status, row.request_id = "confirmed", None   # moved back to where the carrier has it: nothing to ask
            continue
        row.status = "unconfirmed"
        items.append({"number": number, "action": "change" if row.confirmed_location_id else "add", "address": dict(loc.address)})
    for number, row in sorted(rows.items()):
        if number in desired or (row.location_id is None and row.request_id is not None):
            continue                                       # still held, or its removal already asked for
        pending = db.get(CarrierRequest, row.request_id) if row.request_id else None
        if row.confirmed_location_id is None and (pending is None or pending.status == "open"):
            if pending is not None:                        # never sent: take it out of the request instead of asking twice
                pending.items = [i for i in pending.items if i["number"] != number]
                if not pending.items:
                    pending.status, pending.closed_at, pending.note = "superseded", utcnow(), "nothing left to ask"
            db.delete(row)                                 # the carrier never had it: nothing to remove there
            continue
        row.location_id, row.status = None, "unconfirmed"  # the carrier has it, or may (a request was sent): ask for its removal
        items.append({"number": number, "action": "remove", "address": None})
    if not items:
        db.flush()
        return None
    asked = {i["number"] for i in items}
    for old in db.execute(select(CarrierRequest).where(CarrierRequest.tenant_id == ps.tenant_id, CarrierRequest.status == "open")).scalars():
        items += [i for i in old.items if i["number"] not in asked]     # an unsent request is folded into the new one
        asked |= {i["number"] for i in old.items}
        old.status, old.closed_at, old.note = "superseded", utcnow(), "folded into a later request"
    req = CarrierRequest(id=uuid.uuid4(), tenant_id=ps.tenant_id, carrier=carrier, method="email", items=sorted(items, key=lambda i: i["number"]))
    db.add(req)
    db.flush()
    for row in db.execute(select(EmergencyNumber).where(EmergencyNumber.tenant_id == ps.tenant_id, EmergencyNumber.number.in_(asked))).scalars():
        row.request_id = req.id
    return req


def compose(req: CarrierRequest, organization: str) -> Dict[str, str]:
    """The email to Hickory: one line per number, the address as it should be in the 911 records, the request's id to reply about."""
    lines = []
    for i in req.items:
        what = {"add": "Add", "change": "Change", "remove": "Remove"}[i["action"]]
        lines.append(f"  {what:7} {i['number']}" + (f"  at  {address_line(i['address'])}" if i["address"] else "  (no longer in service with us)"))
    ref = str(req.id)[:8]
    body = (f"Hello,\n\nPlease update the 911 address records for these numbers ({organization}):\n\n" + "\n".join(lines)
            + f"\n\nPlease reply to confirm when the records are updated, quoting reference {ref}.\n\nThank you,\nPhoton (PhotonVox)\n")
    return {"subject": f"911 address update {ref}: {organization} ({len(req.items)} number{'s' if len(req.items) != 1 else ''})", "body": body}


def send_open(db: Session, sender: mail.Sender = mail.send) -> int:
    """Email every open request to the carrier's contact. Without an address or a mail token, requests stay open for staff to send by hand."""
    if not settings.htc_e911_email:
        return 0
    sent = 0
    for req in db.execute(select(CarrierRequest).where(CarrierRequest.status == "open", CarrierRequest.method == "email")).scalars().all():
        tenant = db.get(Tenant, req.tenant_id)
        msg = compose(req, tenant.name if tenant else str(req.tenant_id))
        ref = sender(settings.htc_e911_email, msg["subject"], msg["body"])
        if ref is None:
            continue
        mark_sent(db, req, ref)
        sent += 1
    db.commit()
    return sent


def mark_sent(db: Session, req: CarrierRequest, reference: str, method: Optional[str] = None) -> None:
    """Sent: by email (the message id), or by staff through the carrier's portal (the ticket number)."""
    req.status, req.sent_at, req.reference = "sent", utcnow(), reference[:200]
    if method:
        req.method = method
    for row in _numbers(db, req):
        row.status = "requested"


def close(db: Session, req: CarrierRequest, confirmed: bool, who_label: str, note: str = "") -> None:
    """The carrier's answer. Confirmed: its numbers are confirmed at the address asked for (a removed number is forgotten). Rejected: they stay
    unconfirmed and a new request is needed (after the address is corrected)."""
    req.status, req.closed_at, req.closed_by_label, req.note = ("confirmed" if confirmed else "rejected"), utcnow(), who_label[:320], note
    for row in _numbers(db, req):
        if not confirmed:
            row.status, row.request_id = "unconfirmed", None
        elif row.location_id is None:
            db.delete(row)
        else:
            row.status, row.confirmed_location_id, row.confirmed_at, row.request_id = "confirmed", row.location_id, utcnow(), None


def _numbers(db: Session, req: CarrierRequest) -> List[EmergencyNumber]:
    return list(db.execute(select(EmergencyNumber).where(EmergencyNumber.request_id == req.id)).scalars())
