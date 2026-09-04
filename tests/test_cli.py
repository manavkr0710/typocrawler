from __future__ import annotations

import httpx
import respx
from sqlalchemy import inspect, select
from typer.testing import CliRunner

from typocrawler import __version__
from typocrawler.cli import app
from typocrawler.db import make_engine
from typocrawler.db import repos as repos_table

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
    result = runner.invoke(app, ["fetch"])
    assert result.exit_code == 1
    assert "stint 3" in result.stdout


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
