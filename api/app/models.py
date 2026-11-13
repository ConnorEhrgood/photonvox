"""PhotonVox data model.

The first block is the **directory copy**: organizations, sites, people and their effective access as the PhotonID directory sent them
(`~/projects/photon-suite/ARCHITECTURE.md` §5). Only the sync (the system role) writes it; everything else reads it. The organization is still
called a tenant here, holding the directory's organization id, so RLS and code read like the sister products. The four kinds arrive in any order,
so there are no foreign keys between them (PhotonGuard learned this, its migration 0002).

The second block is PhotonVox's own: the audit log, the engines (instances), phone systems with their versions, what each publish wrote on its
engine (engine objects, engine secrets) and emergency locations. Phones and the rest arrive with the build steps that need them (BUILD-GUIDE §5). Every tenant-owned table has `tenant_id` and a row-level security policy from the migration that creates it; tests/api/test_rls.py
fails if one does not.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Float, Index, Integer, SmallInteger, String, Text, UniqueConstraint, text
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


class PbxInstance(Base):
    """A FusionPBX engine PhotonVox publishes to (ARCHITECTURE §5). Platform-wide: Photon staff see and change it; nothing here is a customer's.
    Its database login and agent secret are sealed (app/crypto.py)."""
    __tablename__ = "pbx_instance"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    region: Mapped[str] = mapped_column(String(40), default="us-east")
    role: Mapped[str] = mapped_column(String(20), default="active")          # active | standby | draining
    hostname: Mapped[str] = mapped_column(String(120))                       # FreeSWITCH's own hostname (part of a cache key)
    database_url_sealed: Mapped[str] = mapped_column(Text, default="")
    agent: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)      # how to reach its vox-agent: {"kind": "http", "url": ...}
    agent_secret_sealed: Mapped[str] = mapped_column(Text, default="")
    # [{key, proxy, addresses}] and, per call class, the upstream keys in Photon's order ({"national": ["htc"], ...}); 911's upstream.
    upstreams: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list)
    routing: Mapped[Dict[str, List[str]]] = mapped_column(JSONB, default=dict)
    emergency_upstream: Mapped[str] = mapped_column(String(60), default="")
    versions: Mapped[Dict[str, str]] = mapped_column(JSONB, default=dict)   # FusionPBX, FreeSWITCH, as last reported
    # Outgoing mail (voicemail to email): {host, port, secure, username, from, from_name}; Postmark's SMTP with a voicemail server's token.
    email: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)
    email_password_sealed: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("role in ('active', 'standby', 'draining')", name="ck_pbx_instance_role"),)


class PhoneSystem(Base):
    """An organization's phone system (decision 4: one per organization): its working draft, where it runs and what is published."""
    __tablename__ = "phone_system"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    domain_name: Mapped[str] = mapped_column(String(200), unique=True)
    domain_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    draft: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)      # the document being built (app/document/model.py)
    draft_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_version: Mapped[Optional[int]] = mapped_column(Integer)       # the version running on the engine, when one is
    # new: nothing published yet | publishing | ready | failed (the last publish failed; the previous version runs) | changed (edited outside)
    status: Mapped[str] = mapped_column(String(20), default="new")
    drift: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)      # the last drift check: {checked_at, changed: [...], missing: [...], extra: [...]}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("status in ('new', 'publishing', 'ready', 'failed', 'changed')", name="ck_phone_system_status"),)


class PhoneSystemVersion(Base):
    """Every publish is a version (ARCHITECTURE §8): the document as published, who and when, and how its check went. Undo publishes an earlier
    version's document again, as a new version."""
    __tablename__ = "phone_system_version"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    phone_system_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    number: Mapped[int] = mapped_column(Integer)
    document: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    note: Mapped[str] = mapped_column(String(200), default="")               # "restored from version 3", "undo after a failed check"
    # queued -> publishing -> ready | failed (and then the previous ready version is restored) ; superseded once a later one is ready
    state: Mapped[str] = mapped_column(String(20), default="queued")
    check: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)      # the synthetic check: [{kind, number, expect, got, ok}]
    error: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    created_by_label: Mapped[str] = mapped_column(String(320), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("phone_system_id", "number", name="uq_phone_system_version_number"),
                      CheckConstraint("state in ('queued', 'publishing', 'ready', 'failed', 'superseded')", name="ck_phone_system_version_state"))


class EngineObject(Base):
    """What the running version wrote on its engine: one row per FusionPBX row, with the hash of PhotonVox's columns. The next publish removes
    what is no longer wanted; the drift check compares against it."""
    __tablename__ = "engine_object"
    phone_system_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(60), primary_key=True)
    object_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    hash: Mapped[str] = mapped_column(String(64))


class EngineSecret(Base):
    """The SIP passwords and voicemail PINs PhotonVox's adapter gave a phone system's rows, sealed. Only the system reads them (to provision
    phones through GDMS and to email a user their PIN); no policy lets the API's role see this table."""
    __tablename__ = "engine_secret"
    phone_system_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    label: Mapped[str] = mapped_column(String(80), primary_key=True)         # "extension:101", "voicemail:101"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    sealed: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmergencyLocation(Base):
    """A site's emergency (911) address (ARCHITECTURE §11). A site gets no phones until one is validated. R1 validates by hand: an admin enters
    it, Photon staff check it and register it with the upstream (a staff queue), until HTC's process is known (BUILD-GUIDE GATE 3b)."""
    __tablename__ = "emergency_location"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    key: Mapped[str] = mapped_column(String(40))                             # what the document's sites refer to ("main", "floor-2")
    address: Mapped[Dict[str, Any]] = mapped_column(JSONB)                   # {street, unit, city, state, zip}
    status: Mapped[str] = mapped_column(String(20), default="pending")       # pending | validated | rejected
    note: Mapped[str] = mapped_column(Text, default="")
    validated_by_label: Mapped[str] = mapped_column(String(320), default="")
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("site_id", "key", name="uq_emergency_location_site_key"),
                      CheckConstraint("status in ('pending', 'validated', 'rejected')", name="ck_emergency_location_status"))


class EmergencyNumber(Base):
    """The 911 address each number the organization holds is registered at with its carrier (Connor, 2026-11-13: Hickory keeps this by hand
    per DID). PhotonVox holds the truth; a change makes a carrier request; the number is shown unconfirmed until the carrier confirms."""
    __tablename__ = "emergency_number"
    number: Mapped[str] = mapped_column(String(16), primary_key=True)              # E.164
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    location_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))   # None: the number is being removed from the carrier's records
    carrier: Mapped[str] = mapped_column(String(40), default="htc")
    status: Mapped[str] = mapped_column(String(20), default="unconfirmed")         # unconfirmed | requested | confirmed
    request_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))    # the open request that will confirm it
    confirmed_location_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))   # what the carrier last confirmed
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (CheckConstraint("status in ('unconfirmed', 'requested', 'confirmed')", name="ck_emergency_number_status"),)


class CarrierRequest(Base):
    """A request to a carrier to add, change or remove numbers' 911 addresses, tracked until it confirms. Hickory: an email (or a ticket) that
    Photon staff mark confirmed when Hickory answers; a carrier with an API later submits and polls through the same record."""
    __tablename__ = "carrier_request"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    carrier: Mapped[str] = mapped_column(String(40), default="htc")
    method: Mapped[str] = mapped_column(String(20), default="email")               # email | ticket | api
    items: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB)                     # [{number, action: add|change|remove, address}]
    status: Mapped[str] = mapped_column(String(20), default="open")                # open (to send) | sent | confirmed | rejected | superseded
    reference: Mapped[str] = mapped_column(String(200), default="")                # the email's message id, the ticket number, the API's id
    note: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closed_by_label: Mapped[str] = mapped_column(String(320), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("status in ('open', 'sent', 'confirmed', 'rejected', 'superseded')", name="ck_carrier_request_status"),
                      CheckConstraint("method in ('email', 'ticket', 'api')", name="ck_carrier_request_method"))
