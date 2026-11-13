"""An append-only record of what matters if something goes wrong or someone asks "who did that": every change to a phone system, every phone action
(enroll, move, reboot, reset), every emergency-address change and every staff view, from the steps that add them. Written in the same transaction as
the change, so a change that rolls back leaves no trace and a change that commits always has one. Details never hold secrets."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models import AuditLog


def record(db: Session, *, actor_id: Optional[uuid.UUID], actor_label: str, actor_source: str, action: str,
           tenant_id: Optional[uuid.UUID] = None, target_type: str = "", target_id: Any = "", **detail: Any) -> None:
    # A plain INSERT, not the ORM's: the ORM asks for the new id back (RETURNING), which needs the right to read the row, and the people who write
    # the log (admins) are deliberately not the people who read it (owners).
    db.execute(insert(AuditLog).values(
        tenant_id=tenant_id, actor_person_id=actor_id, actor_label=actor_label[:320], actor_source=actor_source, action=action[:60],
        target_type=target_type[:40], target_id=str(target_id)[:80], detail={k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in detail.items()},
    ))
