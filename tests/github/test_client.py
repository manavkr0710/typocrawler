from __future__ import annotations

import httpx
import pytest
import respx

from typocrawler.github.client import GitHubClient, GitHubError


def test_requires_a_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(GitHubError, match="no GitHub token"):
        GitHubClient(None)


def test_env_token_is_picked_up(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    with GitHubClient(None) as client:
        assert client._client.headers["authorization"] == "Bearer from-env"


@respx.mock
def test_query_returns_data_and_tracks_rate_limit_points():
    respx.post("https://api.github.com/graphql").mock(
        return_value=httpx.Response(200, json={"data": {"rateLimit": {"cost": 1}, "foo": "bar"}})
    )
    with GitHubClient("tok") as client:
        data = client.query("query { foo }")
        assert data["foo"] == "bar"
        assert client.points_used == 1


@respx.mock
def test_query_raises_on_graphql_errors():
    respx.post("https://api.github.com/graphql").mock(
        return_value=httpx.Response(200, json={"errors": [{"message": "bad query"}]})
    )
    with GitHubClient("tok") as client, pytest.raises(GitHubError, match="bad query"):
        client.query("query { foo }")


@respx.mock
def test_query_retries_transient_server_errors_then_succeeds():
    route = respx.post("https://api.github.com/graphql")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, json={"data": {"ok": True}}),
    ]
    with GitHubClient("tok") as client:
        data = client.query("query { ok }")
        assert data["ok"] is True
        assert route.call_count == 2
