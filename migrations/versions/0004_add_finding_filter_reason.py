"""add findings.filter_reason

Records why the heuristic pass rejected a finding (``acronym``, ``allowlist``, ...) — kept so
the dashboard can show what was filtered and why, and so rules stay debuggable.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-07

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Guard against "duplicate column" on a from-scratch db, whose 0001 already creates this
    # column since create_all uses the current models.py.
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("findings")}
    if "filter_reason" not in cols:
        with op.batch_alter_table("findings") as batch:
            batch.add_column(sa.Column("filter_reason", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("findings")}
    if "filter_reason" in cols:
        with op.batch_alter_table("findings") as batch:
            batch.drop_column("filter_reason")
