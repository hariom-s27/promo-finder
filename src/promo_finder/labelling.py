"""list-lines: one markdown table per episode so the labeller can pick line IDs.

Files go to outputs/labelling/ (git-ignored). The console only ever shows paths and counts.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import Episode

HELD_OUT_SPEC = "1-4,11-14,26-29,42-45"
HELD_OUT: tuple[int, ...] = (1, 2, 3, 4, 11, 12, 13, 14, 26, 27, 28, 29, 42, 43, 44, 45)
BLOCKS: dict[str, tuple[int, ...]] = {"A": (1, 2, 3, 4), "B": (11, 12, 13, 14),
                                      "C": (26, 27, 28, 29), "D": (42, 43, 44, 45)}

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
