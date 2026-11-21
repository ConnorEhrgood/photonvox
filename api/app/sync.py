"""Keeping our copy of the directory current: pull the change feed, resolve a first sign-in, publish our roles.

All of this runs as the system role, with the vendored reference client (photonid_directory_client) and our `DbProjection`. Sign-in and authorization
never call the directory; they read our copy. If the directory is down, this fails quietly (the error is kept in `sync_state` for monitoring) and only
admin changes made there wait.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import roles
from app.config import settings
from app.directory.projection import BadDocument, DbProjection
from app.models import Person, SyncState
from photonid_directory_client import DirectoryClient, DirectoryError


log = logging.getLogger("photonvox.sync")

LOCK_KEY = 7_101_001          # advisory lock: only one pull at a time, across the API and the worker

# Builds a directory client over a projection. `None` where no directory is configured (a developer's machine with nothing to sync from).
DirectoryFactory = Callable[..., DirectoryClient]


@dataclass(frozen=True)
class PullResult:
    ok: bool
    applied: int = 0
    cursor: int = 0
    busy: bool = False
    error: Optional[str] = None


def _state(db: Session) -> SyncState:
    state = db.get(SyncState, 1)
    if state is None:
        state = SyncState(id=1, cursor=0)
        db.add(state)
        db.flush()
    return state


def pull(db: Session, make_client: DirectoryFactory, now: datetime) -> PullResult:
    """One pass over the change feed, from where we left off. `db` is a system session; this commits."""
    got = db.execute(text("select pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY}).scalar()
    if not got:
        db.rollback()
        return PullResult(ok=True, busy=True)
    state = _state(db)
    state.last_pull_at = now
    try:
        result = make_client(DbProjection(db)).sync_once()
        state = _state(db)
        state.last_ok_at, state.last_error = now, None
        db.commit()
        return PullResult(ok=True, applied=result.changes, cursor=result.cursor)
    except (DirectoryError, BadDocument, KeyError, TypeError, ValueError, SQLAlchemyError) as e:
        # A change our copy cannot take (a constraint, a serialization failure) is recorded like any other failure (audit VOX-A-11): the
        # status line and the platform page show that the copy has stopped, instead of only the worker's log.
        db.rollback()
        message = f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}"[:500]
        log.warning("directory pull failed: %s", message)
        state = _state(db)
        state.last_pull_at, state.last_error = now, message
        db.commit()
        return PullResult(ok=False, error=message)


def resolve(db: Session, make_client: DirectoryFactory, sub: str, timeout_s: float) -> bool:
    """A sign-in from a `sub` we do not hold: ask the directory about that person and, if it knows them, bring the copy up to date with a pull (the
    resolved documents are never written into the copy directly: they may be older than what a pull has applied). True if the person is now known.
    Raises DirectoryError if the directory could not answer in time (the caller says "your access is being set up")."""
    if make_client(DbProjection(db), timeout_s=timeout_s).resolve(sub) is None:
        return False
    result = pull(db, make_client, datetime.now().astimezone())
    if not result.ok and not result.busy:
        raise DirectoryError(result.error or "the pull after resolving failed")
    return db.execute(select(Person.id).where(Person.sub == sub)).first() is not None


def publish_roles(db: Session, make_client: DirectoryFactory) -> bool:
    """Tell the directory our role catalog, if it has changed since it last accepted it. True if it was sent."""
    state = _state(db)
    wanted = roles.catalog_hash()
    if state.roles_published_hash == wanted:
        db.rollback()
        return False
    make_client(DbProjection(db)).publish_roles(settings.directory_product, roles.catalog()["roles"])
    state.roles_published_hash = wanted
    db.commit()
    return True
