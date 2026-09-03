from __future__ import annotations

from sqlalchemy import inspect
from typer.testing import CliRunner

from typocrawler import __version__
from typocrawler.cli import app
from typocrawler.db import make_engine

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
    result = runner.invoke(app, ["discover"])
    assert result.exit_code == 1
    assert "stint 2" in result.stdout
