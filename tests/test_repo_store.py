from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from typocrawler.db import repos as repos_table
from typocrawler.db.repo_store import record_crawl_run, upsert_org, upsert_repos
from typocrawler.github.discover import RepoRecord


def test_upsert_org_is_idempotent(engine):
    with engine.begin() as conn:
        id1 = upsert_org(conn, "google")
        id2 = upsert_org(conn, "google")
    assert id1 == id2


def test_upsert_repos_inserts_then_updates_in_place(engine):
    with engine.begin() as conn:
        org_id = upsert_org(conn, "google")
        upsert_repos(conn, org_id, [RepoRecord("google/leveldb", "main", 10, False, False, None)])

    with engine.begin() as conn:
        org_id = upsert_org(conn, "google")
        upsert_repos(conn, org_id, [RepoRecord("google/leveldb", "main", 55, True, False, None)])

    with engine.connect() as conn:
        count = conn.execute(select(func.count()).select_from(repos_table)).scalar_one()
        row = conn.execute(
            select(repos_table.c.stars, repos_table.c.is_archived).where(
                repos_table.c.full_name == "google/leveldb"
            )
        ).one()

    assert count == 1
    assert row.stars == 55
    assert row.is_archived is True


def test_record_crawl_run(engine):
    now = datetime.now(UTC)
    with engine.begin() as conn:
        run_id = record_crawl_run(
            conn,
            started_at=now,
            finished_at=now,
            repos_scanned=5,
            api_points_used=3,
        )
    assert run_id > 0
