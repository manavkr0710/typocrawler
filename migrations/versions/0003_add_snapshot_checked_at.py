"""add readme_snapshots.checked_at

Marks when a snapshot has been run through the spell-checkers, so ``check`` can resume and
skip work it has already done.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("readme_snapshots") as batch:
        batch.add_column(sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("readme_snapshots") as batch:
        batch.drop_column("checked_at")
