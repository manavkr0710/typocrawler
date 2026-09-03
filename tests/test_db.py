from __future__ import annotations

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from typocrawler.db import findings, orgs, repos


def _seed_repo(engine) -> int:
    with engine.begin() as conn:
        org_id = conn.execute(insert(orgs).values(login="google")).inserted_primary_key[0]
        repo_id = conn.execute(
            insert(repos).values(org_id=org_id, full_name="google/leveldb")
        ).inserted_primary_key[0]
    return repo_id


def test_schema_has_expected_tables(engine):
    from sqlalchemy import inspect

    names = set(inspect(engine).get_table_names())
    assert {"orgs", "repos", "readme_snapshots", "findings", "crawl_runs"} <= names


def test_repo_full_name_is_unique(engine):
    _seed_repo(engine)
    with engine.begin() as conn:  # noqa: SIM117
        org_id = conn.execute(select(orgs.c.id)).scalar_one()
        with pytest.raises(IntegrityError):
            conn.execute(insert(repos).values(org_id=org_id, full_name="google/leveldb"))


def test_finding_status_check_constraint(engine):
    repo_id = _seed_repo(engine)
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            insert(findings).values(
                repo_id=repo_id,
                blob_sha="abc",
                line_no=1,
                token="teh",
                suggestion="the",
                source="both",
                status="bogus",
            )
        )


def test_finding_dedup_unique_constraint(engine):
    repo_id = _seed_repo(engine)
    row = dict(
        repo_id=repo_id,
        blob_sha="abc",
        line_no=3,
        token="recieve",
        suggestion="receive",
        source="codespell",
    )
    with engine.begin() as conn:
        conn.execute(insert(findings).values(**row))
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(insert(findings).values(**row))


def test_foreign_key_enforced(engine):
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(insert(repos).values(org_id=999, full_name="ghost/repo"))
