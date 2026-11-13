from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import rls
from app.config import settings

# The API's connection: `vox_app`, subject to row-level security.
engine = create_engine(settings.database_url, pool_pre_ping=True)
# The system connection: `vox_system`, for the worker, the directory sync and resolving a first sign-in. Never handed to a route's own queries.
system_engine = create_engine(settings.system_database_url or settings.database_url, pool_pre_ping=True)
# The database OWNER: migrations and test set-up only. The app never uses it, because the owner bypasses row-level security.
owner_engine = create_engine(settings.migrate_database_url or settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
SystemSession = sessionmaker(bind=system_engine, autoflush=False, expire_on_commit=False)
rls.install(SessionLocal)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
