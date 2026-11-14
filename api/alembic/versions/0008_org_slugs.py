"""tenant.slug and tenant.former_slugs: each organization's address in every Photon product (/org/<slug>/), from the directory; the directory
read again once so the copy has them. pbx_instance.dial_formats: how each upstream wants North American numbers

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant", sa.Column("slug", sa.String(63), nullable=True))
    op.add_column("tenant", sa.Column("former_slugs", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.execute("UPDATE sync_state SET cursor = 0")
    op.add_column("pbx_instance", sa.Column("dial_formats", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("pbx_instance", "dial_formats")
    op.drop_column("tenant", "former_slugs")
    op.drop_column("tenant", "slug")
