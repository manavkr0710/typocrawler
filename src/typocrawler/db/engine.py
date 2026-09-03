"""Engine construction with SQLite pragmas suited to a single-writer batch workload."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.pool import StaticPool

DEFAULT_DB_PATH = Path("typos.db")


def _apply_pragmas(dbapi_connection, _record) -> None:
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


def make_engine(db_path: str | Path = DEFAULT_DB_PATH, *, echo: bool = False) -> Engine:
    """Create a SQLite engine.

    ``":memory:"`` yields a single shared in-memory database (handy for tests); any other value
    is treated as a file path.
    """
    if str(db_path) == ":memory:":
        engine = create_engine(
            "sqlite://",
            echo=echo,
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(f"sqlite:///{Path(db_path)}", echo=echo, future=True)
    event.listen(engine, "connect", _apply_pragmas)
    return engine
