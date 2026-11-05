"""Parse timestamped episode screenplays into Episode / Scene / Line.

The parser never crashes on one bad block: it records a ParseWarning (no script text)
and continues. Line IDs are assigned in file order, so the same file always gives the
same IDs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Optional

from .models import Episode, Line, ParseWarning, Scene, line_id

FILENAME_RE = re.compile(r"^episode-(\d+)-Episode\s*(\d+)\.txt$", re.I)
HEADER_RE = re.compile(r"^\s*(EPISODE NUMBER|EPISODE LOGLINE|CONTINUITY NOTES)\s*:\s*(.*)$", re.I)
START_RE = re.compile(r"^\s*-{2,}\s*SCRIPT\s+START\s*-{2,}\s*$", re.I)
END_RE = re.compile(r"^\s*-{2,}\s*SCRIPT\s+END\s*-{2,}\s*$", re.I)
SCENE_RE = re.compile(r"^\s*SCENE\s+(\d+)\s*:?\s*$", re.I)
FIELD_RE = re.compile(r"^\s*(scene heading|scene start|scene end|actions and dialogue)\s*:\s*(.*)$", re.I)
LABEL_RE = re.compile(r"^\s*\*\*\s*(.+?)\s*\*\*\s*:?\s*$")
TIMING_RE = re.compile(
    r"^\s*start\s*:\s*\(?\s*([^()|]*?)\s*\)?\s*\|\s*end\s*:\s*\(?\s*([^()|]*?)\s*\)?\s*$", re.I
)

_HMS = re.compile(r"^(\d+):([0-5]?\d):([0-5]?\d)(?:[.,](\d+))?$")
_MS = re.compile(r"^(\d+):([0-5]?\d)(?:[.,](\d+))?$")

# Non-speaker labels (lower-case, brackets removed) -> kind. Anything else is a speaker.
NON_DIALOGUE = {
    "camera": "camera",
    "action": "action",
    "sound fx": "sfx",
    "sfx": "sfx",
    "sound": "sfx",
    "sound effect": "sfx",
    "sound effects": "sfx",
    "music": "other",
    "transition": "other",
    "text": "other",
    "on-screen text": "other",
    "on screen text": "other",
    "title card": "other",
    "insert": "other",
    "super": "other",
    "note": "other",
}


def _frac_ms(frac: Optional[str]) -> int:
    if not frac:
        return 0
    return int(round(Fraction(int(frac), 10 ** len(frac)) * 1000))


def parse_time(value: str) -> Optional[int]:
    """mm:ss.ss, m:ss, hh:mm:ss.ss, with or without decimals -> integer ms (None if bad)."""
    s = value.strip().strip("()").strip()
    m = _HMS.match(s)
    if m:
        h, mi, se, fr = m.groups()
        total = int(h) * 3600 + int(mi) * 60 + int(se)
    else:
        m = _MS.match(s)
        if not m:
            return None
        mi, se, fr = m.groups()
        total = int(mi) * 60 + int(se)
    return total * 1000 + _frac_ms(fr)


def classify_label(label: str) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    """Return (kind, speaker, emotion, ext) for a bold label (without ** and trailing colon)."""
    groups = [g.strip() for g in re.findall(r"\(([^()]*)\)", label)]
    base = re.sub(r"\s*\(.*$", "", label).strip()
    kind = NON_DIALOGUE.get(base.lower())
    if kind is not None:
        return kind, None, None, ("; ".join(groups) or None)
    if not base:
        return "other", None, None, ("; ".join(groups) or None)
    emotion = groups[-1] if groups else None
    ext = "; ".join(groups[:-1]) or None
    return "dialogue", base, emotion, ext


@dataclass
class _Block:
    label: str
    line_no: int
    timing: Optional[tuple[str, str]] = None
    timing_line: int = 0
    text: list[str] = field(default_factory=list)
    text_before_timing: bool = False


def parse_file(path: Path | str) -> Episode:
    path = Path(path)
    warnings: list[ParseWarning] = []
    fm = FILENAME_RE.match(path.name)
    file_ep = int(fm.group(1)) if fm else None
    source_id = fm.group(2) if fm else ""

    raw_lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    has_start = any(START_RE.match(x) for x in raw_lines)

    header: dict[str, str] = {}
    for x in raw_lines:
        if START_RE.match(x) or SCENE_RE.match(x):
            break
        hm = HEADER_RE.match(x)
        if hm:
            header.setdefault(hm.group(1).upper(), hm.group(2).strip())
    header_ep: Optional[int] = None
    if "EPISODE NUMBER" in header:
        d = re.search(r"\d+", header["EPISODE NUMBER"])
        header_ep = int(d.group()) if d else None

    ep = file_ep if file_ep is not None else header_ep

    def warn(code: str, ln: Optional[int], reason: str) -> None:
        warnings.append(ParseWarning(code=code, ep=ep, line_no=ln, reason=reason))

    if file_ep is None:
        warn("BAD_FILENAME", None, "filename is not episode-NNN-Episode <id>.txt")
    if header_ep is None:
        warn("NO_HEADER_EP", None, "header has no episode number")
    elif file_ep is not None and header_ep != file_ep:
        warn("EP_MISMATCH", None, f"filename says {file_ep}, header says {header_ep}")
    if ep is None:
        ep = 0
        warn("NO_EPISODE_NUMBER", None, "no episode number in filename or header; using 0")
    if not has_start:
        warn("NO_SCRIPT_START", None, "no SCRIPT START marker; parsing from first scene/label")

    lines_out: list[Line] = []
    scenes: list[Scene] = []
    seen_scene_numbers: set[int] = set()
    state = {"scene": None, "block": None}

    def implicit_scene() -> Scene:
        sc = Scene(number=0)
        scenes.append(sc)
        state["scene"] = sc
        return sc

    def finish() -> None:
        b: Optional[_Block] = state["block"]
        state["block"] = None
        if b is None:
            return
        if b.timing is None:
            warn("NO_TIMING", b.line_no, "block has no Start/End line; skipped")
            return
        s, e = parse_time(b.timing[0]), parse_time(b.timing[1])
        if s is None or e is None:
            warn("BAD_TIME", b.timing_line, "unparseable time; block skipped")
            return
        texts = [t for t in b.text if t]
        if len(texts) > 1:
            warn("MULTILINE_JOINED", b.line_no, f"{len(texts)} text lines joined")
        if not texts:
            warn("EMPTY_TEXT", b.line_no, "block has no text line")
        if b.text_before_timing:
            warn("TEXT_BEFORE_TIMING", b.line_no, "text appeared before the Start/End line")
        kind, speaker, emotion, ext = classify_label(b.label)
        sc: Optional[Scene] = state["scene"]
        if sc is None:
            warn("NO_SCENE", b.line_no, "block before any SCENE heading; put in scene 0")
            sc = implicit_scene()
        idx = len(lines_out) + 1
        ln = Line(
            id=line_id(ep, idx), ep=ep, idx=idx, scene=sc.number, kind=kind,
            speaker=speaker, emotion=emotion, ext=ext, text=" ".join(texts),
            start_ms=s, end_ms=e, src_line=b.line_no,
        )
        lines_out.append(ln)
        sc.line_ids.append(ln.id)

    in_script = False
    ended = False
    warned_after_end = False
    for ln_no, raw in enumerate(raw_lines, 1):
        s = raw.strip()
        if not in_script:
            if ended:
                if s and not warned_after_end:
                    warn("TEXT_AFTER_END", ln_no, "content after SCRIPT END ignored")
                    warned_after_end = True
                continue
            if START_RE.match(s):
                in_script = True
                continue
            if has_start or not (SCENE_RE.match(s) or LABEL_RE.match(s)):
                continue
            in_script = True  # no START marker: begin at the first structural line
        if END_RE.match(s):
            finish()
            in_script = False
            ended = True
            continue
        if not s:
            continue
        if START_RE.match(s):
            warn("DUP_SCRIPT_START", ln_no, "repeated SCRIPT START ignored")
            continue
        m = SCENE_RE.match(s)
        if m:
            finish()
            num = int(m.group(1))
            if num in seen_scene_numbers:
                warn("DUP_SCENE", ln_no, f"scene number {num} repeated")
            seen_scene_numbers.add(num)
            sc = Scene(number=num)
            scenes.append(sc)
            state["scene"] = sc
            continue
        m = FIELD_RE.match(s)
        if m:
            finish()
            name, val = m.group(1).lower(), m.group(2).strip()
            if name == "actions and dialogue":
                continue
            sc = state["scene"]
            if sc is None:
                warn("FIELD_WITHOUT_SCENE", ln_no, "scene field before any SCENE heading")
                sc = implicit_scene()
            if name == "scene heading":
                sc.heading = val
            else:
                t = parse_time(val)
                if t is None:
                    warn("BAD_SCENE_TIME", ln_no, f"unparseable {name}")
                elif name == "scene start":
                    sc.start_ms = t
                else:
                    sc.end_ms = t
            continue
        m = LABEL_RE.match(s)
        if m:
            finish()
            state["block"] = _Block(label=m.group(1).rstrip(":").strip(), line_no=ln_no)
            continue
        m = TIMING_RE.match(s)
        if m:
            b = state["block"]
            if b is None or b.timing is not None:
                warn("STRAY_TIMING", ln_no, "Start/End line outside a block; ignored")
                continue
            if b.text:
                b.text_before_timing = True
            b.timing = (m.group(1), m.group(2))
            b.timing_line = ln_no
            continue
        b = state["block"]
        if b is None:
            warn("STRAY_TEXT", ln_no, "text line outside a block; ignored")
            continue
        b.text.append(s)
    finish()
    if has_start and not ended:
        warn("NO_SCRIPT_END", None, "no SCRIPT END marker")

    for sc in scenes:
        if sc.start_ms is None or sc.end_ms is None:
            warn("SCENE_TIME_MISSING", None, f"scene {sc.number} lacks a start or end time")

    return Episode(
        ep=ep,
        source_file=path.name,
        source_id=source_id,
        header_ep=header_ep,
        logline=header.get("EPISODE LOGLINE", ""),
        continuity=header.get("CONTINUITY NOTES", ""),
        scenes=scenes,
        lines=lines_out,
        duration_ms=max((x.end_ms for x in lines_out), default=0),
        warnings=warnings,
    )


def find_episode_files(data_dir: Path | str) -> list[Path]:
    return sorted(Path(data_dir).rglob("episode-*.txt"), key=lambda p: (p.name.lower(), str(p)))


def parse_dir(data_dir: Path | str) -> tuple[list[Episode], list[ParseWarning]]:
    """Parse every episode file under data_dir (recursive). Returns (episodes, file-level warnings)."""
    episodes: list[Episode] = []
    warnings: list[ParseWarning] = []
    seen: set[int] = set()
    for f in find_episode_files(data_dir):
        try:
            e = parse_file(f)
        except Exception as ex:  # one bad file must not stop the run
            warnings.append(ParseWarning(code="FILE_ERROR", reason=f"{f.name}: {type(ex).__name__}"))
            continue
        if e.ep in seen:
            warnings.append(ParseWarning(code="DUP_EPISODE", ep=e.ep, reason=f"{f.name}: episode number already parsed; skipped"))
            continue
        seen.add(e.ep)
        episodes.append(e)
    episodes.sort(key=lambda e: e.ep)
    return episodes, warnings
