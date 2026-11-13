"""an instance's outgoing mail (voicemail to email through Postmark's SMTP): host, port, security, user, sender; the password sealed

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pbx_instance", sa.Column("email", pg.JSONB, nullable=False, server_default=sa.text("'{}'")))
    op.add_column("pbx_instance", sa.Column("email_password_sealed", sa.Text, nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("pbx_instance", "email_password_sealed")
    op.drop_column("pbx_instance", "email")
