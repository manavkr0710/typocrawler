from __future__ import annotations

from sqlalchemy import func, select

from typocrawler.db import findings, readme_snapshots, repos
from typocrawler.db.finding_store import (
    FindingRow,
    mark_checked,
    reclassify,
    snapshots_to_check,
    upsert_findings,
)
from typocrawler.db.repo_store import upsert_org, upsert_repos
from typocrawler.db.snapshot_store import save_readme_snapshot
from typocrawler.github.discover import RepoRecord


def _seed_snapshot(engine, full_name="acme/widgets", sha="sha1"):
    with engine.begin() as conn:
        org_id = upsert_org(conn, "acme")
        upsert_repos(conn, org_id, [RepoRecord(full_name, "main", 0, False, False, None)])
        repo_id = conn.execute(
            select(repos.c.id).where(repos.c.full_name == full_name)
        ).scalar_one()
        save_readme_snapshot(
            conn, repo_id, blob_sha=sha, raw_md="# x", extracted_text="x"
        )
        snap_id = conn.execute(
            select(readme_snapshots.c.id).where(readme_snapshots.c.repo_id == repo_id)
        ).scalar_one()
    return repo_id, snap_id


def _row(repo_id, sha, **kw):
    base = dict(
        repo_id=repo_id,
        blob_sha=sha,
        line_no=4,
        col=0,
        token="recieve",
        suggestion="receive",
        context_snippet="you recieve it",
        source="both",
        heuristic_score=2,
    )
    base.update(kw)
    return FindingRow(**base)


def test_snapshots_to_check_excludes_already_checked(engine):
    _, snap_id = _seed_snapshot(engine)
    with engine.connect() as conn:
        assert [s.id for s in snapshots_to_check(conn)] == [snap_id]

    with engine.begin() as conn:
        mark_checked(conn, [snap_id])
    with engine.connect() as conn:
        assert snapshots_to_check(conn) == []


def test_upsert_findings_is_idempotent_on_the_unique_key(engine):
    repo_id, _ = _seed_snapshot(engine)
    with engine.begin() as conn:
        upsert_findings(conn, [_row(repo_id, "sha1")])
        upsert_findings(conn, [_row(repo_id, "sha1", suggestion="receive", source="codespell")])

    with engine.connect() as conn:
        count = conn.execute(select(func.count()).select_from(findings)).scalar_one()
        source = conn.execute(select(findings.c.source)).scalar_one()
    assert count == 1
    assert source == "codespell"  # refreshed on conflict


def test_reclassify_rejects_and_is_idempotent(engine):
    repo_id, _ = _seed_snapshot(engine)
    with engine.begin() as conn:
        upsert_findings(
            conn,
            [
                _row(repo_id, "sha1", token="recieve", line_no=1),  # real -> kept
                _row(repo_id, "sha1", token="AKS", suggestion="ASK", line_no=2),  # acronym
                _row(repo_id, "sha1", token="widget", line_no=3),  # allowlisted below
            ],
        )

    with engine.begin() as conn:
        outcomes = reclassify(conn, allowlist={"widget"})

    assert outcomes["kept"] == 1
    assert outcomes["acronym"] == 1
    assert outcomes["allowlist"] == 1

    with engine.connect() as conn:
        cols = select(findings.c.token, findings.c.status, findings.c.filter_reason)
        by_token = {r.token: (r.status, r.filter_reason) for r in conn.execute(cols)}
    assert by_token["recieve"] == ("new", None)
    assert by_token["AKS"][0] == "false_positive"
    assert by_token["widget"] == ("false_positive", "allowlist")

    # running again changes nothing
    with engine.begin() as conn:
        again = reclassify(conn, allowlist={"widget"})
    assert again == outcomes


def test_reclassify_leaves_confirmed_findings_alone(engine):
    repo_id, _ = _seed_snapshot(engine)
    confirmed = _row(repo_id, "sha1", token="AKS", suggestion="ASK", status="confirmed")
    with engine.begin() as conn:
        upsert_findings(conn, [confirmed])
    with engine.begin() as conn:
        reclassify(conn, allowlist=set())
    with engine.connect() as conn:
        status = conn.execute(select(findings.c.status)).scalar_one()
    assert status == "confirmed"


def test_mark_checked_sets_timestamp(engine):
    _, snap_id = _seed_snapshot(engine)
    with engine.begin() as conn:
        mark_checked(conn, [snap_id])
    with engine.connect() as conn:
        checked = conn.execute(
            select(readme_snapshots.c.checked_at).where(readme_snapshots.c.id == snap_id)
        ).scalar_one()
    assert checked is not None
