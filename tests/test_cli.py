from __future__ import annotations

import base64

import httpx
import respx
from sqlalchemy import inspect, select
from typer.testing import CliRunner

from typocrawler import __version__
from typocrawler.cli import app
from typocrawler.db import init_db, make_engine, readme_snapshots
from typocrawler.db import repos as repos_table
from typocrawler.db.repo_store import upsert_org, upsert_repos
from typocrawler.github.discover import RepoRecord

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_init_db_creates_schema(tmp_path):
    db = tmp_path / "typos.db"
    result = runner.invoke(app, ["init-db", "--db", str(db)])
    assert result.exit_code == 0
    assert db.exists()
    assert "findings" in inspect(make_engine(db)).get_table_names()


def test_orgs_lists_targets():
    result = runner.invoke(app, ["orgs"])
    assert result.exit_code == 0
    assert "google" in result.stdout


def test_stubbed_command_exits_nonzero():
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1
    assert "stint 4" in result.stdout


def test_discover_requires_a_token(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = runner.invoke(app, ["discover", "--db", str(tmp_path / "typos.db")])
    assert result.exit_code == 1
    assert "no GitHub token" in result.stdout


@respx.mock
def test_discover_populates_the_database(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")

    config = tmp_path / "orgs.yml"
    config.write_text("orgs:\n  - login: acme\n", encoding="utf-8")
    db = tmp_path / "typos.db"

    respx.post("https://api.github.com/graphql").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "rateLimit": {"cost": 1},
                    "organization": {
                        "repositories": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "nameWithOwner": "acme/widgets",
                                    "isArchived": False,
                                    "isFork": False,
                                    "stargazerCount": 5,
                                    "pushedAt": "2024-01-01T00:00:00Z",
                                    "defaultBranchRef": {"name": "main"},
                                }
                            ],
                        }
                    },
                }
            },
        )
    )

    result = runner.invoke(app, ["discover", "--config", str(config), "--db", str(db)])
    assert result.exit_code == 0, result.stdout
    assert "acme" in result.stdout

    with make_engine(db).connect() as conn:
        names = [row[0] for row in conn.execute(select(repos_table.c.full_name))]
    assert names == ["acme/widgets"]


@respx.mock
def test_fetch_stores_snapshot_and_extracted_prose(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    db = tmp_path / "typos.db"

    engine = init_db(db)
    with engine.begin() as conn:
        org_id = upsert_org(conn, "acme")
        upsert_repos(conn, org_id, [RepoRecord("acme/widgets", "main", 0, False, False, None)])

    readme = "# Widgets\n\nThis prokect is usefull.\n\n```\nteh_code = 1\n```\n"
    respx.get("https://api.github.com/repos/acme/widgets/readme").mock(
        return_value=httpx.Response(
            200,
            json={
                "path": "README.md",
                "sha": "sha1",
                "encoding": "base64",
                "content": base64.b64encode(readme.encode()).decode(),
            },
            headers={"etag": '"e1"'},
        )
    )

    result = runner.invoke(app, ["fetch", "--db", str(db)])
    assert result.exit_code == 0, result.stdout

    with make_engine(db).connect() as conn:
        cols = select(readme_snapshots.c.extracted_text, readme_snapshots.c.raw_md)
        rows = conn.execute(cols).all()
        checked = conn.execute(select(repos_table.c.readme_checked_at)).scalar_one()
    assert len(rows) == 1
    assert "prokect" in rows[0].extracted_text and "usefull" in rows[0].extracted_text
    assert "teh_code" not in rows[0].extracted_text  # code fence stripped
    assert "teh_code" in rows[0].raw_md  # but the raw markdown is kept verbatim
    assert checked is not None


def test_fetch_reports_when_nothing_to_do(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    db = tmp_path / "typos.db"
    init_db(db)
    result = runner.invoke(app, ["fetch", "--db", str(db)])
    assert result.exit_code == 0
    assert "all caught up" in result.stdout
