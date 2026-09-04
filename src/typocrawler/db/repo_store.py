"""Upsert helpers that write discovery results into the database."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Connection, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from typocrawler.db.models import crawl_runs, orgs, repos
from typocrawler.github.discover import RepoRecord


def upsert_org(conn: Connection, login: str) -> int:
    """Insert the org if it's new, and return its id either way."""
    stmt = sqlite_insert(orgs).values(login=login).on_conflict_do_nothing(index_elements=["login"])
    conn.execute(stmt)
    return conn.execute(select(orgs.c.id).where(orgs.c.login == login)).scalar_one()


def upsert_repos(conn: Connection, org_id: int, records: Sequence[RepoRecord]) -> int:
    """Insert new repos, or refresh metadata on ones already known (keyed on ``full_name``).

    Returns the number of records written.
    """
    now = datetime.now(UTC)
    for r in records:
        stmt = sqlite_insert(repos).values(
            org_id=org_id,
            full_name=r.full_name,
            default_branch=r.default_branch,
            stars=r.stars,
            is_archived=r.is_archived,
            is_fork=r.is_fork,
            pushed_at=r.pushed_at,
            last_checked_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["full_name"],
            set_={
                "default_branch": stmt.excluded.default_branch,
                "stars": stmt.excluded.stars,
                "is_archived": stmt.excluded.is_archived,
                "is_fork": stmt.excluded.is_fork,
                "pushed_at": stmt.excluded.pushed_at,
                "last_checked_at": stmt.excluded.last_checked_at,
            },
        )
        conn.execute(stmt)
    return len(records)


def record_crawl_run(
    conn: Connection,
    *,
    started_at: datetime,
    finished_at: datetime,
    repos_scanned: int,
    api_points_used: int,
    findings_new: int = 0,
    findings_confirmed: int = 0,
) -> int:
    """Log one pipeline run for later inspection."""
    result = conn.execute(
        crawl_runs.insert().values(
            started_at=started_at,
            finished_at=finished_at,
            repos_scanned=repos_scanned,
            api_points_used=api_points_used,
            findings_new=findings_new,
            findings_confirmed=findings_confirmed,
        )
    )
    return result.inserted_primary_key[0]
