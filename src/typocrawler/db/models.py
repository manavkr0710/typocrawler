"""SQLAlchemy Core schema.

Kept as Core ``Table`` definitions (not the ORM) — this is a batch pipeline with a handful of
tables, and staying close to SQL keeps a future Postgres migration mechanical.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)

metadata = MetaData()

FINDING_STATUSES = ("new", "confirmed", "false_positive", "fixed")
FINDING_SOURCES = ("codespell", "typos", "both")
LLM_VERDICTS = ("typo", "not_typo", "unsure")


def _in_list(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    joined = ",".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({joined})", name=name)


orgs = Table(
    "orgs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("login", String, nullable=False, unique=True),
    Column("added_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

repos = Table(
    "repos",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("org_id", Integer, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
    Column("full_name", String, nullable=False, unique=True),
    Column("default_branch", String, nullable=False, server_default="main"),
    Column("stars", Integer, nullable=False, server_default="0"),
    Column("is_archived", Boolean, nullable=False, server_default="0"),
    Column("is_fork", Boolean, nullable=False, server_default="0"),
    Column("pushed_at", DateTime(timezone=True)),
    Column("readme_path", String),
    Column("readme_blob_sha", String),
    Column("readme_etag", String),
    Column("readme_checked_at", DateTime(timezone=True)),
    Column("last_checked_at", DateTime(timezone=True)),
)

readme_snapshots = Table(
    "readme_snapshots",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repo_id", Integer, ForeignKey("repos.id", ondelete="CASCADE"), nullable=False),
    Column("blob_sha", String, nullable=False),
    Column("fetched_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("raw_md", Text, nullable=False),
    Column("extracted_text", Text, nullable=False),
    Column("checked_at", DateTime(timezone=True)),
    UniqueConstraint("repo_id", "blob_sha", name="uq_snapshot_repo_blob"),
)

findings = Table(
    "findings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repo_id", Integer, ForeignKey("repos.id", ondelete="CASCADE"), nullable=False),
    Column("blob_sha", String, nullable=False),
    Column("line_no", Integer, nullable=False),
    Column("col", Integer, nullable=False, server_default="0"),
    Column("token", String, nullable=False),
    Column("suggestion", String, nullable=False),
    Column("context_snippet", Text, nullable=False, server_default=""),
    Column("source", String, nullable=False),
    Column("heuristic_score", Integer, nullable=False, server_default="0"),
    Column("filter_reason", String),
    Column("llm_verdict", String),
    Column("llm_correction", String),
    Column("status", String, nullable=False, server_default="new"),
    Column("first_seen_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    UniqueConstraint("repo_id", "token", "line_no", "blob_sha", name="uq_finding_dedup"),
    _in_list("status", FINDING_STATUSES, "ck_finding_status"),
    _in_list("source", FINDING_SOURCES, "ck_finding_source"),
)

crawl_runs = Table(
    "crawl_runs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("started_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("repos_scanned", Integer, nullable=False, server_default="0"),
    Column("api_points_used", Integer, nullable=False, server_default="0"),
    Column("findings_new", Integer, nullable=False, server_default="0"),
    Column("findings_confirmed", Integer, nullable=False, server_default="0"),
)
