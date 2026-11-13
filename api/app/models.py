"""PhotonVox data model.

The first block is the **directory copy**: organizations, sites, people and their effective access as the PhotonID directory sent them
(`~/projects/photon-suite/ARCHITECTURE.md` §5). Only the sync (the system role) writes it; everything else reads it. The organization is still
called a tenant here, holding the directory's organization id, so RLS and code read like the sister products. The four kinds arrive in any order,
so there are no foreign keys between them (PhotonGuard learned this, its migration 0002).

The second block is PhotonVox's own: the audit log. Phone systems, instances, phones and the rest arrive with the build steps that need them
(BUILD-GUIDE §5). Every tenant-owned table has `tenant_id` and a row-level security policy from the migration that creates it; tests/api/test_rls.py
fails if one does not.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Float, Index, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---- the directory copy (written by the sync only) ----

class Tenant(Base):
    """An organization entitled to PhotonVox. `id` is the directory's organization id, the same in every product."""
    __tablename__ = "tenant"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    partner_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    plan_key: Mapped[str] = mapped_column(String(60), default="")
    # active | suspended | removed. "removed" = no longer entitled to PhotonVox: the row stays, access ends.
    status: Mapped[str] = mapped_column(String(20), default="active")
    # Where the organization's data lives (suite §5); PhotonVox places new phone systems on an instance in this region (ARCHITECTURE §5).
    home_region: Mapped[str] = mapped_column(String(40), default="us-east")
    # The keys of every product the organization has switched on (the directory's `products`, sorted).
    products: Mapped[List[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (CheckConstraint("status in ('active', 'suspended', 'removed')", name="ck_tenant_status"),)


class Site(Base):
    __tablename__ = "site"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)   # unique across the suite, never changes
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(Text, default="")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="active")
    __table_args__ = (CheckConstraint("status in ('active', 'removed')", name="ck_site_status"),)


class Person(Base):
    """One per PhotonID account: `sub` is the OIDC subject. A person invited but not yet signed in may have none."""
    __tablename__ = "person"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    sub: Mapped[Optional[str]] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Photon staff. The directory's documents carry no platform flag; staff are also named in PLATFORM_ADMIN_SUBS.
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class Access(Base):
    """A person's effective access in one organization, as the directory computed it."""
    __tablename__ = "access"
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    role: Mapped[str] = mapped_column(String(20))
    scope_all: Mapped[bool] = mapped_column(Boolean, default=True)
    site_ids: Mapped[List[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list, server_default=text("'{}'"))
    source: Mapped[str] = mapped_column(String(10), default="direct")   # direct | partner
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Lower-ranked entries that cover the rest: [{role, scope: {type, site_ids?}, source}] (the directory's `others`).
    others: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list, server_default=text("'[]'"))
    __table_args__ = (
        CheckConstraint("role in ('owner', 'admin', 'user')", name="ck_access_role"),
        CheckConstraint("source in ('direct', 'partner')", name="ck_access_source"),
        CheckConstraint("scope_all or cardinality(site_ids) > 0", name="ck_access_scope"),
        Index("ix_access_tenant", "tenant_id"),
    )


class SyncState(Base):
    """One row: where we are in the directory's change feed."""
    __tablename__ = "sync_state"
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    cursor: Mapped[int] = mapped_column(BigInteger, default=0)
    last_pull_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_ok_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    roles_published_hash: Mapped[str] = mapped_column(String(64), default="")
    __table_args__ = (CheckConstraint("id = 1", name="ck_sync_state_single"),)


# ---- PhotonVox's own ----

class AuditLog(Base):
    """Append-only: the app and system roles can add and read rows, never change or delete them. Details never hold secrets."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    actor_person_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    actor_label: Mapped[str] = mapped_column(String(320), default="")
    # How the actor came to have the access they used: direct | partner | platform. Customers see partner staff's actions as "Partner support".
    actor_source: Mapped[str] = mapped_column(String(10), default="direct")
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str] = mapped_column(String(40), default="")
    target_id: Mapped[str] = mapped_column(String(80), default="")
    detail: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    # No INSERT ... RETURNING: Postgres allows it only for rows the inserter may also read, and the people who write the log (admins) are not the
    # people who read it (owners).
    __table_args__ = (Index("ix_audit_tenant_at", "tenant_id", "at"), {"implicit_returning": False})
