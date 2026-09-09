"""Turn the findings DB into a static site: two JSON data files plus copied assets."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, func, select

from typocrawler.db.models import findings, repos

_ASSETS = Path(__file__).parent / "assets"

# What the dashboard shows: LLM-confirmed typos, plus heuristic survivors not yet ruled out
# (either awaiting verification or marked "unsure").
_DASHBOARD_STATUSES = ("confirmed", "new")


def _github_line_url(full_name: str, branch: str, path: str | None, line: int) -> str:
    return f"https://github.com/{full_name}/blob/{branch or 'main'}/{path or 'README.md'}#L{line}"


def _verdict(status: str, llm_verdict: str | None) -> str:
    if status == "confirmed":
        return "confirmed"
    return "unsure" if llm_verdict == "unsure" else "unverified"


def _findings_rows(conn) -> list[dict]:
    stmt = (
        select(
            repos.c.full_name,
            repos.c.default_branch,
            repos.c.readme_path,
            repos.c.stars,
            findings.c.line_no,
            findings.c.token,
            findings.c.suggestion,
            findings.c.context_snippet,
            findings.c.source,
            findings.c.status,
            findings.c.llm_verdict,
        )
        .select_from(findings.join(repos, findings.c.repo_id == repos.c.id))
        .where(findings.c.status.in_(_DASHBOARD_STATUSES))
        .order_by(
            (findings.c.status == "confirmed").desc(),
            repos.c.stars.desc(),
            repos.c.full_name,
            findings.c.line_no,
        )
    )
    rows: list[dict] = []
    for r in conn.execute(stmt):
        rows.append(
            {
                "org": r.full_name.split("/", 1)[0],
                "repo": r.full_name,
                "url": _github_line_url(
                    r.full_name, r.default_branch, r.readme_path, r.line_no
                ),
                "line": r.line_no,
                "token": r.token,
                "fix": r.suggestion,
                "context": (r.context_snippet or "").strip(),
                "stars": r.stars,
                "source": r.source,
                "verdict": _verdict(r.status, r.llm_verdict),
            }
        )
    return rows


def _meta(conn, rows: list[dict]) -> dict:
    confirmed = [x for x in rows if x["verdict"] == "confirmed"]
    by_org = Counter(x["org"] for x in confirmed)
    top = Counter(x["token"].lower() for x in confirmed)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "confirmed": len(confirmed),
        "unsure": sum(1 for x in rows if x["verdict"] == "unsure"),
        "unverified": sum(1 for x in rows if x["verdict"] == "unverified"),
        "repos": len({x["repo"] for x in confirmed}),
        "orgs": len(by_org),
        "readmes_scanned": conn.execute(
            select(func.count()).select_from(repos).where(repos.c.readme_checked_at.is_not(None))
        ).scalar_one(),
        "by_org": dict(by_org.most_common()),
        "top_typos": [[word, n] for word, n in top.most_common(12)],
    }


def build_site(engine: Engine, out: Path) -> dict:
    """Write ``out/`` (data JSON + assets) and return the meta dict."""
    out = Path(out)
    (out / "data").mkdir(parents=True, exist_ok=True)

    with engine.connect() as conn:
        rows = _findings_rows(conn)
        meta = _meta(conn, rows)

    (out / "data" / "findings.json").write_text(
        json.dumps(rows, ensure_ascii=False), encoding="utf-8"
    )
    (out / "data" / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    for asset in _ASSETS.iterdir():
        if asset.is_file():
            shutil.copy2(asset, out / asset.name)

    return meta
