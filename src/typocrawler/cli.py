"""``typocrawler`` command-line interface.

Pipeline subcommands are stubbed until their stint lands; ``version``, ``init-db`` and ``orgs``
are live now.
"""

from __future__ import annotations

import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import httpx
import typer
from dotenv import load_dotenv
from sqlalchemy import select, update

from typocrawler import __version__
from typocrawler.check.heuristics import classify, load_allowlist
from typocrawler.check.spell import crossref, run_codespell, run_typos
from typocrawler.config import DEFAULT_CONFIG_PATH, load_config
from typocrawler.db import DEFAULT_DB_PATH, findings, init_db, repos
from typocrawler.db.finding_store import (
    FindingRow,
    mark_checked,
    reclassify,
    snapshots_to_check,
    upsert_findings,
)
from typocrawler.db.repo_store import record_crawl_run, upsert_org, upsert_repos
from typocrawler.db.snapshot_store import repos_needing_readme, save_readme_snapshot
from typocrawler.github.client import GitHubClient, GitHubError, GitHubRateLimitError
from typocrawler.github.discover import iter_org_repos, should_keep
from typocrawler.github.fetch import fetch_readme
from typocrawler.text.extract import extract_lines, extract_prose

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


def _check_batch(snaps, allowlist: set[str]) -> tuple[list[FindingRow], int]:
    """Run both checkers over one batch of snapshots and build (already classified) rows."""
    # file_key -> (repo_id, blob_sha, [(source_line, prose), ...])
    index: dict[str, tuple[int, str, list[tuple[int, str]]]] = {}

    with tempfile.TemporaryDirectory(prefix="typocrawler-check-") as tmp:
        tmp_dir = Path(tmp)
        for snap in snaps:
            lines = extract_lines(snap.raw_md)
            key = f"{snap.id:08d}"
            (tmp_dir / f"{key}.txt").write_text(
                "\n".join(text for _, text in lines), encoding="utf-8"
            )
            index[key] = (snap.repo_id, snap.blob_sha, lines)

        merged = crossref(run_codespell(tmp_dir) + run_typos(tmp_dir))

    rows: list[FindingRow] = []
    for hit in merged:
        entry = index.get(hit.file_key)
        if entry is None or not (1 <= hit.line <= len(entry[2])):
            continue
        repo_id, blob_sha, lines = entry
        source_line, context = lines[hit.line - 1]
        verdict = classify(hit.word, hit.suggestion, context, allowlist)
        rows.append(
            FindingRow(
                repo_id=repo_id,
                blob_sha=blob_sha,
                line_no=source_line,
                col=hit.col,
                token=hit.word,
                suggestion=hit.suggestion,
                context_snippet=context[:300],
                source=hit.source,
                heuristic_score=hit.score,
                status="new" if verdict.keep else "false_positive",
                filter_reason=verdict.reason,
            )
        )
    return rows, sum(1 for h in merged if h.source == "both")


@app.command()
def check(
    db: str = typer.Option(str(DEFAULT_DB_PATH), help="SQLite file to read/write."),
    limit: int = typer.Option(0, help="Max READMEs to check this run (0 = all remaining)."),
    batch: int = typer.Option(250, min=1, help="READMEs per batch; each batch is committed."),
) -> None:
    """Run codespell + typos over fetched READMEs, then heuristically filter the hits.

    Resumable: only snapshots not yet checked are processed, and each batch is committed as it
    finishes. The checkers run on the stripped prose, but each finding's line number points back
    to the original README. Findings that fail the heuristics land as ``false_positive`` — see
    ``typocrawler findings --rejected``.
    """
    engine = init_db(db)
    allowlist = load_allowlist()
    with engine.begin() as conn:
        snaps = list(snapshots_to_check(conn, limit=limit or None))
    if not snaps:
        typer.secho("no READMEs need checking — all caught up", fg=typer.colors.GREEN)
        return

    started_at = datetime.now(UTC)
    total_findings = total_kept = total_both = 0

    for start in range(0, len(snaps), batch):
        chunk = snaps[start : start + batch]
        rows, both = _check_batch(chunk, allowlist)
        with engine.begin() as conn:
            written = upsert_findings(conn, rows)
            mark_checked(conn, [s.id for s in chunk])
        kept = sum(1 for r in rows if r.status == "new")
        total_findings += written
        total_kept += kept
        total_both += both
        typer.echo(
            f"  {min(start + batch, len(snaps))}/{len(snaps)} READMEs  "
            f"(+{written} findings, {kept} kept)"
        )

    with engine.begin() as conn:
        record_crawl_run(
            conn,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            repos_scanned=len(snaps),
            api_points_used=0,
            findings_new=total_findings,
        )

    typer.secho(
        f"checked {len(snaps)} READMEs -> {total_findings} findings, "
        f"{total_kept} kept after heuristics ({total_both} flagged by both checkers)",
        fg=typer.colors.GREEN,
    )


@app.command("filter")
def filter_cmd(
    db: str = typer.Option(str(DEFAULT_DB_PATH), help="SQLite file to read/write."),
) -> None:
    """Re-run the heuristic filters over all findings (e.g. after editing the allowlist)."""
    engine = init_db(db)
    allowlist = load_allowlist()
    with engine.begin() as conn:
        outcomes = reclassify(conn, allowlist)

    kept = outcomes.pop("kept", 0)
    total = kept + sum(outcomes.values())
    typer.secho(f"re-filtered {total} findings -> {kept} kept", fg=typer.colors.GREEN)
    for reason, n in outcomes.most_common():
        typer.echo(f"  rejected {n:>5}  {reason}")


@app.command("findings")
def findings_cmd(
    db: str = typer.Option(str(DEFAULT_DB_PATH), help="SQLite file to read."),
    limit: int = typer.Option(50, help="Max rows to show."),
    source: str = typer.Option("", help="Filter by source: codespell, typos, both."),
    org: str = typer.Option("", help="Filter by org login, e.g. google."),
    rejected: bool = typer.Option(False, "--rejected", help="Show heuristically-filtered ones."),
    all_: bool = typer.Option(False, "--all", help="Show findings of every status."),
) -> None:
    """Print typo findings — by default the ones that survived the heuristics."""
    engine = init_db(db)
    stmt = (
        select(
            repos.c.full_name,
            findings.c.line_no,
            findings.c.token,
            findings.c.suggestion,
            findings.c.source,
            findings.c.context_snippet,
            findings.c.filter_reason,
        )
        .select_from(findings.join(repos, findings.c.repo_id == repos.c.id))
        .order_by(findings.c.heuristic_score.desc(), repos.c.full_name)
        .limit(limit)
    )
    if rejected:
        stmt = stmt.where(findings.c.status == "false_positive")
    elif not all_:
        stmt = stmt.where(findings.c.status == "new")
    if source:
        stmt = stmt.where(findings.c.source == source)
    if org:
        stmt = stmt.where(repos.c.full_name.like(f"{org}/%"))

    with engine.connect() as conn:
        rows = conn.execute(stmt).all()

    if not rows:
        typer.secho("no findings match", fg=typer.colors.YELLOW)
        return
    for r in rows:
        tag = f"{r.source}/{r.filter_reason}" if r.filter_reason else r.source
        typer.secho(f"{tag:16} ", fg=typer.colors.CYAN, nl=False)
        typer.echo(f"{r.full_name}:{r.line_no}  {r.token} -> {r.suggestion}")
        typer.secho(f"    {r.context_snippet[:100]}", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(f"\n{len(rows)} shown")


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
