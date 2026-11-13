"""Photon staff come from the PhotonID directory: `person.is_staff`, and the directory read again once

From this version, Photon staff are the directory's platform administrators (`platform_admin`) and every member, in any role, of partner
Photon (`partners`, slug "photon"), read from each person document (decided 2026-11-13, as PhotonConsole does). `is_platform_admin` now
holds the directory's own flag; `is_staff` is what PhotonVox's platform pages check. The copy already holds the person documents, applied
by the previous version, which ignored the two fields: setting the cursor back to 0 makes the next pull a full snapshot that applies them.

Revision ID: 0006
Revises: 0005
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("person", sa.Column("is_staff", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE sync_state SET cursor = 0")


def downgrade() -> None:
    op.drop_column("person", "is_staff")
