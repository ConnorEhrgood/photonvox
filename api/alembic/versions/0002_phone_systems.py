"""engines, phone systems and their versions, what each publish wrote (engine objects and secrets), emergency locations, numbers' 911
registrations with their carrier and the requests that change them

Revision ID: 0002
Revises: 0001

Policies for `vox_app` (the API): phone systems, versions and engine objects are the organization's admins' and owners' (`vx_team_tenants()`,
the same people who see its members) and Photon staff's; the API creates versions, only the worker (`vox_system`) moves them along. Engine
secrets have no app policy at all: the API never reads a SIP password. Instances are Photon staff's only.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TEAM = "(tenant_id IN (SELECT vx_team_tenants()) OR vx_privileged())"
APP_POLICIES = {
    "pbx_instance": [("read", "SELECT", "vx_privileged()", None), ("add", "INSERT", None, "vx_privileged()"),
                     ("change", "UPDATE", "vx_privileged()", "vx_privileged()")],
    "phone_system": [("read", "SELECT", TEAM, None), ("add", "INSERT", None, TEAM), ("change", "UPDATE", TEAM, TEAM)],
    "phone_system_version": [("read", "SELECT", TEAM, None), ("add", "INSERT", None, TEAM)],
    "engine_object": [("read", "SELECT", TEAM, None)],
    "emergency_location": [("read", "SELECT", TEAM, None), ("add", "INSERT", None, TEAM)],     # staff validate as the system
    "engine_secret": [],
    # Staff confirm with the carrier; admins see their numbers' state and their requests.
    "emergency_number": [("read", "SELECT", TEAM, None)],
    "carrier_request": [("read", "SELECT", TEAM, None)],       # staff record the carrier's answer as the system
}
APP_GRANTS = {"pbx_instance": "SELECT, INSERT, UPDATE", "phone_system": "SELECT, INSERT, UPDATE", "phone_system_version": "SELECT, INSERT",
              "engine_object": "SELECT", "emergency_location": "SELECT, INSERT", "emergency_number": "SELECT",
              "carrier_request": "SELECT"}
SYSTEM_GRANTS = {t: "SELECT, INSERT, UPDATE, DELETE" for t in APP_POLICIES}


def upgrade() -> None:
    uuid_ = pg.UUID(as_uuid=True)
    now = sa.text("now()")
    ts = lambda name, **kw: sa.Column(name, sa.DateTime(timezone=True), **kw)  # noqa: E731
    op.create_table(
        "pbx_instance",
        sa.Column("id", uuid_, primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("region", sa.String(40), nullable=False, server_default="us-east"),
        sa.Column("role", sa.String(20), nullable=False, server_default="active"),
        sa.Column("hostname", sa.String(120), nullable=False),
        sa.Column("database_url_sealed", sa.Text, nullable=False, server_default=""),
        sa.Column("agent", pg.JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("agent_secret_sealed", sa.Text, nullable=False, server_default=""),
        sa.Column("upstreams", pg.JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("routing", pg.JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("emergency_upstream", sa.String(60), nullable=False, server_default=""),
        sa.Column("versions", pg.JSONB, nullable=False, server_default=sa.text("'{}'")),
        ts("created_at", nullable=False, server_default=now),
        sa.CheckConstraint("role in ('active', 'standby', 'draining')", name="ck_pbx_instance_role"),
    )
    op.create_table(
        "phone_system",
        sa.Column("id", uuid_, primary_key=True),
        sa.Column("tenant_id", uuid_, nullable=False, unique=True),
        sa.Column("instance_id", uuid_, nullable=False),
        sa.Column("domain_name", sa.String(200), nullable=False, unique=True),
        sa.Column("domain_uuid", uuid_, nullable=False, unique=True),
        sa.Column("draft", pg.JSONB, nullable=False, server_default=sa.text("'{}'")),
        ts("draft_updated_at", nullable=False, server_default=now),
        sa.Column("published_version", sa.Integer),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("drift", pg.JSONB, nullable=False, server_default=sa.text("'{}'")),
        ts("created_at", nullable=False, server_default=now),
        sa.CheckConstraint("status in ('new', 'publishing', 'ready', 'failed', 'changed')", name="ck_phone_system_status"),
    )
    op.create_table(
        "phone_system_version",
        sa.Column("id", uuid_, primary_key=True),
        sa.Column("tenant_id", uuid_, nullable=False),
        sa.Column("phone_system_id", uuid_, nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("document", pg.JSONB, nullable=False),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("state", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("check", pg.JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("created_by", uuid_),
        sa.Column("created_by_label", sa.String(320), nullable=False, server_default=""),
        ts("created_at", nullable=False, server_default=now),
        ts("published_at"),
        sa.UniqueConstraint("phone_system_id", "number", name="uq_phone_system_version_number"),
        sa.CheckConstraint("state in ('queued', 'publishing', 'ready', 'failed', 'superseded')", name="ck_phone_system_version_state"),
    )
    op.create_index("ix_phone_system_version_tenant_id", "phone_system_version", ["tenant_id"])
    op.create_table(
        "engine_object",
        sa.Column("phone_system_id", uuid_, primary_key=True),
        sa.Column("table_name", sa.String(60), primary_key=True),
        sa.Column("object_uuid", uuid_, primary_key=True),
        sa.Column("tenant_id", uuid_, nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_engine_object_tenant_id", "engine_object", ["tenant_id"])
    op.create_table(
        "engine_secret",
        sa.Column("phone_system_id", uuid_, primary_key=True),
        sa.Column("label", sa.String(80), primary_key=True),
        sa.Column("tenant_id", uuid_, nullable=False),
        sa.Column("sealed", sa.Text, nullable=False),
        ts("created_at", nullable=False, server_default=now),
    )
    op.create_index("ix_engine_secret_tenant_id", "engine_secret", ["tenant_id"])
    op.create_table(
        "emergency_location",
        sa.Column("id", uuid_, primary_key=True),
        sa.Column("tenant_id", uuid_, nullable=False),
        sa.Column("site_id", uuid_, nullable=False),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("address", pg.JSONB, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("validated_by_label", sa.String(320), nullable=False, server_default=""),
        ts("validated_at"),
        ts("created_at", nullable=False, server_default=now),
        sa.UniqueConstraint("site_id", "key", name="uq_emergency_location_site_key"),
        sa.CheckConstraint("status in ('pending', 'validated', 'rejected')", name="ck_emergency_location_status"),
    )
    op.create_index("ix_emergency_location_tenant_id", "emergency_location", ["tenant_id"])
    op.create_table(
        "emergency_number",
        sa.Column("number", sa.String(16), primary_key=True),
        sa.Column("tenant_id", uuid_, nullable=False),
        sa.Column("location_id", uuid_),
        sa.Column("carrier", sa.String(40), nullable=False, server_default="htc"),
        sa.Column("status", sa.String(20), nullable=False, server_default="unconfirmed"),
        sa.Column("request_id", uuid_),
        sa.Column("confirmed_location_id", uuid_),
        ts("confirmed_at"),
        ts("updated_at", nullable=False, server_default=now),
        sa.CheckConstraint("status in ('unconfirmed', 'requested', 'confirmed')", name="ck_emergency_number_status"),
    )
    op.create_index("ix_emergency_number_tenant_id", "emergency_number", ["tenant_id"])
    op.create_table(
        "carrier_request",
        sa.Column("id", uuid_, primary_key=True),
        sa.Column("tenant_id", uuid_, nullable=False),
        sa.Column("carrier", sa.String(40), nullable=False, server_default="htc"),
        sa.Column("method", sa.String(20), nullable=False, server_default="email"),
        sa.Column("items", pg.JSONB, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("reference", sa.String(200), nullable=False, server_default=""),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        ts("sent_at"),
        ts("closed_at"),
        sa.Column("closed_by_label", sa.String(320), nullable=False, server_default=""),
        ts("created_at", nullable=False, server_default=now),
        sa.CheckConstraint("status in ('open', 'sent', 'confirmed', 'rejected', 'superseded')", name="ck_carrier_request_status"),
        sa.CheckConstraint("method in ('email', 'ticket', 'api')", name="ck_carrier_request_method"),
    )
    op.create_index("ix_carrier_request_tenant_id", "carrier_request", ["tenant_id"])

    for table, grants in APP_GRANTS.items():
        op.execute(f'GRANT {grants} ON "{table}" TO vox_app')
    for table, grants in SYSTEM_GRANTS.items():
        op.execute(f'GRANT {grants} ON "{table}" TO vox_system')
    for table in SYSTEM_GRANTS:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY "{table}_system" ON "{table}" FOR ALL TO vox_system USING (true) WITH CHECK (true)')
    for table, pols in APP_POLICIES.items():
        for name, cmd, using, check in pols:
            clause = (f"USING ({using}) " if using else "") + (f"WITH CHECK ({check})" if check else "")
            op.execute(f'CREATE POLICY "{table}_{name}" ON "{table}" FOR {cmd} TO vox_app {clause}')


def downgrade() -> None:
    for table in reversed(list(SYSTEM_GRANTS)):
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
