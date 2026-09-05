"""Fetch a repo's README via the REST API, with conditional-request (ETag) support."""

from __future__ import annotations

import base64
from dataclasses import dataclass

from typocrawler.github.client import GitHubClient

MAX_README_BYTES = 1_000_000


@dataclass(frozen=True)
class ReadmeResult:
    status: str  # "fetched" | "not_modified" | "absent" | "skipped"
    path: str | None = None
    blob_sha: str | None = None
    etag: str | None = None
    raw_md: str | None = None


def fetch_readme(client: GitHubClient, full_name: str, *, etag: str | None = None) -> ReadmeResult:
    """Fetch ``full_name``'s README.

    ``not_modified`` when the ETag still matches (cheap — 304s don't count against the rate
    limit); ``absent`` when the repo has no README; ``skipped`` when it's implausibly large.
    """
    resp = client.rest_get(f"/repos/{full_name}/readme", etag=etag)
    if resp.status_code == 304:
        return ReadmeResult(status="not_modified")
    if resp.status_code == 404:
        return ReadmeResult(status="absent")

    body = resp.json()
    if body.get("encoding") != "base64":
        return ReadmeResult(status="absent")

    raw = base64.b64decode(body["content"])
    if len(raw) > MAX_README_BYTES:
        return ReadmeResult(status="skipped", path=body.get("path"), blob_sha=body.get("sha"))

    return ReadmeResult(
        status="fetched",
        path=body.get("path"),
        blob_sha=body.get("sha"),
        etag=resp.headers.get("etag"),
        raw_md=raw.decode("utf-8", errors="replace"),
    )
