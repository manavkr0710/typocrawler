"""Thin GitHub client (GraphQL + REST): auth, retries, and rate-limit awareness."""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

_RETRYABLE_STATUS = {502, 503, 504}

_RETRY_KW: dict[str, Any] = {
    "reraise": True,
    "stop": stop_after_attempt(5),
    "wait": wait_exponential(multiplier=1, min=1, max=30),
}


class GitHubError(RuntimeError):
    """Missing auth, an unknown org, or a GraphQL-level error in the response."""


class GitHubRateLimitError(GitHubError):
    """Primary REST rate limit exhausted. Carries the reset time so callers can stop cleanly."""

    def __init__(self, reset_epoch: int) -> None:
        self.reset_at = datetime.fromtimestamp(reset_epoch, tz=UTC)
        super().__init__(f"GitHub rate limit exhausted; resets at {self.reset_at.isoformat()}")


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        resp = exc.response
        if resp.status_code in _RETRYABLE_STATUS:
            return True
        # Secondary rate limit: GitHub sends 403 with a Retry-After header.
        if resp.status_code == 403 and "retry-after" in resp.headers:
            return True
    return False


class GitHubClient:
    """A client for the GitHub API, authenticated with a personal access token.

    Safe to share across threads: ``httpx.Client`` handles concurrent requests, and
    ``points_used`` is updated under a lock.
    """

    def __init__(self, token: str | None = None, *, timeout: float = 30.0) -> None:
        token = token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise GitHubError(
                "no GitHub token: pass one explicitly or set the GITHUB_TOKEN environment variable"
            )
        self._client = httpx.Client(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "opensource-readme-typo-crawler",
            },
            timeout=timeout,
        )
        self.points_used = 0
        self._points_lock = threading.Lock()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @retry(retry=retry_if_exception(_is_retryable), **_RETRY_KW)
    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run one GraphQL query and return its ``data`` object."""
        resp = self._client.post("/graphql", json={"query": query, "variables": variables or {}})
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise GitHubError(str(payload["errors"]))
        data: dict[str, Any] = payload["data"]
        cost = (data.get("rateLimit") or {}).get("cost")
        if cost:
            with self._points_lock:
                self.points_used += cost
        return data

    @retry(retry=retry_if_exception(_is_retryable), **_RETRY_KW)
    def rest_get(self, path: str, *, etag: str | None = None) -> httpx.Response:
        """GET a REST endpoint. Returns the response as-is for 200/304/404.

        Raises :class:`GitHubRateLimitError` when the primary rate limit is exhausted, and
        lets other unexpected statuses raise through ``raise_for_status`` (so 5xx retries).
        """
        headers = {"If-None-Match": etag} if etag else {}
        resp = self._client.get(path, headers=headers)
        if resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0":
            raise GitHubRateLimitError(int(resp.headers.get("x-ratelimit-reset", "0")))
        if resp.status_code not in (200, 304, 404):
            resp.raise_for_status()
        return resp
