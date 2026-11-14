"""integration tokens (PhotonEntry's door stations and door calls, scope vox:entry) and how phones reach each engine over SIP

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_token",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("label", sa.String(100), nullable=False, server_default=""),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("hint", sa.String(8), nullable=False, server_default=""),
        sa.Column("created_by", pg.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_integration_token_tenant_id", "integration_token", ["tenant_id"])
    op.execute('GRANT SELECT, INSERT, UPDATE ON "integration_token" TO vox_app')
    op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON "integration_token" TO vox_system')
    op.execute('ALTER TABLE "integration_token" ENABLE ROW LEVEL SECURITY')
    op.execute('CREATE POLICY "integration_token_system" ON "integration_token" FOR ALL TO vox_system USING (true) WITH CHECK (true)')
    # The organization's own people (the capability vox.entry.manage is checked by the route); the integration endpoints use the system.
    op.execute('CREATE POLICY "integration_token_team" ON "integration_token" FOR ALL TO vox_app '
               'USING (tenant_id IN (SELECT vx_team_tenants()) OR vx_privileged()) WITH CHECK (tenant_id IN (SELECT vx_team_tenants()) OR vx_privileged())')
    # How a device reaches the engine over SIP, for PhotonEntry's intercoms: {"port", "transport", "outbound_proxy"}; empty: 5060/udp, no proxy.
    op.add_column("pbx_instance", sa.Column("sip_access", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("pbx_instance", "sip_access")
    op.drop_table("integration_token")
