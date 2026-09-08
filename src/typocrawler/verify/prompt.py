"""Build the verification prompt and parse the model's reply. No network here — pure and tested.

The model is asked a plain ``misspelled: true | false`` question per word (small models handle
that far better than a "typo / not_typo" vocabulary). Corrections come from the spell-checkers,
not the model, so we don't ask for them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_FENCE = re.compile(r"```(?:json)?|```")

_INSTRUCTIONS = (
    "Below are words a spell-checker flagged in software project README files, each with the "
    "sentence it appeared in. For EACH word decide whether it is genuinely MISSPELLED (a real "
    "spelling error that should be fixed) or FINE — a correct word, a name (product / company / "
    "person), a technical term, an abbreviation, code, or another language used on purpose.\n"
    "\n"
    "Reply with ONLY a JSON array, one object per word, in the same order:\n"
    '  {"misspelled": true}   or   {"misspelled": false}\n'
    'Use {"misspelled": null} only when the sentence gives you no way to tell.'
)


@dataclass(frozen=True)
class VerifyItem:
    token: str
    suggestion: str
    context: str
    repo: str


@dataclass(frozen=True)
class VerifyResult:
    verdict: str  # "typo" | "not_typo" | "unsure"
    correction: str = ""  # always "" — kept for the pipeline's shape


def build_prompt(items: list[VerifyItem]) -> str:
    lines = [_INSTRUCTIONS, "", "Words:"]
    for n, it in enumerate(items, 1):
        sentence = " ".join(it.context.split())[:200]
        lines.append(f'{n}. "{it.token}" — sentence: {sentence}')
    return "\n".join(lines)


def _verdict(misspelled: object) -> str:
    if misspelled is True:
        return "typo"
    if misspelled is False:
        return "not_typo"
    return "unsure"


def parse_response(text: str, expected: int) -> list[VerifyResult]:
    """Parse the model's JSON array, tolerating fences/prose, padded/truncated to ``expected``."""
    cleaned = _FENCE.sub("", text)
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON array in model response: {text[:200]!r}")

    data = json.loads(cleaned[start : end + 1])
    results = [VerifyResult(_verdict(obj.get("misspelled"))) for obj in data]
    results.extend(VerifyResult("unsure") for _ in range(expected - len(results)))
    return results[:expected]
