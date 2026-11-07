"""Set temporal IoU between two promos (eval/match_rule.md section 2).

tIoU(p, g) = sum_e |P_e & G_e| / sum_e |P_e | G_e|, per episode, exact integer milliseconds.
Reused by check-gold (P01b) and the P08 scorer.
"""

from __future__ import annotations

from typing import Iterable

Seg = tuple[int, int, int]  # (ep, start_ms, end_ms)


def _merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(intervals):
        if e <= s:
            continue
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def _by_episode(segs: Iterable[Seg]) -> dict[int, list[tuple[int, int]]]:
    by: dict[int, list[tuple[int, int]]] = {}
    for ep, s, e in segs:
        by.setdefault(int(ep), []).append((int(s), int(e)))
    return {ep: _merge(v) for ep, v in by.items()}


def _length(iv: list[tuple[int, int]]) -> int:
    return sum(e - s for s, e in iv)


def _intersection(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> int:
    i = j = total = 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if hi > lo:
            total += hi - lo
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return total


def set_tiou(segs_a: Iterable[Seg], segs_b: Iterable[Seg]) -> float:
    a, b = _by_episode(segs_a), _by_episode(segs_b)
    inter = union = 0
    for ep in set(a) | set(b):
        ia, ib = a.get(ep, []), b.get(ep, [])
        x = _intersection(ia, ib)
        inter += x
        union += _length(ia) + _length(ib) - x
    return inter / union if union else 0.0
