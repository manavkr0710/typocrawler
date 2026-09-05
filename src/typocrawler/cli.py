"""``typocrawler`` command-line interface.

Pipeline subcommands are stubbed until their stint lands; ``version``, ``init-db`` and ``orgs``
are live now.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

import httpx
import typer
from dotenv import load_dotenv
from sqlalchemy import update

from typocrawler import __version__
from typocrawler.config import DEFAULT_CONFIG_PATH, load_config
from typocrawler.db import DEFAULT_DB_PATH, init_db, repos
from typocrawler.db.repo_store import record_crawl_run, upsert_org, upsert_repos
from typocrawler.db.snapshot_store import repos_needing_readme, save_readme_snapshot
from typocrawler.github.client import GitHubClient, GitHubError, GitHubRateLimitError
from typocrawler.github.discover import iter_org_repos, should_keep
from typocrawler.github.fetch import fetch_readme
from typocrawler.text.extract import extract_prose

load_dotenv()  # pulls GITHUB_TOKEN (etc.) from a .env file in cwd/a parent dir, if present

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Crawl big-org open-source READMEs and surface genuine typos.",
)


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


@app.command("init-db")
def init_db_cmd(
    db: str = typer.Option(str(DEFAULT_DB_PATH), help="SQLite file to create."),
) -> None:
    """Create the SQLite schema."""
    init_db(db)
    typer.secho(f"initialised schema in {db}", fg=typer.colors.GREEN)


@app.command()
def orgs(
    config: str = typer.Option(str(DEFAULT_CONFIG_PATH), help="Path to the org config file."),
) -> None:
    """Show the resolved target org list."""
    for o in load_config(config).resolved():
        typer.echo(
            f"{o.login:<16} min_stars={o.min_stars:<5} "
            f"forks={str(o.include_forks):<5} archived={o.include_archived}"
        )


def _not_yet(name: str, stint: int) -> None:
    typer.secho(f"'{name}' arrives in stint {stint} — not implemented yet.", fg=typer.colors.YELLOW)
    raise typer.Exit(code=1)


@app.command()
def discover(
    config: str = typer.Option(str(DEFAULT_CONFIG_PATH), help="Path to the org config file."),
    db: str = typer.Option(str(DEFAULT_DB_PATH), help="SQLite file to write into."),
    token: str | None = typer.Option(
        None,
        envvar="GITHUB_TOKEN",
        help="GitHub personal access token (public-repo read scope).",
    ),
    workers: int = typer.Option(
        4, min=1, max=8, help="How many orgs to fetch concurrently."
    ),
) -> None:
    """Enumerate org repositories into the database.

    Orgs are fetched concurrently (each org's own pages are still sequential — GraphQL
    pagination is cursor-based). Each org is committed to the database as soon as its fetch
    completes, so an interrupted run keeps whatever it already finished.
    """
    cfg = load_config(config)
    engine = init_db(db)

    try:
        client = GitHubClient(token)
    except GitHubError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    started_at = datetime.now(UTC)
    total_seen = total_kept = 0

    def _fetch(org):
        try:
            return org, list(iter_org_repos(client, org.login)), None
        except GitHubError as exc:
            return org, None, exc

    with client:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_fetch, org) for org in cfg.resolved()]
            for future in as_completed(futures):
                org, records, err = future.result()
                if err is not None:
                    typer.secho(f"{org.login}: {err}", fg=typer.colors.YELLOW)
                    continue
                kept = [r for r in records if should_keep(r, org)]
                with engine.begin() as conn:
                    org_id = upsert_org(conn, org.login)
                    upsert_repos(conn, org_id, kept)
                total_seen += len(records)
                total_kept += len(kept)
                typer.echo(f"{org.login:<16} kept {len(kept)}/{len(records)} repos")

        with engine.begin() as conn:
            record_crawl_run(
                conn,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                repos_scanned=total_kept,
                api_points_used=client.points_used,
            )

    typer.secho(
        f"discovered {total_kept} repos ({total_seen} seen, {client.points_used} API points used)",
        fg=typer.colors.GREEN,
    )


def _persist_readme(conn, row, result) -> None:
    now = datetime.now(UTC)
    if result.status == "fetched":
        save_readme_snapshot(
            conn,
            row.id,
            blob_sha=result.blob_sha,
            raw_md=result.raw_md,
            extracted_text=extract_prose(result.raw_md),
        )
        conn.execute(
            update(repos)
            .where(repos.c.id == row.id)
            .values(
                readme_path=result.path,
                readme_blob_sha=result.blob_sha,
                readme_etag=result.etag,
                readme_checked_at=now,
                last_checked_at=now,
            )
        )
    else:
        conn.execute(
            update(repos)
            .where(repos.c.id == row.id)
            .values(readme_checked_at=now, last_checked_at=now)
        )


@app.command()
def fetch(
    db: str = typer.Option(str(DEFAULT_DB_PATH), help="SQLite file to read/write."),
    token: str | None = typer.Option(None, envvar="GITHUB_TOKEN", help="GitHub token."),
    limit: int = typer.Option(300, help="Max repos to fetch this run (0 = all remaining)."),
    workers: int = typer.Option(6, min=1, max=10, help="Concurrent README fetches."),
) -> None:
    """Fetch README files for discovered repos and extract their prose.

    Resumable: only repos without a README snapshot are fetched, so re-running continues where
    the last run stopped. Conditional (ETag) requests mean unchanged READMEs cost nothing.
    """
    engine = init_db(db)
    try:
        client = GitHubClient(token)
    except GitHubError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    with engine.begin() as conn:
        todo = list(repos_needing_readme(conn, limit=limit or None))
    if not todo:
        typer.secho("no repos need a README fetch — all caught up", fg=typer.colors.GREEN)
        return

    started_at = datetime.now(UTC)
    counts: Counter[str] = Counter()
    stopped = False

    def _work(row):
        try:
            return row, fetch_readme(client, row.full_name, etag=row.readme_etag), None
        except GitHubRateLimitError:
            raise
        except (GitHubError, httpx.HTTPStatusError) as exc:
            return row, None, exc

    with client, ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_work, r) for r in todo]
        for future in as_completed(futures):
            try:
                row, result, err = future.result()
            except GitHubRateLimitError as exc:
                stopped = True
                typer.secho(
                    f"\n{exc} — re-run `typocrawler fetch` after that.", fg=typer.colors.YELLOW
                )
                for f in futures:
                    f.cancel()
                break
            if err is not None:
                counts["error"] += 1
                typer.secho(f"  {row.full_name}: {err}", fg=typer.colors.YELLOW)
                continue
            with engine.begin() as conn:
                _persist_readme(conn, row, result)
            counts[result.status] += 1
            if sum(counts.values()) % 25 == 0:
                typer.echo(f"  {sum(counts.values())}/{len(todo)}  {dict(counts)}")

    with engine.begin() as conn:
        record_crawl_run(
            conn,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            repos_scanned=sum(counts.values()),
            api_points_used=0,
        )

    colour = typer.colors.YELLOW if stopped else typer.colors.GREEN
    typer.secho(f"fetch done: {dict(counts)}", fg=colour)


@app.command()
def check(db: str = typer.Option(str(DEFAULT_DB_PATH))) -> None:
    """Run the spell-checkers over extracted README text."""
    _not_yet("check", 4)


@app.command()
def verify(db: str = typer.Option(str(DEFAULT_DB_PATH))) -> None:
    """LLM verification pass over candidate findings."""
    _not_yet("verify", 6)


@app.command()
def report(
    db: str = typer.Option(str(DEFAULT_DB_PATH)),
    out: str = typer.Option("site", help="Output directory for the static site."),
) -> None:
    """Build the static dashboard."""
    _not_yet("report", 7)


if __name__ == "__main__":
    app()
