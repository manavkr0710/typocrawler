"""Read/write helpers for README snapshots and the repos that still need one."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Connection, Row, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from typocrawler.db.models import readme_snapshots, repos


def repos_needing_readme(conn: Connection, *, limit: int | None = None) -> Sequence[Row]:
    """Repos whose README hasn't been fetched yet, oldest-discovered first."""
    stmt = (
        select(repos.c.id, repos.c.full_name, repos.c.readme_etag)
        .where(repos.c.readme_checked_at.is_(None))
        .order_by(repos.c.id.asc())
    )
    if limit:
        stmt = stmt.limit(limit)
    return conn.execute(stmt).all()


def save_readme_snapshot(
    conn: Connection,
    repo_id: int,
    *,
    blob_sha: str,
    raw_md: str,
    extracted_text: str,
) -> bool:
    """Store a snapshot unless one already exists for this ``(repo, blob_sha)``.

    Returns ``True`` if a new row was inserted.
    """
    stmt = (
        sqlite_insert(readme_snapshots)
        .values(repo_id=repo_id, blob_sha=blob_sha, raw_md=raw_md, extracted_text=extracted_text)
        .on_conflict_do_nothing(index_elements=["repo_id", "blob_sha"])
    )
    return conn.execute(stmt).rowcount > 0
