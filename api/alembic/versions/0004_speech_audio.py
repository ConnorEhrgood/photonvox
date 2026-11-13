"""greetings already spoken, cached by voice and text (decision 30); the system's own table

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "speech_audio",
        sa.Column("key", sa.String(32), primary_key=True),
        sa.Column("voice", sa.String(60), nullable=False),
        sa.Column("characters", sa.Integer, nullable=False),
        sa.Column("audio", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON "speech_audio" TO vox_system')
    op.execute('ALTER TABLE "speech_audio" ENABLE ROW LEVEL SECURITY')
    op.execute('CREATE POLICY "speech_audio_system" ON "speech_audio" FOR ALL TO vox_system USING (true) WITH CHECK (true)')


def downgrade() -> None:
    op.drop_table("speech_audio")
