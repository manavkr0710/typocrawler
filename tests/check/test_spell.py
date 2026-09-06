from __future__ import annotations

from typocrawler.check.spell import RawHit, crossref, run_codespell, run_typos


def _write(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding="utf-8")


def test_run_codespell_finds_known_misspellings(tmp_path):
    _write(tmp_path, "00000001.txt", "You will recieve teh files.\n")
    hits = run_codespell(tmp_path)
    words = {h.word for h in hits}
    assert {"recieve", "teh"} <= words
    assert all(h.source == "codespell" for h in hits)
    assert next(h for h in hits if h.word == "recieve").suggestion == "receive"
    assert next(h for h in hits if h.word == "recieve").file_key == "00000001"


def test_run_typos_finds_known_misspellings(tmp_path):
    _write(tmp_path, "00000002.txt", "line one is fine\nyou will recieve it\n")
    hits = run_typos(tmp_path)
    recieve = next(h for h in hits if h.word == "recieve")
    assert recieve.line == 2
    assert recieve.suggestion == "receive"
    assert recieve.source == "typos"


def test_run_codespell_clean_file_returns_nothing(tmp_path):
    _write(tmp_path, "00000003.txt", "This sentence is entirely correct.\n")
    assert run_codespell(tmp_path) == []


def test_crossref_marks_agreement_and_scores():
    hits = [
        RawHit("f", 3, 0, "recieve", "receive", "codespell"),
        RawHit("f", 3, 10, "recieve", "receive", "typos"),
        RawHit("f", 5, 0, "wrok", "work", "codespell"),
    ]
    merged = {(m.line, m.word): m for m in crossref(hits)}

    agreed = merged[(3, "recieve")]
    assert agreed.source == "both"
    assert agreed.score == 2
    assert agreed.col == 10  # picks up the column typos provided

    solo = merged[(5, "wrok")]
    assert solo.source == "codespell"
    assert solo.score == 1
