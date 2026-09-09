from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select, update

from typocrawler.db import findings as findings_table
from typocrawler.db import repos as repos_table
from typocrawler.db.repo_store import upsert_org, upsert_repos
from typocrawler.github.discover import RepoRecord
from typocrawler.report import build_site


def _seed(engine):
    with engine.begin() as conn:
        org_id = upsert_org(conn, "google")
        upsert_repos(
            conn,
            org_id,
            [
                RepoRecord("google/clasp", "master", 5817, False, False, None),
                RepoRecord("google/leveldb", "main", 100, False, False, None),
            ],
        )
        ids = {
            r.full_name: r.id
            for r in conn.execute(select(repos_table.c.full_name, repos_table.c.id))
        }
        conn.execute(
            update(repos_table)
            .where(repos_table.c.full_name == "google/clasp")
            .values(readme_path="README.md", readme_checked_at=datetime.now(UTC))
        )
        def row(repo, line, token, fix, ctx, status, verdict=None, reason=None, source="both"):
            return dict(
                repo_id=ids[repo], blob_sha="s", line_no=line, token=token, suggestion=fix,
                context_snippet=ctx, source=source, heuristic_score=2, status=status,
                llm_verdict=verdict, filter_reason=reason,
            )

        conn.execute(
            findings_table.insert(),
            [
                row("google/clasp", 633, "directoy", "directory",
                    "the project directoy is set", "confirmed", "typo"),
                row("google/leveldb", 10, "recieve", "receive",
                    "you recieve a callback", "new"),
                row("google/leveldb", 20, "als", "also", "als the config", "new", "unsure",
                    source="typos"),
                row("google/leveldb", 30, "AKS", "ASK", "deploy AKS", "false_positive",
                    reason="acronym"),
            ],
        )


def test_build_site_writes_data_and_assets(engine, tmp_path):
    _seed(engine)
    meta = build_site(engine, tmp_path)

    assert (tmp_path / "index.html").is_file()
    assert (tmp_path / "app.js").is_file()
    assert (tmp_path / "style.css").is_file()

    rows = json.loads((tmp_path / "data" / "findings.json").read_text(encoding="utf-8"))
    by_token = {r["token"]: r for r in rows}

    # confirmed + new (unverified/unsure) shown; heuristic false-positive excluded
    assert set(by_token) == {"directoy", "recieve", "als"}
    assert by_token["directoy"]["verdict"] == "confirmed"
    assert by_token["recieve"]["verdict"] == "unverified"
    assert by_token["als"]["verdict"] == "unsure"

    # confirmed rows sort first
    assert rows[0]["token"] == "directoy"

    # github deep link uses the repo's branch + readme path
    assert by_token["directoy"]["url"] == (
        "https://github.com/google/clasp/blob/master/README.md#L633"
    )

    assert meta == json.loads((tmp_path / "data" / "meta.json").read_text(encoding="utf-8"))
    assert meta["confirmed"] == 1
    assert meta["unverified"] == 1
    assert meta["unsure"] == 1
    assert meta["orgs"] == 1
    assert meta["by_org"] == {"google": 1}
    assert meta["top_typos"] == [["directoy", 1]]
