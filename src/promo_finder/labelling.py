"""list-lines: one markdown table per episode so the labeller can pick line IDs.

Files go to outputs/labelling/ (git-ignored). The console only ever shows paths and counts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import Episode

HELD_OUT_SPEC = "1-4,11-14,26-29,42-45"
HELD_OUT: tuple[int, ...] = (1, 2, 3, 4, 11, 12, 13, 14, 26, 27, 28, 29, 42, 43, 44, 45)
BLOCKS: dict[str, tuple[int, ...]] = {"A": (1, 2, 3, 4), "B": (11, 12, 13, 14),
                                      "C": (26, 27, 28, 29), "D": (42, 43, 44, 45)}

# P08b fresh set: sealed until the score-once gate (counts only before that).
FRESH_SPEC = "31-34"
FRESH: tuple[int, ...] = (31, 32, 33, 34)
FRESH_BLOCKS: dict[str, tuple[int, ...]] = {"F": FRESH}

# P08b fresh block B: the 4 episodes where v2 changes the kept candidates most, picked by code from builder
# output only (tools/pick_block_b.py; the rule is in eval/match_rule_fresh_b.md). Sealed like block A.
FRESH_B_SPEC = "15-17,35"
FRESH_B: tuple[int, ...] = (15, 16, 17, 35)
FRESH_B_BLOCKS: dict[str, tuple[int, ...]] = {"FB": FRESH_B}
SEALED: tuple[int, ...] = FRESH + FRESH_B   # no promo content, span, line id or score before the score-once gate


@dataclass(frozen=True)
class Split:
    """An evaluation split: which episodes it covers and how its labels are checked."""

    name: str
    episodes: tuple[int, ...]
    blocks: dict[str, tuple[int, ...]]
    spec: str
    not_in_code: str                 # row error for a label outside the split
    pos_range: tuple[int, int]       # warnings only
    neg_range: tuple[int, int]
    pos_target: str
    neg_target: str
    other_label: str                 # report text for labels outside every block
    subdir: str                      # under outputs/labelling/ ("" = the folder itself)
    default_workbook: str
    default_gold: str


HELD_OUT_SPLIT = Split(
    name="held-out", episodes=HELD_OUT, blocks=BLOCKS, spec=HELD_OUT_SPEC, not_in_code="NOT_HELD_OUT",
    pos_range=(12, 18), neg_range=(3, 7), pos_target="~15", neg_target="~5",
    other_label="not held-out / unreadable", subdir="",
    default_workbook="outputs/labelling/gold_labelling.xlsx", default_gold="eval/gold.csv")
FRESH_SPLIT = Split(
    name="fresh", episodes=FRESH, blocks=FRESH_BLOCKS, spec=FRESH_SPEC, not_in_code="NOT_IN_SPLIT",
    pos_range=(6, 10), neg_range=(1, 3), pos_target="~8", neg_target="~2",
    other_label="not in fresh split / unreadable", subdir="fresh",
    default_workbook="outputs/labelling/fresh/gold_labelling_fresh.xlsx", default_gold="eval/gold_fresh.csv")
FRESH_B_SPLIT = Split(
    name="fresh_b", episodes=FRESH_B, blocks=FRESH_B_BLOCKS, spec=FRESH_B_SPEC, not_in_code="NOT_IN_SPLIT",
    pos_range=(6, 10), neg_range=(1, 3), pos_target="~8", neg_target="~2",
    other_label="not in fresh_b split / unreadable", subdir="fresh_b",
    default_workbook="outputs/labelling/fresh_b/gold_labelling_fresh_b.xlsx", default_gold="eval/gold_fresh_b.csv")
SPLITS: dict[str, Split] = {"held-out": HELD_OUT_SPLIT, "fresh": FRESH_SPLIT, "fresh_b": FRESH_B_SPLIT}

_PART = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$")


def parse_eps(spec: str) -> list[int]:
    """'1-4,11,13-14' -> [1, 2, 3, 4, 11, 13, 14] (sorted, unique). Raises ValueError on bad input."""
    out: set[int] = set()
    for part in spec.split(","):
        m = _PART.match(part)
        if not m:
            raise ValueError(f"bad episode list item: {part!r}")
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if b < a or a < 1:
            raise ValueError(f"bad episode range: {part!r}")
        out.update(range(a, b + 1))
    return sorted(out)


def compact_eps(eps) -> str:
    """[15, 16, 17, 35] -> '15-17,35' (the inverse of parse_eps for sorted episode lists)."""
    eps = sorted(set(eps))
    parts, start = [], 0
    for i in range(1, len(eps) + 1):
        if i == len(eps) or eps[i] != eps[i - 1] + 1:
            a, b = eps[start], eps[i - 1]
            parts.append(str(a) if a == b else f"{a}-{b}")
            start = i
    return ",".join(parts)


def fmt_ms(ms: int) -> str:
    """Milliseconds -> mm:ss.s (rounded to the nearest tenth, half up)."""
    tenths = (int(ms) + 50) // 100
    return f"{tenths // 600:02d}:{(tenths % 600) // 10:02d}.{tenths % 10}"


def _cell(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).replace("|", "\\|")


def render_episode(ep: Episode) -> tuple[str, int, int]:
    """Return (markdown, line_rows, scene_markers)."""
    out = [f"# E{ep.ep:02d}  duration {fmt_ms(ep.duration_ms)}", "",
           "| line_id | start | end | kind | speaker | emotion | text |",
           "|---|---|---|---|---|---|---|"]
    rows = markers = 0
    scene = None
    for ln in ep.lines:
        if ln.scene != scene:
            scene = ln.scene
            markers += 1
            out.append(f"| --- scene {scene} --- | | | | | | |")
        speaker = ln.speaker if ln.kind == "dialogue" else None
        out.append(f"| {ln.id} | {fmt_ms(ln.start_ms)} | {fmt_ms(ln.end_ms)} | {ln.kind} | "
                   f"{_cell(speaker)} | {_cell(ln.emotion)} | {_cell(ln.text)} |")
        rows += 1
    return "\n".join(out) + "\n", rows, markers


def write_labelling(episodes: list[Episode], eps: list[int], out_dir: Path) -> tuple[list[tuple[Path, int, int]], list[int]]:
    """Write E##_lines.md for each requested episode. Returns (written, missing_eps)."""
    by_ep = {e.ep: e for e in episodes}
    out_dir.mkdir(parents=True, exist_ok=True)
    written, missing = [], []
    for n in eps:
        e = by_ep.get(n)
        if e is None:
            missing.append(n)
            continue
        text, rows, markers = render_episode(e)
        p = out_dir / f"E{n:02d}_lines.md"
        p.write_bytes(text.encode("utf-8"))
        written.append((p, rows, markers))
    return written, missing
