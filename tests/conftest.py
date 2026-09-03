from __future__ import annotations

import pytest
from sqlalchemy import Engine

from typocrawler.db import make_engine, metadata


@pytest.fixture
def engine(tmp_path) -> Engine:
    eng = make_engine(tmp_path / "test.db")
    metadata.create_all(eng)
    return eng
