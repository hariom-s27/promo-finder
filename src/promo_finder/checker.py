"""Timestamp checker: the safety core.

The LLM only ever names line IDs. This module turns (first_id, last_id) spans into
segments whose times come exclusively from parsed lines, and enforces every promo rule.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

from .config import PromoCfg
from .models import CheckResult, Episode, Line, Segment

ERROR_CODES = (
    "UNKNOWN_ID",
    "CROSS_EP_SPAN",
    "REVERSED_SPAN",
    "BAD_SEGMENT_TIME",
    "TOO_SHORT",
    "TOO_LONG",
    "TOO_MANY_SEGMENTS",
    "OUT_OF_ORDER",
    "OVERLAP",
)


class LineIndex(dict):
    """dict[line_id, Line] that also keeps each episode's lines in file order."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._by_ep: Optional[dict[int, list[Line]]] = None

    def __setitem__(self, key, value):
        self._by_ep = None
        super().__setitem__(key, value)

    def episode_lines(self, ep: int) -> list[Line]:
        if self._by_ep is None:
            by: dict[int, list[Line]] = {}
            for ln in self.values():
                by.setdefault(ln.ep, []).append(ln)
            for v in by.values():
                v.sort(key=lambda x: x.idx)
            self._by_ep = by
        return self._by_ep.get(ep, [])


def build_index(episodes: Iterable[Episode]) -> LineIndex:
    idx = LineIndex()
    for e in episodes:
        for ln in e.lines:
            if ln.id in idx:
                raise ValueError(f"duplicate line id {ln.id}")
            idx[ln.id] = ln
    return idx


def _episode_lines(index: Mapping[str, Line], ep: int) -> list[Line]:
    if isinstance(index, LineIndex):
        return index.episode_lines(ep)
    return sorted((x for x in index.values() if x.ep == ep), key=lambda x: x.idx)


def _promo_cfg(cfg) -> PromoCfg:
    if cfg is None:
        return PromoCfg()
    return getattr(cfg, "promo", cfg)


def check_promo(spans: list[tuple[str, str]], index: Mapping[str, Line], cfg=None) -> CheckResult:
    pc = _promo_cfg(cfg)
    errors: list[str] = []

    def err(code: str) -> None:
        if code not in errors:
            errors.append(code)

    segments: list[Segment] = []
    for first_id, last_id in spans:
        a, b = index.get(first_id), index.get(last_id)
        if a is None or b is None:
            err("UNKNOWN_ID")
            continue
        if a.ep != b.ep:
            err("CROSS_EP_SPAN")
            continue
        if b.idx < a.idx:
            err("REVERSED_SPAN")
            continue
        covered = [x for x in _episode_lines(index, a.ep) if a.idx <= x.idx <= b.idx]
        # Times come only from parsed lines: start of the first line, end of the last line.
        seg = Segment(ep=a.ep, start_ms=a.start_ms, end_ms=b.end_ms, line_ids=[x.id for x in covered])
        if seg.end_ms <= seg.start_ms:
            err("BAD_SEGMENT_TIME")
            continue
        segments.append(seg)

    span_errors = bool(errors)

    if len(spans) > pc.max_segments:
        err("TOO_MANY_SEGMENTS")

    seen: set[str] = set()
    for s in segments:
        ids = set(s.line_ids)
        if seen & ids:
            err("OVERLAP")
        seen |= ids

    for p, q in zip(segments, segments[1:]):
        if (q.ep, q.start_ms) < (p.ep, p.start_ms):
            err("OUT_OF_ORDER")

    total = sum(s.end_ms - s.start_ms for s in segments)
    if not span_errors:  # a partial total after a bad span would only add noise
        if total < pc.min_ms:
            err("TOO_SHORT")
        if total > pc.max_ms:
            err("TOO_LONG")

    return CheckResult(ok=not errors, segments=segments, total_ms=total, errors=errors)


def snap_to_lines(ep: int, start_ms: int, end_ms: int, index: Mapping[str, Line]) -> tuple[tuple[str, str], int, int]:
    """Snap free timestamps to enclosing line boundaries.

    Returns ((first_id, last_id), start_moved_ms, end_moved_ms). Moves are signed:
    start_moved <= 0 means the start moved earlier; end_moved >= 0 means the end moved later.
    """
    lines = [x for x in _episode_lines(index, ep) if x.end_ms > x.start_ms]
    if not lines:
        raise ValueError(f"no usable lines for episode {ep}")
    if end_ms < start_ms:
        start_ms, end_ms = end_ms, start_ms

    cands = [x for x in lines if x.start_ms <= start_ms]
    first = (max(cands, key=lambda x: (x.start_ms, -x.idx)) if cands
             else min(lines, key=lambda x: (x.start_ms, x.idx)))
    cands = [x for x in lines if x.end_ms >= end_ms and x.idx >= first.idx]
    if cands:
        last = min(cands, key=lambda x: (x.end_ms, -x.idx))
    else:
        later = [x for x in lines if x.idx >= first.idx]
        last = max(later, key=lambda x: (x.end_ms, x.idx))
    return (first.id, last.id), first.start_ms - start_ms, last.end_ms - end_ms
