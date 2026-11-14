"""the demo organization (docs/DEMO.md): tenant.demo, the directory's flag, and pbx_instance.simulated, an engine whose phones and calls are
simulated (staging CT 610). A demo organization is placed on and published to a simulated engine only, and a simulated engine takes nobody else.
Expand only: two columns with defaults.

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant", sa.Column("demo", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("pbx_instance", sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("pbx_instance", "simulated")
    op.drop_column("tenant", "demo")
