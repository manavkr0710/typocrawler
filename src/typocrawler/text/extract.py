"""Reduce README markdown to plain prose worth spell-checking.

Everything that reliably produces false positives is dropped: fenced/indented code, inline
code, raw HTML (badges, shields), image alt text, and link URLs (the link *text* is kept).
What survives is one line of prose per source block.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark")

_DROP_INLINE = {"code_inline", "image", "html_inline"}
_BREAKS = {"softbreak", "hardbreak"}
_WS = re.compile(r"[ \t]{2,}")


def _inline_prose(children: list) -> str:
    parts: list[str] = []
    for child in children:
        if child.type in _DROP_INLINE:
            continue
        if child.type in _BREAKS:
            parts.append(" ")
        elif child.type == "text":
            parts.append(child.content)
        # emphasis / strong / strikethrough / link open+close markers: skipped,
        # their inner text tokens are kept.
    return _WS.sub(" ", "".join(parts)).strip()


def extract_lines(markdown: str) -> list[tuple[int, str]]:
    """``(source_line, prose)`` for each non-empty block, source line 1-based.

    The source line lets a finding point back to a real line in the original README even
    though the checkers run on the stripped-down prose.
    """
    out: list[tuple[int, str]] = []
    source_line = 1
    for token in _md.parse(markdown):
        if token.map:
            source_line = token.map[0] + 1
        if token.type == "inline" and token.children:
            text = _inline_prose(token.children)
            if text:
                out.append((source_line, text))
    return out


def extract_prose(markdown: str) -> str:
    """Return the checkable prose of a README as newline-separated lines."""
    return "\n".join(text for _, text in extract_lines(markdown))
