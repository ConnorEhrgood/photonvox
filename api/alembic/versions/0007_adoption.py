"""phone_system.adoption: a hand-built domain taken over in place (decision 32, ARCHITECTURE §17); pbx_instance.own_gateways: an engine's own,
hand-built gateways that routing may name and PhotonVox never writes

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("phone_system", sa.Column("adoption", pg.JSONB(), nullable=True))
    op.add_column("pbx_instance", sa.Column("own_gateways", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("pbx_instance", "own_gateways")
    op.drop_column("phone_system", "adoption")
