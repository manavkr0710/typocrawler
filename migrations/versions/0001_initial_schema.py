"""initial schema

Baseline migration: creates every table from the Core metadata. Subsequent migrations use
explicit ``op`` directives (autogenerate compares the live DB against the same metadata).

Revision ID: 0001
Revises:
Create Date: 2026-09-03

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from typocrawler.db.models import metadata

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    metadata.create_all(op.get_bind())


def downgrade() -> None:
    metadata.drop_all(op.get_bind())
