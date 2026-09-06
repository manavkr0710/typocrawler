from __future__ import annotations

import pytest

from typocrawler.text.extract import extract_lines, extract_prose

FENCED = """Some intro text.

```python
recieve = teh_value  # misspellings in code must not leak
```

Closing text.
"""


@pytest.mark.parametrize(
    "markdown, present, absent",
    [
        ("# Hello world", ["Hello world"], []),
        (FENCED, ["Some intro text.", "Closing text."], ["recieve", "teh_value"]),
        ("Call the `recieve()` helper at teh end.", ["at teh end"], ["recieve"]),
        (
            "See [the recieve guide](https://example.com/recieve-docs) now.",
            ["the recieve guide", "now"],
            ["https", "example.com", "recieve-docs"],
        ),
        (
            "[![Build](https://img.shields.io/x.svg)](https://ci.example.com/x)",
            [],
            ["Build", "shields", "img"],
        ),
        ("<p>Some <b>bolded</b> words.</p>", [], ["bolded"]),
        ("Press <kbd>Ctrl</kbd> to continue.", ["Press", "continue"], ["<kbd>", "</kbd>"]),
        (
            "First paragraph here.\n\nSecond paragraph here.",
            ["First paragraph here.", "Second paragraph here."],
            [],
        ),
    ],
)
def test_extract_prose(markdown, present, absent):
    out = extract_prose(markdown)
    for s in present:
        assert s in out, f"expected {s!r} in {out!r}"
    for s in absent:
        assert s not in out, f"did not expect {s!r} in {out!r}"


def test_real_typos_survive_extraction():
    md = "## Overview\n\nThis prokect hepls you managae your files.\n"
    out = extract_prose(md)
    assert "prokect" in out
    assert "hepls" in out
    assert "managae" in out


def test_extract_lines_maps_to_source_line_numbers():
    md = "# Title\n\n```\ncode teh\n```\n\nProse with recieve here.\n"
    lines = extract_lines(md)
    assert lines[0] == (1, "Title")
    # the prose paragraph starts on source line 7, past the fenced code block
    assert lines[1][0] == 7
    assert "recieve" in lines[1][1]
