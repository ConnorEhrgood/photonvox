"""directory copy, audit log; the three database roles; row-level security

Revision ID: 0001
Revises:

Roles: the OWNER running this migration owns the tables and is never used by the app. `vox_app` is the API's login: every policy below applies to
it. `vox_system` is the worker's and the directory sync's: it has its own all-access policies and cannot change the schema. A session with no
`app.mode` set sees nothing through `vox_app`.

The directory copy follows PhotonGuard's after its migration 0002: no foreign keys between the four kinds (they arrive in any order), `access.others`
for the directory's lower-ranked entries (a person's role at a site is the strongest entry that covers it), `tenant.products`.
"""
import os
import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

FUNCTIONS = [
    "CREATE FUNCTION vx_mode() RETURNS text LANGUAGE sql STABLE AS $$ SELECT coalesce(current_setting('app.mode', true), '') $$",
    "CREATE FUNCTION vx_pid() RETURNS uuid LANGUAGE sql STABLE AS $$ "
    "SELECT CASE WHEN vx_mode() = 'user' THEN nullif(current_setting('app.person_id', true), '')::uuid END $$",
    "CREATE FUNCTION vx_privileged() RETURNS boolean LANGUAGE sql STABLE AS $$ "
    "SELECT vx_mode() = 'user' AND coalesce(current_setting('app.admin', true), '') = 'on' $$",
    # The helpers below read the access table on the policies' behalf, so they run as the owner (SECURITY DEFINER) and do not recurse into its policy.
    # A grant that has expired counts for nothing, whatever the directory has synced since.
    "CREATE FUNCTION vx_my_tenants() RETURNS SETOF uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$ "
    "SELECT tenant_id FROM access WHERE person_id = vx_pid() AND (expires_at IS NULL OR expires_at > now()) $$",
    # Admins and owners: they see their organization's people. (A partner technician's admin comes through the partner grant: the same row.)
    "CREATE FUNCTION vx_team_tenants() RETURNS SETOF uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$ "
    "SELECT tenant_id FROM access WHERE person_id = vx_pid() AND role IN ('admin', 'owner') AND (expires_at IS NULL OR expires_at > now()) $$",
    "CREATE FUNCTION vx_owner_tenants() RETURNS SETOF uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$ "
    "SELECT tenant_id FROM access WHERE person_id = vx_pid() AND role = 'owner' AND (expires_at IS NULL OR expires_at > now()) $$",
    "CREATE FUNCTION vx_my_sites() RETURNS SETOF uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$ "
    "SELECT s.id FROM site s JOIN access a ON a.tenant_id = s.tenant_id WHERE a.person_id = vx_pid() "
    "AND (a.expires_at IS NULL OR a.expires_at > now()) AND s.status = 'active' AND (a.scope_all OR s.id = ANY (a.site_ids) OR EXISTS ("
    "SELECT 1 FROM jsonb_array_elements(a.others) o WHERE o->'scope'->>'type' = 'all' OR (o->'scope'->'site_ids') ? s.id::text)) $$",
    "CREATE FUNCTION vx_team_people() RETURNS SETOF uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$ "
    "SELECT person_id FROM access WHERE tenant_id IN (SELECT vx_team_tenants()) $$",
]
FUNCTION_NAMES = ["vx_team_people()", "vx_my_sites()", "vx_owner_tenants()", "vx_team_tenants()", "vx_my_tenants()", "vx_privileged()", "vx_pid()", "vx_mode()"]

TEAM = "tenant_id IN (SELECT vx_team_tenants())"
# table -> [(policy name, command, USING, WITH CHECK or None)], all for vox_app. Permissive policies for one command are OR'd together.
APP_POLICIES = {
    "tenant": [("read", "SELECT", "vx_privileged() OR id IN (SELECT vx_my_tenants())", None)],
    "site": [("read", "SELECT", "id IN (SELECT vx_my_sites())", None)],
    "person": [("read", "SELECT", "id = vx_pid() OR id IN (SELECT vx_team_people())", None)],
    "access": [("read", "SELECT", f"person_id = vx_pid() OR {TEAM}", None)],
    "sync_state": [],     # the sync's own: no policy for the app role, so it sees nothing
    "audit_log": [
        ("write", "INSERT", None, "vx_mode() = 'user' AND actor_person_id = vx_pid() AND (tenant_id IS NULL OR tenant_id IN (SELECT vx_my_tenants()))"),
        ("read", "SELECT", "tenant_id IN (SELECT vx_owner_tenants()) OR (tenant_id IS NULL AND vx_privileged())", None),
    ],
}
APP_GRANTS = {"tenant": "SELECT", "site": "SELECT", "person": "SELECT", "access": "SELECT", "audit_log": "SELECT, INSERT"}
SYSTEM_GRANTS = {
    "tenant": "SELECT, INSERT, UPDATE, DELETE", "site": "SELECT, INSERT, UPDATE, DELETE", "person": "SELECT, INSERT, UPDATE, DELETE",
    "access": "SELECT, INSERT, UPDATE, DELETE", "sync_state": "SELECT, INSERT, UPDATE", "audit_log": "SELECT, INSERT",
}


def _password(var: str) -> str:
    value = os.environ.get(var, "")
    if value and not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", value):
        raise RuntimeError(f"{var} must be 16 to 128 letters, digits, '-' or '_'")
    return value


def _role(name: str, password: str) -> None:
    op.execute(f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{name}') THEN "
               f"CREATE ROLE {name} NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOLOGIN; END IF; END $$")
    if password:
        op.execute(f"ALTER ROLE {name} LOGIN PASSWORD '{password}'")


def upgrade() -> None:
    _role("vox_app", _password("APP_DB_PASSWORD"))
    _role("vox_system", _password("SYSTEM_DB_PASSWORD"))

    uuid_ = pg.UUID(as_uuid=True)
    now = sa.text("now()")
    op.create_table(
        "tenant",
        sa.Column("id", uuid_, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("partner_id", uuid_),
        sa.Column("plan_key", sa.String(60), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("home_region", sa.String(40), nullable=False, server_default="us-east"),
        sa.Column("products", pg.JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint("status in ('active', 'suspended', 'removed')", name="ck_tenant_status"),
    )
    op.create_table(
        "site",
        sa.Column("id", uuid_, primary_key=True),
        sa.Column("tenant_id", uuid_, nullable=False),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.Text, nullable=False, server_default=""),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("latitude", sa.Float),
        sa.Column("longitude", sa.Float),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.CheckConstraint("status in ('active', 'removed')", name="ck_site_status"),
    )
    op.create_index("ix_site_tenant_id", "site", ["tenant_id"])
    op.create_table(
        "person",
        sa.Column("id", uuid_, primary_key=True),
        sa.Column("sub", sa.String(200), unique=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("email", sa.String(320), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_platform_admin", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "access",
        sa.Column("person_id", uuid_, primary_key=True),
        sa.Column("tenant_id", uuid_, primary_key=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("scope_all", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("site_ids", pg.ARRAY(uuid_), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source", sa.String(10), nullable=False, server_default="direct"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("others", pg.JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.CheckConstraint("role in ('owner', 'admin', 'user')", name="ck_access_role"),
        sa.CheckConstraint("source in ('direct', 'partner')", name="ck_access_source"),
        sa.CheckConstraint("scope_all or cardinality(site_ids) > 0", name="ck_access_scope"),
    )
    op.create_index("ix_access_tenant", "access", ["tenant_id"])
    op.create_table(
        "sync_state",
        sa.Column("id", sa.SmallInteger, primary_key=True, server_default="1"),
        sa.Column("cursor", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("last_pull_at", sa.DateTime(timezone=True)),
        sa.Column("last_ok_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
        sa.Column("roles_published_hash", sa.String(64), nullable=False, server_default=""),
        sa.CheckConstraint("id = 1", name="ck_sync_state_single"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("tenant_id", uuid_),
        sa.Column("actor_person_id", uuid_),
        sa.Column("actor_label", sa.String(320), nullable=False, server_default=""),
        sa.Column("actor_source", sa.String(10), nullable=False, server_default="direct"),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False, server_default=""),
        sa.Column("target_id", sa.String(80), nullable=False, server_default=""),
        sa.Column("detail", pg.JSONB, nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_audit_tenant_at", "audit_log", ["tenant_id", "at"])

    for f in FUNCTIONS:
        op.execute(f)
    op.execute("GRANT USAGE ON SCHEMA public TO vox_app, vox_system")
    op.execute("REVOKE ALL ON alembic_version FROM vox_app, vox_system")
    for table, grants in APP_GRANTS.items():
        op.execute(f'GRANT {grants} ON "{table}" TO vox_app')
    for table, grants in SYSTEM_GRANTS.items():
        op.execute(f'GRANT {grants} ON "{table}" TO vox_system')
    op.execute("GRANT USAGE ON SEQUENCE audit_log_id_seq TO vox_app, vox_system")
    op.execute("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO vox_app, vox_system")

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
    for f in FUNCTION_NAMES:
        op.execute(f"DROP FUNCTION IF EXISTS {f}")
    # The roles are left in place: other databases on the cluster may use them.
