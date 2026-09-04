"""Enumerate an org's repositories via GitHub's GraphQL API.

Filters (archived / forks / min stars) are applied client-side in :func:`should_keep` rather
than as GraphQL arguments — GitHub's schema doesn't expose an ``isArchived``/star-count filter
on the ``repositories`` connection, so we page through everything and filter after.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

from typocrawler.config import ResolvedOrg
from typocrawler.github.client import GitHubClient, GitHubError

REPO_QUERY = """
query($login: String!, $cursor: String) {
  rateLimit { cost remaining resetAt }
  organization(login: $login) {
    repositories(first: 100, after: $cursor, orderBy: {field: NAME, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        isArchived
        isFork
        stargazerCount
        pushedAt
        defaultBranchRef { name }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class RepoRecord:
    full_name: str
    default_branch: str
    stars: int
    is_archived: bool
    is_fork: bool
    pushed_at: datetime | None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def iter_org_repos(client: GitHubClient, login: str) -> Iterator[RepoRecord]:
    """Yield every repository in ``login``, paginating as needed.

    Raises :class:`GitHubError` if ``login`` isn't a GitHub organization.
    """
    cursor: str | None = None
    while True:
        data = client.query(REPO_QUERY, {"login": login, "cursor": cursor})
        org = data.get("organization")
        if org is None:
            raise GitHubError(f"no such GitHub organization: {login!r}")
        block = org["repositories"]
        for node in block["nodes"]:
            yield RepoRecord(
                full_name=node["nameWithOwner"],
                default_branch=(node.get("defaultBranchRef") or {}).get("name") or "main",
                stars=node["stargazerCount"],
                is_archived=node["isArchived"],
                is_fork=node["isFork"],
                pushed_at=_parse_dt(node.get("pushedAt")),
            )
        page = block["pageInfo"]
        if not page["hasNextPage"]:
            return
        cursor = page["endCursor"]


def should_keep(record: RepoRecord, org: ResolvedOrg) -> bool:
    """Apply an org's scope filters to one discovered repo."""
    if record.is_archived and not org.include_archived:
        return False
    if record.is_fork and not org.include_forks:
        return False
    return record.stars >= org.min_stars
