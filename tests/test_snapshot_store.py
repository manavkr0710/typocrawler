from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update

from typocrawler.db import readme_snapshots, repos
from typocrawler.db.repo_store import upsert_org, upsert_repos
from typocrawler.db.snapshot_store import repos_needing_readme, save_readme_snapshot
from typocrawler.github.discover import RepoRecord


def _seed(engine, n: int = 1) -> list[int]:
    with engine.begin() as conn:
        org_id = upsert_org(conn, "acme")
        upsert_repos(
            conn,
            org_id,
            [RepoRecord(f"acme/r{i}", "main", 0, False, False, None) for i in range(n)],
        )
        return [r.id for r in conn.execute(select(repos.c.id).order_by(repos.c.id))]


def test_save_snapshot_is_idempotent_per_blob(engine):
    (repo_id,) = _seed(engine)
    with engine.begin() as conn:
        assert save_readme_snapshot(
            conn, repo_id, blob_sha="s1", raw_md="# x", extracted_text="x"
        ) is True
    with engine.begin() as conn:
        assert save_readme_snapshot(
            conn, repo_id, blob_sha="s1", raw_md="# x", extracted_text="x"
        ) is False
    with engine.connect() as conn:
        count = conn.execute(select(func.count()).select_from(readme_snapshots)).scalar_one()
    assert count == 1


def test_repos_needing_readme_skips_already_checked(engine):
    ids = _seed(engine, 3)
    with engine.begin() as conn:
        conn.execute(
            update(repos).where(repos.c.id == ids[0]).values(readme_checked_at=datetime.now(UTC))
        )
    with engine.connect() as conn:
        todo = repos_needing_readme(conn)
    assert [r.id for r in todo] == ids[1:]


def test_repos_needing_readme_respects_limit(engine):
    _seed(engine, 5)
    with engine.connect() as conn:
        assert len(repos_needing_readme(conn, limit=2)) == 2
