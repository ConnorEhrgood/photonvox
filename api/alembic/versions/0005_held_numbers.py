"""the numbers Photon holds and which organization each is assigned to (security review C2)

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "held_number",
        sa.Column("number", sa.String(16), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True)),
        sa.Column("carrier", sa.String(40), nullable=False, server_default="htc"),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_held_number_tenant_id", "held_number", ["tenant_id"])
    op.execute('GRANT SELECT ON "held_number" TO vox_app')
    op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON "held_number" TO vox_system')
    op.execute('ALTER TABLE "held_number" ENABLE ROW LEVEL SECURITY')
    op.execute('CREATE POLICY "held_number_system" ON "held_number" FOR ALL TO vox_system USING (true) WITH CHECK (true)')
    # An organization's admins see its numbers; Photon staff see the stock too. Only the system (staff routes) assigns.
    op.execute('CREATE POLICY "held_number_read" ON "held_number" FOR SELECT TO vox_app USING (tenant_id IN (SELECT vx_team_tenants()) OR vx_privileged())')


def downgrade() -> None:
    op.drop_table("held_number")
