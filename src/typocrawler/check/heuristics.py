"""Cheap rules that reject the bulk of spell-checker false positives before the LLM stage.

The checkers are low-noise but not clean: acronyms (``AKS`` -> "ASK"), product names
(``Synopsys``), code identifiers, and fragments shredded out of ASCII tables all slip through.
Each rule here is conservative — when unsure, keep the finding and let stint 6 (LLM) decide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ALLOWLIST_PATH = Path("config/allowlist.txt")

_MIN_TOKEN_LEN = 3
_CAMEL = re.compile(r"[a-z][A-Z]|[A-Z]{2}[a-z]")


@dataclass(frozen=True)
class Verdict:
    keep: bool
    reason: str  # "" when kept, otherwise the rule that rejected it


def load_allowlist(path: str | Path | None = None) -> set[str]:
    """Read ``config/allowlist.txt`` — one word per line, ``#`` comments, case-insensitive."""
    p = Path(path) if path is not None else DEFAULT_ALLOWLIST_PATH
    if not p.is_file():
        return set()
    words: set[str] = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        word = line.split("#", 1)[0].strip().lower()
        if word:
            words.add(word)
    return words


def _looks_like_noise(context: str) -> bool:
    """Table rows and ASCII art — where 'wil', 'hve' etc. come from."""
    if context.count("|") >= 2:
        return True
    words = context.split()
    if len(words) < 3:
        return True
    tiny = sum(1 for w in words if len(w.strip(".,:;()[]")) <= 2)
    return tiny / len(words) > 0.5


def classify(token: str, suggestion: str, context: str, allowlist: set[str]) -> Verdict:
    t = token.strip()
    low = t.lower()

    if low in allowlist:
        return Verdict(False, "allowlist")
    if len(t) < _MIN_TOKEN_LEN:
        return Verdict(False, "too-short")
    if t.isupper() and len(t) <= 5:
        return Verdict(False, "acronym")
    if suggestion.isupper() and not suggestion.islower():
        # checker only uppercases a correction when the source token was acronym-shaped
        return Verdict(False, "acronym")
    if any(c.isdigit() for c in t) or "_" in t or _CAMEL.search(t):
        return Verdict(False, "identifier")
    if not t.isascii():
        return Verdict(False, "non-ascii")
    if _looks_like_noise(context):
        return Verdict(False, "fragment")
    return Verdict(True, "")
