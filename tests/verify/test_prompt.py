from __future__ import annotations

import pytest

from typocrawler.verify.prompt import VerifyItem, build_prompt, parse_response

_ITEMS = [
    VerifyItem("recieve", "receive", "you will recieve the callback later", "netflix/foo"),
    VerifyItem("Synopsys", "synopsis", "built with Synopsys tools", "acme/bar"),
]


def test_build_prompt_lists_every_word_with_its_sentence():
    prompt = build_prompt(_ITEMS)
    assert '1. "recieve" — sentence: you will recieve the callback later' in prompt
    assert '2. "Synopsys"' in prompt
    assert "misspelled" in prompt


def test_build_prompt_collapses_context_whitespace():
    prompt = build_prompt([VerifyItem("x", "y", "a\n\n  b\tc", "r/r")])
    assert "sentence: a b c" in prompt


def test_parse_response_maps_booleans_to_verdicts():
    results = parse_response('[{"misspelled": true}, {"misspelled": false}]', 2)
    assert results[0].verdict == "typo"
    assert results[1].verdict == "not_typo"
    assert all(r.correction == "" for r in results)


def test_parse_response_null_or_missing_is_unsure():
    results = parse_response('[{"misspelled": null}, {"foo": 1}]', 2)
    assert results[0].verdict == "unsure"
    assert results[1].verdict == "unsure"


def test_parse_response_tolerates_fences_and_prose():
    text = 'Here you go:\n```json\n[{"misspelled": true}]\n```\nHope that helps!'
    assert parse_response(text, 1)[0].verdict == "typo"


def test_parse_response_pads_and_truncates_to_expected_count():
    assert len(parse_response('[{"misspelled": true}]', 3)) == 3
    assert len(parse_response('[{"misspelled": true},{"misspelled": true}]', 1)) == 1


def test_parse_response_raises_without_an_array():
    with pytest.raises(ValueError, match="no JSON array"):
        parse_response("the model said no", 1)
