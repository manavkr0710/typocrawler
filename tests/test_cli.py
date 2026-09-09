from __future__ import annotations

import base64

import httpx
import respx
from sqlalchemy import inspect, select
from typer.testing import CliRunner

from typocrawler import __version__
from typocrawler.cli import app
from typocrawler.db import findings, init_db, make_engine, readme_snapshots
from typocrawler.db import repos as repos_table
from typocrawler.db.repo_store import upsert_org, upsert_repos
from typocrawler.db.snapshot_store import save_readme_snapshot
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
    result = runner.invoke(app, ["check", "--db", "does-not-matter", "--help"])
    assert result.exit_code == 0  # all pipeline commands are implemented now


def test_report_builds_a_site(tmp_path):
    db = tmp_path / "typos.db"
    engine = init_db(db)
    with engine.begin() as conn:
        org_id = upsert_org(conn, "acme")
        upsert_repos(conn, org_id, [RepoRecord("acme/widgets", "main", 9, False, False, None)])
        repo_id = conn.execute(
            select(repos_table.c.id).where(repos_table.c.full_name == "acme/widgets")
        ).scalar_one()
        conn.execute(
            findings.insert().values(
                repo_id=repo_id,
                blob_sha="s",
                line_no=3,
                token="recieve",
                suggestion="receive",
                context_snippet="you recieve it",
                source="both",
                heuristic_score=2,
                status="confirmed",
                llm_verdict="typo",
            )
        )

    out = tmp_path / "site"
    result = runner.invoke(app, ["report", "--db", str(db), "--out", str(out)])
    assert result.exit_code == 0, result.stdout
    assert "1 confirmed" in result.stdout
    assert (out / "index.html").is_file()
    assert "recieve" in (out / "data" / "findings.json").read_text(encoding="utf-8")


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


def test_check_records_findings_with_source_readme_line(tmp_path):
    db = tmp_path / "typos.db"
    engine = init_db(db)
    with engine.begin() as conn:
        org_id = upsert_org(conn, "acme")
        upsert_repos(conn, org_id, [RepoRecord("acme/widgets", "main", 0, False, False, None)])
        repo_id = conn.execute(
            select(repos_table.c.id).where(repos_table.c.full_name == "acme/widgets")
        ).scalar_one()
        raw_md = "# Widgets\n\n```\nignored teh\n```\n\nYou will recieve the widget.\n"
        save_readme_snapshot(
            conn, repo_id, blob_sha="sha1", raw_md=raw_md, extracted_text="x"
        )

    result = runner.invoke(app, ["check", "--db", str(db)])
    assert result.exit_code == 0, result.stdout

    with make_engine(db).connect() as conn:
        rows = conn.execute(
            select(findings.c.token, findings.c.suggestion, findings.c.line_no, findings.c.source)
        ).all()

    tokens = {r.token: r for r in rows}
    assert "recieve" in tokens
    assert tokens["recieve"].suggestion == "receive"
    assert tokens["recieve"].line_no == 7  # real README line, not the stripped-prose line
    assert "teh" not in tokens  # inside a fenced code block, never checked


def test_check_reports_when_nothing_to_do(tmp_path):
    db = tmp_path / "typos.db"
    init_db(db)
    result = runner.invoke(app, ["check", "--db", str(db)])
    assert result.exit_code == 0
    assert "all caught up" in result.stdout


def test_check_commits_each_batch(tmp_path):
    db = tmp_path / "typos.db"
    engine = init_db(db)
    with engine.begin() as conn:
        org_id = upsert_org(conn, "acme")
        upsert_repos(
            conn,
            org_id,
            [RepoRecord(f"acme/r{i}", "main", 0, False, False, None) for i in range(3)],
        )
        for i, repo_id in enumerate(
            conn.execute(select(repos_table.c.id).order_by(repos_table.c.id)).scalars()
        ):
            save_readme_snapshot(
                conn,
                repo_id,
                blob_sha=f"sha{i}",
                raw_md=f"# R{i}\n\nThis has a recieve typo.\n",
                extracted_text="x",
            )

    result = runner.invoke(app, ["check", "--db", str(db), "--batch", "1"])
    assert result.exit_code == 0, result.stdout
    assert "1/3 READMEs" in result.stdout  # per-batch progress line
    assert "3/3 READMEs" in result.stdout


def test_findings_command_lists_and_filters(tmp_path):
    db = tmp_path / "typos.db"
    engine = init_db(db)
    with engine.begin() as conn:
        org_id = upsert_org(conn, "acme")
        upsert_repos(conn, org_id, [RepoRecord("acme/widgets", "main", 0, False, False, None)])
        repo_id = conn.execute(
            select(repos_table.c.id).where(repos_table.c.full_name == "acme/widgets")
        ).scalar_one()
        save_readme_snapshot(
            conn,
            repo_id,
            blob_sha="sha1",
            raw_md="# Widgets\n\nYou will recieve the widget.\n",
            extracted_text="x",
        )
    runner.invoke(app, ["check", "--db", str(db)])

    listed = runner.invoke(app, ["findings", "--db", str(db)])
    assert listed.exit_code == 0
    assert "recieve -> receive" in listed.stdout
    assert "acme/widgets" in listed.stdout

    filtered = runner.invoke(app, ["findings", "--db", str(db), "--org", "google"])
    assert "no findings match" in filtered.stdout


def test_check_filters_acronyms_but_keeps_real_typos(tmp_path):
    db = tmp_path / "typos.db"
    engine = init_db(db)
    with engine.begin() as conn:
        org_id = upsert_org(conn, "acme")
        upsert_repos(conn, org_id, [RepoRecord("acme/widgets", "main", 0, False, False, None)])
        repo_id = conn.execute(
            select(repos_table.c.id).where(repos_table.c.full_name == "acme/widgets")
        ).scalar_one()
        save_readme_snapshot(
            conn,
            repo_id,
            blob_sha="sha1",
            raw_md="# Widgets\n\nDeploy to AKS then recieve the callback in your enviroment.\n",
            extracted_text="x",
        )

    runner.invoke(app, ["check", "--db", str(db)])

    kept = runner.invoke(app, ["findings", "--db", str(db)]).stdout
    assert "recieve -> receive" in kept
    assert "enviroment -> environment" in kept
    assert "AKS -> ASK" not in kept  # filtered by the heuristics

    rejected = runner.invoke(app, ["findings", "--db", str(db), "--rejected"]).stdout
    assert "AKS -> ASK" in rejected


def test_filter_command_reclassifies_after_allowlist_edit(tmp_path, monkeypatch):
    db = tmp_path / "typos.db"
    engine = init_db(db)
    with engine.begin() as conn:
        org_id = upsert_org(conn, "acme")
        upsert_repos(conn, org_id, [RepoRecord("acme/widgets", "main", 0, False, False, None)])
        repo_id = conn.execute(
            select(repos_table.c.id).where(repos_table.c.full_name == "acme/widgets")
        ).scalar_one()
        save_readme_snapshot(
            conn,
            repo_id,
            blob_sha="sha1",
            raw_md="# Widgets\n\nKeep the runtime config seperate from the app code.\n",
            extracted_text="x",
        )
    runner.invoke(app, ["check", "--db", str(db)])
    assert "seperate" in runner.invoke(app, ["findings", "--db", str(db)]).stdout

    allow = tmp_path / "allowlist.txt"
    allow.write_text("seperate\n", encoding="utf-8")
    monkeypatch.setattr("typocrawler.check.heuristics.DEFAULT_ALLOWLIST_PATH", allow)

    result = runner.invoke(app, ["filter", "--db", str(db)])
    assert result.exit_code == 0
    assert "allowlist" in result.stdout
    assert "seperate" not in runner.invoke(app, ["findings", "--db", str(db)]).stdout


def _seed_finding(engine, token="recieve", suggestion="receive", status="new"):
    with engine.begin() as conn:
        org_id = upsert_org(conn, "acme")
        upsert_repos(conn, org_id, [RepoRecord("acme/widgets", "main", 0, False, False, None)])
        repo_id = conn.execute(
            select(repos_table.c.id).where(repos_table.c.full_name == "acme/widgets")
        ).scalar_one()
        conn.execute(
            findings.insert().values(
                repo_id=repo_id,
                blob_sha="sha1",
                line_no=3,
                token=token,
                suggestion=suggestion,
                context_snippet=f"you will {token} it",
                source="both",
                heuristic_score=2,
                status=status,
            )
        )


def test_verify_with_stub_provider_confirms_findings(tmp_path):
    db = tmp_path / "typos.db"
    _seed_finding(init_db(db))

    result = runner.invoke(app, ["verify", "--db", str(db), "--provider", "stub"])
    assert result.exit_code == 0, result.stdout
    assert "1 confirmed" in result.stdout

    with make_engine(db).connect() as conn:
        row = conn.execute(
            select(findings.c.status, findings.c.llm_verdict, findings.c.llm_correction)
        ).one()
    assert row.status == "confirmed"
    assert row.llm_verdict == "typo"

    confirmed = runner.invoke(app, ["findings", "--db", str(db), "--confirmed"]).stdout
    assert "recieve -> receive" in confirmed


def test_verify_reports_when_nothing_pending(tmp_path):
    db = tmp_path / "typos.db"
    init_db(db)
    result = runner.invoke(app, ["verify", "--db", str(db), "--provider", "stub"])
    assert result.exit_code == 0
    assert "all caught up" in result.stdout


@respx.mock
def test_verify_errors_clearly_without_a_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    respx.get("http://localhost:11434/api/tags").mock(side_effect=httpx.ConnectError("down"))
    db = tmp_path / "typos.db"
    _seed_finding(init_db(db))
    # autodetect -> ollama, which self-checks and fails since it isn't reachable
    result = runner.invoke(app, ["verify", "--db", str(db)])
    assert result.exit_code == 1
    assert "Ollama not reachable" in result.stdout
