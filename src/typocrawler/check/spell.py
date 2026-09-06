"""Drive ``codespell`` and ``typos`` over a directory of prose files and merge their hits.

Both tools ship curated common-misspelling lists (not a full dictionary diff), so their raw
output is already fairly low-noise. When they agree on a word, confidence is higher — that's
recorded as ``source="both"``. Heavier false-positive filtering is stint 5's job.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_CODESPELL_LINE = re.compile(r"^(?P<path>.+):(?P<line>\d+): (?P<word>\S+) ==> (?P<fix>.+)$")


@dataclass(frozen=True)
class RawHit:
    file_key: str
    line: int
    col: int
    word: str
    suggestion: str
    source: str  # "codespell" | "typos"


@dataclass(frozen=True)
class MergedHit:
    file_key: str
    line: int
    col: int
    word: str
    suggestion: str
    source: str  # "codespell" | "typos" | "both"
    score: int


def _tool(name: str) -> str:
    """Resolve a checker executable, preferring the one alongside the running interpreter."""
    here = Path(sys.executable).parent
    for candidate in (here / name, here / f"{name}.exe"):
        if candidate.exists():
            return str(candidate)
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"{name!r} not found on PATH — run `pip install -e .`")
    return found


def run_codespell(directory: Path) -> list[RawHit]:
    proc = subprocess.run(
        [_tool("codespell"), "--disable-colors", str(directory)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 65):  # 65 == misspellings found
        raise RuntimeError(f"codespell failed ({proc.returncode}): {proc.stderr.strip()}")

    hits: list[RawHit] = []
    for line in proc.stdout.splitlines():
        m = _CODESPELL_LINE.match(line.strip())
        if not m:
            continue
        fix = m["fix"].split(",")[0].strip().rstrip(".")
        hits.append(
            RawHit(
                file_key=Path(m["path"]).stem,
                line=int(m["line"]),
                col=0,
                word=m["word"],
                suggestion=fix,
                source="codespell",
            )
        )
    return hits


def run_typos(directory: Path) -> list[RawHit]:
    proc = subprocess.run(
        [_tool("typos"), "--format", "json", str(directory)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 2):  # 2 == typos found
        raise RuntimeError(f"typos failed ({proc.returncode}): {proc.stderr.strip()}")

    hits: list[RawHit] = []
    for line in proc.stdout.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "typo" or not obj.get("corrections"):
            continue
        hits.append(
            RawHit(
                file_key=Path(obj["path"]).stem,
                line=int(obj["line_num"]),
                col=int(obj.get("byte_offset", 0)),
                word=obj["typo"],
                suggestion=obj["corrections"][0],
                source="typos",
            )
        )
    return hits


def crossref(hits: list[RawHit]) -> list[MergedHit]:
    """Collapse hits on the same (file, line, word) and mark agreement."""
    grouped: dict[tuple[str, int, str], dict] = {}
    for h in hits:
        key = (h.file_key, h.line, h.word.lower())
        cur = grouped.setdefault(
            key,
            {"sources": set(), "col": h.col, "word": h.word, "suggestion": h.suggestion},
        )
        cur["sources"].add(h.source)
        if h.col and not cur["col"]:
            cur["col"] = h.col

    merged: list[MergedHit] = []
    for (file_key, line, _), v in grouped.items():
        both = v["sources"] == {"codespell", "typos"}
        merged.append(
            MergedHit(
                file_key=file_key,
                line=line,
                col=v["col"],
                word=v["word"],
                suggestion=v["suggestion"],
                source="both" if both else next(iter(v["sources"])),
                score=2 if both else 1,
            )
        )
    return merged
