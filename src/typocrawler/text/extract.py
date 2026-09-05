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


def extract_prose(markdown: str) -> str:
    """Return the checkable prose of a README as newline-separated lines."""
    lines: list[str] = []
    for token in _md.parse(markdown):
        if token.type == "inline" and token.children:
            text = _inline_prose(token.children)
            if text:
                lines.append(text)
    return "\n".join(lines)
