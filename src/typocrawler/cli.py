"""``typocrawler`` command-line interface.

Pipeline subcommands are stubbed until their stint lands; ``version``, ``init-db`` and ``orgs``
are live now.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

import typer

from typocrawler import __version__
from typocrawler.config import DEFAULT_CONFIG_PATH, load_config
from typocrawler.db import DEFAULT_DB_PATH, init_db
from typocrawler.db.repo_store import record_crawl_run, upsert_org, upsert_repos
from typocrawler.github.client import GitHubClient, GitHubError
from typocrawler.github.discover import iter_org_repos, should_keep

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


@app.command()
def fetch(db: str = typer.Option(str(DEFAULT_DB_PATH))) -> None:
    """Fetch README blobs for known repositories (ETag-cached)."""
    _not_yet("fetch", 3)


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
