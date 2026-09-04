"""Thin GitHub GraphQL client: auth, retries, and rate-limit point tracking."""

from __future__ import annotations

import os
import threading
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

_RETRYABLE_STATUS = {502, 503, 504}


class GitHubError(RuntimeError):
    """Missing auth, an unknown org, or a GraphQL-level error in the response."""


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
    """A GraphQL client for the GitHub API, authenticated with a personal access token.

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

    @retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception(_is_retryable),
    )
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
