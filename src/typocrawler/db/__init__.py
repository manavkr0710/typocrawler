"""Database package: schema (:mod:`.models`) and engine construction (:mod:`.engine`)."""

from __future__ import annotations

from sqlalchemy import Engine

from typocrawler.db.engine import DEFAULT_DB_PATH, make_engine
from typocrawler.db.models import (
    crawl_runs,
    findings,
    metadata,
    orgs,
    readme_snapshots,
    repos,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "make_engine",
    "metadata",
    "orgs",
    "repos",
    "readme_snapshots",
    "findings",
    "crawl_runs",
    "init_db",
]


def init_db(db_path=DEFAULT_DB_PATH) -> Engine:
    """Create every table if it does not yet exist and return the engine."""
    engine = make_engine(db_path)
    metadata.create_all(engine)
    return engine
