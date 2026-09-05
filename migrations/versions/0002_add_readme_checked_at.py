"""add repos.readme_checked_at

Tracks when a repo's README was last fetched, separately from ``last_checked_at`` (which
discovery already sets), so ``fetch`` can tell which repos still need a README pull.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("repos") as batch:
        batch.add_column(sa.Column("readme_checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("repos") as batch:
        batch.drop_column("readme_checked_at")
