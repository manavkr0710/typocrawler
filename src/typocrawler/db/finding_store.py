"""Read the check work queue and write findings."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Connection, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from typocrawler.check.heuristics import classify
from typocrawler.db.models import findings, readme_snapshots

_LOCKED = ("confirmed", "fixed")  # human/LLM verdicts the heuristic pass must not overwrite


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
    status: str = "new"
    filter_reason: str = field(default="")


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
            filter_reason=r.filter_reason or None,
            status=r.status,
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
                "filter_reason": stmt.excluded.filter_reason,
                "status": stmt.excluded.status,
                "last_seen_at": stmt.excluded.last_seen_at,
            },
        )
        conn.execute(stmt)
    return len(rows)


def reclassify(conn: Connection, allowlist: set[str]) -> Counter[str]:
    """Re-run the heuristic rules over every finding not already confirmed/fixed.

    Idempotent — safe to re-run after editing ``config/allowlist.txt`` or the rules.
    Returns a count per outcome (``kept``, ``acronym``, ``allowlist``, ...).
    """
    rows = conn.execute(
        select(
            findings.c.id,
            findings.c.token,
            findings.c.suggestion,
            findings.c.context_snippet,
        ).where(findings.c.status.not_in(_LOCKED))
    ).all()

    outcomes: Counter[str] = Counter()
    for row in rows:
        verdict = classify(row.token, row.suggestion, row.context_snippet, allowlist)
        outcomes["kept" if verdict.keep else verdict.reason] += 1
        conn.execute(
            update(findings)
            .where(findings.c.id == row.id)
            .values(
                status="new" if verdict.keep else "false_positive",
                filter_reason=verdict.reason or None,
            )
        )
    return outcomes
