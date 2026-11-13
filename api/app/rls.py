"""Row-level security: who the database thinks it is talking to.

The API logs in as `vox_app`, which does not own the tables, so Postgres applies the policies from migration 0001 to everything it does. A policy
decides from per-transaction settings: `app.mode` (`user`), `app.person_id` and `app.admin` (platform staff). A session that has not said who it is
has no mode, so every policy fails and it sees nothing: forgetting to set a context loses data, it never leaks it.

The worker and the directory sync log in as `vox_system` instead, which has its own all-access policies on every table. They set no context.
So there are only two ways to see across organizations, both visible in the code: a `SystemSession`, or a platform admin's `as_user`.

The context lives on the session (`db.info`) and is re-applied at the start of every transaction, because a commit ends the transaction the
settings were local to.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import event, text
from sqlalchemy.orm import Session

_SET = text("select set_config('app.mode', :mode, true), set_config('app.person_id', :person_id, true), set_config('app.admin', :admin, true)")
NONE: Dict[str, str] = {"mode": "", "person_id": "", "admin": ""}


def _params(ctx: Optional[Dict[str, str]]) -> Dict[str, str]:
    return {**NONE, **(ctx or {})}


def install(session_factory: Any) -> None:
    """Apply the session's context at the start of every transaction it opens."""
    @event.listens_for(session_factory, "after_begin")
    def _apply(session: Session, transaction: Any, connection: Any) -> None:  # noqa: ARG001
        connection.execute(_SET, _params(session.info.get("rls")))


def as_person(db: Session, person_id: Any, platform_admin: bool = False) -> None:
    ctx = {"mode": "user", "person_id": str(person_id), "admin": "on" if platform_admin else ""}
    db.info["rls"] = ctx
    if db.in_transaction():
        db.execute(_SET, _params(ctx))   # the transaction already open must see it too
