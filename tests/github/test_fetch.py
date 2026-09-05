from __future__ import annotations

import base64

import httpx
import pytest
import respx

from typocrawler.github.client import GitHubClient, GitHubRateLimitError
from typocrawler.github.fetch import fetch_readme

URL = "https://api.github.com/repos/acme/widgets/readme"


def _readme_json(text: str, sha: str = "sha123") -> dict:
    return {
        "path": "README.md",
        "sha": sha,
        "encoding": "base64",
        "content": base64.b64encode(text.encode()).decode(),
    }


@respx.mock
def test_fetch_readme_success():
    respx.get(URL).mock(
        return_value=httpx.Response(
            200, json=_readme_json("# Widgets\n\nreal prose"), headers={"etag": '"tag1"'}
        )
    )
    with GitHubClient("tok") as client:
        result = fetch_readme(client, "acme/widgets")
    assert result.status == "fetched"
    assert result.blob_sha == "sha123"
    assert result.etag == '"tag1"'
    assert "real prose" in result.raw_md


@respx.mock
def test_fetch_readme_not_modified_sends_conditional_header():
    route = respx.get(URL).mock(return_value=httpx.Response(304))
    with GitHubClient("tok") as client:
        result = fetch_readme(client, "acme/widgets", etag='"tag1"')
    assert result.status == "not_modified"
    assert route.calls.last.request.headers["if-none-match"] == '"tag1"'


@respx.mock
def test_fetch_readme_absent_on_404():
    respx.get(URL).mock(return_value=httpx.Response(404, json={"message": "Not Found"}))
    with GitHubClient("tok") as client:
        assert fetch_readme(client, "acme/widgets").status == "absent"


@respx.mock
def test_fetch_readme_skips_oversized():
    huge = "x" * 1_000_001
    respx.get(URL).mock(return_value=httpx.Response(200, json=_readme_json(huge)))
    with GitHubClient("tok") as client:
        assert fetch_readme(client, "acme/widgets").status == "skipped"


@respx.mock
def test_fetch_readme_raises_on_primary_rate_limit():
    respx.get(URL).mock(
        return_value=httpx.Response(
            403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000000"}
        )
    )
    with GitHubClient("tok") as client, pytest.raises(GitHubRateLimitError):
        fetch_readme(client, "acme/widgets")
