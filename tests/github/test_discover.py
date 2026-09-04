from __future__ import annotations

import httpx
import pytest
import respx

from typocrawler.config import ResolvedOrg
from typocrawler.github.client import GitHubClient, GitHubError
from typocrawler.github.discover import RepoRecord, iter_org_repos, should_keep


def _node(name: str, **kw) -> dict:
    return {
        "nameWithOwner": name,
        "isArchived": kw.get("archived", False),
        "isFork": kw.get("fork", False),
        "stargazerCount": kw.get("stars", 0),
        "pushedAt": kw.get("pushed_at", "2024-01-01T00:00:00Z"),
        "defaultBranchRef": {"name": kw.get("branch", "main")},
    }


def _page(nodes: list[dict], *, has_next: bool = False, cursor: str | None = None) -> dict:
    return {
        "data": {
            "rateLimit": {"cost": 1},
            "organization": {
                "repositories": {
                    "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                    "nodes": nodes,
                }
            },
        }
    }


@respx.mock
def test_iter_org_repos_paginates():
    route = respx.post("https://api.github.com/graphql")
    route.side_effect = [
        httpx.Response(200, json=_page([_node("google/a")], has_next=True, cursor="c1")),
        httpx.Response(200, json=_page([_node("google/b")], has_next=False)),
    ]
    with GitHubClient("tok") as client:
        names = [r.full_name for r in iter_org_repos(client, "google")]
    assert names == ["google/a", "google/b"]
    assert route.call_count == 2


@respx.mock
def test_iter_org_repos_raises_for_unknown_org():
    respx.post("https://api.github.com/graphql").mock(
        return_value=httpx.Response(
            200, json={"data": {"rateLimit": {"cost": 1}, "organization": None}}
        )
    )
    with GitHubClient("tok") as client, pytest.raises(GitHubError, match="no such GitHub org"):
        list(iter_org_repos(client, "nope"))


def test_should_keep_filters_archived_forks_and_low_stars():
    org = ResolvedOrg(
        login="google", min_stars=10, include_forks=False, include_archived=False, extra_paths=[]
    )
    keep = RepoRecord("google/keep", "main", 20, False, False, None)
    low_stars = RepoRecord("google/low", "main", 1, False, False, None)
    archived = RepoRecord("google/old", "main", 20, True, False, None)
    fork = RepoRecord("google/fork", "main", 20, False, True, None)

    assert should_keep(keep, org)
    assert not should_keep(low_stars, org)
    assert not should_keep(archived, org)
    assert not should_keep(fork, org)


def test_should_keep_honours_relaxed_org_rules():
    org = ResolvedOrg(
        login="google", min_stars=0, include_forks=True, include_archived=True, extra_paths=[]
    )
    archived_fork = RepoRecord("google/both", "main", 0, True, True, None)
    assert should_keep(archived_fork, org)
