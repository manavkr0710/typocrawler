"""``typocrawler`` command-line interface.

Pipeline subcommands are stubbed until their stint lands; ``version``, ``init-db`` and ``orgs``
are live now.
"""

from __future__ import annotations

import typer

from typocrawler import __version__
from typocrawler.config import DEFAULT_CONFIG_PATH, load_config
from typocrawler.db import DEFAULT_DB_PATH, init_db

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
    config: str = typer.Option(str(DEFAULT_CONFIG_PATH)),
    db: str = typer.Option(str(DEFAULT_DB_PATH)),
) -> None:
    """Enumerate org repositories into the database."""
    _not_yet("discover", 2)


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
