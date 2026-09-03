from __future__ import annotations

import textwrap

import pytest

from typocrawler.config import DEFAULT_CONFIG_PATH, load_config


def _write(tmp_path, body: str):
    p = tmp_path / "orgs.yml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_shipped_config_loads():
    cfg = load_config(DEFAULT_CONFIG_PATH)
    logins = {o.login for o in cfg.resolved()}
    assert {"google", "microsoft", "facebook"} <= logins


def test_defaults_apply_and_are_overridable(tmp_path):
    path = _write(
        tmp_path,
        """
        defaults:
          min_stars: 10
          include_forks: true
        orgs:
          - login: google
          - login: microsoft
            min_stars: 500
        """,
    )
    resolved = {o.login: o for o in load_config(path).resolved()}

    assert resolved["google"].min_stars == 10
    assert resolved["google"].include_forks is True
    assert resolved["microsoft"].min_stars == 500
    assert resolved["microsoft"].include_forks is True


def test_duplicate_org_rejected(tmp_path):
    path = _write(
        tmp_path,
        """
        orgs:
          - login: google
          - login: Google
        """,
    )
    with pytest.raises(ValueError, match="duplicate org"):
        load_config(path)


def test_empty_org_list_rejected(tmp_path):
    path = _write(tmp_path, "orgs: []\n")
    with pytest.raises(ValueError, match="at least one org"):
        load_config(path)


def test_unknown_key_rejected(tmp_path):
    path = _write(
        tmp_path,
        """
        orgs:
          - login: google
            colour: blue
        """,
    )
    with pytest.raises(ValueError):
        load_config(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yml")
