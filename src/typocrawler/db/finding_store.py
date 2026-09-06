"""Read the check work queue and write findings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Connection, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from typocrawler.db.models import findings, readme_snapshots


def snapshots_to_check(conn: Connection, *, limit: int | None = None):
    """README snapshots not yet run through the checkers, oldest first."""
    stmt = (
        select(
            readme_snapshots.c.id,
            readme_snapshots.c.repo_id,
            readme_snapshots.c.blob_sha,
            readme_snapshots.c.raw_md,
        )
        .where(readme_snapshots.c.checked_at.is_(None))
        .order_by(readme_snapshots.c.id)
    )
    if limit:
        stmt = stmt.limit(limit)
    return conn.execute(stmt).all()


def mark_checked(conn: Connection, snapshot_ids: Sequence[int]) -> None:
    if not snapshot_ids:
        return
    conn.execute(
        update(readme_snapshots)
        .where(readme_snapshots.c.id.in_(snapshot_ids))
        .values(checked_at=datetime.now(UTC))
    )


@dataclass
class FindingRow:
    repo_id: int
    blob_sha: str
    line_no: int
    col: int
    token: str
    suggestion: str
    context_snippet: str
    source: str
    heuristic_score: int


def upsert_findings(conn: Connection, rows: Sequence[FindingRow]) -> int:
    """Insert new findings; refresh ``last_seen_at`` and metadata on ones already recorded."""
    now = datetime.now(UTC)
    for r in rows:
        stmt = sqlite_insert(findings).values(
            repo_id=r.repo_id,
            blob_sha=r.blob_sha,
            line_no=r.line_no,
            col=r.col,
            token=r.token,
            suggestion=r.suggestion,
            context_snippet=r.context_snippet,
            source=r.source,
            heuristic_score=r.heuristic_score,
            first_seen_at=now,
            last_seen_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["repo_id", "token", "line_no", "blob_sha"],
            set_={
                "suggestion": stmt.excluded.suggestion,
                "context_snippet": stmt.excluded.context_snippet,
                "col": stmt.excluded.col,
                "source": stmt.excluded.source,
                "heuristic_score": stmt.excluded.heuristic_score,
                "last_seen_at": stmt.excluded.last_seen_at,
            },
        )
        conn.execute(stmt)
    return len(rows)
