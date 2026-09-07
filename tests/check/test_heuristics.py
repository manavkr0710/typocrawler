from __future__ import annotations

import pytest

from typocrawler.check.heuristics import classify, load_allowlist

_PROSE = "this is a normal sentence with enough real words in it"


@pytest.mark.parametrize(
    "token, suggestion, context, reason",
    [
        ("recieve", "receive", _PROSE, ""),  # kept
        ("enviroment", "environment", _PROSE, ""),  # kept
        ("AKS", "ASK", _PROSE, "acronym"),
        ("hve", "HAVE", _PROSE, "acronym"),  # uppercase correction gives it away
        ("ue", "use", _PROSE, "too-short"),
        ("get_thing", "get_thing", _PROSE, "identifier"),
        ("fooBar", "foo bar", _PROSE, "identifier"),
        ("v2beta1", "v2 beta", _PROSE, "identifier"),
        ("café", "cafe", _PROSE, "non-ascii"),
        ("wil", "will", "| wil | x | y |", "fragment"),
        ("teh", "the", "a b c teh d e", "fragment"),  # mostly tiny tokens
    ],
)
def test_classify(token, suggestion, context, reason):
    v = classify(token, suggestion, context, allowlist=set())
    assert v.reason == reason
    assert v.keep == (reason == "")


def test_allowlist_rejects():
    v = classify("synopsys", "synopsis", _PROSE, allowlist={"synopsys"})
    assert not v.keep and v.reason == "allowlist"


def test_load_allowlist(tmp_path):
    f = tmp_path / "allow.txt"
    f.write_text("AKS  # azure\n\n# comment line\nSynopsys\n", encoding="utf-8")
    assert load_allowlist(f) == {"aks", "synopsys"}


def test_load_allowlist_missing_file_is_empty(tmp_path):
    assert load_allowlist(tmp_path / "nope.txt") == set()


def test_shipped_allowlist_loads():
    assert "aks" in load_allowlist()
