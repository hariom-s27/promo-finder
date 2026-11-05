"""Timing sanity checks. Warnings and counts only; never stops the run."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from .models import KINDS, Episode, ParseWarning

GAP_MS = 2000


class ValidationReport(BaseModel):
    start_ge_end: list[str] = Field(default_factory=list)  # line IDs
    backwards_starts: int = 0
    overlaps_by_pair: dict[str, int] = Field(default_factory=dict)
    gaps_over_2s: int = 0
    out_of_scene: list[str] = Field(default_factory=list)  # line IDs

    def counts(self) -> dict:
        return {
            "start_ge_end": len(self.start_ge_end),
            "backwards_starts": self.backwards_starts,
            "overlaps_total": sum(self.overlaps_by_pair.values()),
            "overlaps_by_pair": dict(sorted(self.overlaps_by_pair.items())),
            "gaps_over_2s": self.gaps_over_2s,
            "out_of_scene": len(self.out_of_scene),
        }


def validate_episode(ep: Episode) -> tuple[ValidationReport, list[ParseWarning]]:
    rep = ValidationReport()
    warns: list[ParseWarning] = []
    lines = ep.lines

    # 1. start >= end
    for ln in lines:
        if ln.start_ms >= ln.end_ms:
            rep.start_ge_end.append(ln.id)
            warns.append(ParseWarning(code="START_GE_END", ep=ep.ep, line_no=ln.src_line, reason=ln.id))

    # 2. start times going backwards in file order
    for prev, cur in zip(lines, lines[1:]):
        if cur.start_ms < prev.start_ms:
            rep.backwards_starts += 1

    good = sorted((x for x in lines if x.start_ms < x.end_ms), key=lambda x: (x.start_ms, x.end_ms, x.idx))

    # 3. overlaps, counted per kind pair (sweep over time-sorted lines)
    pairs: Counter[str] = Counter()
    active: list = []
    for ln in good:
        active = [a for a in active if a.end_ms > ln.start_ms]
        for a in active:
            pairs["+".join(sorted((a.kind, ln.kind)))] += 1
        active.append(ln)
    rep.overlaps_by_pair = dict(pairs)

    # 4. gaps > 2 s: time not covered by any earlier line (time order, running max end)
    max_end = None
    for ln in good:
        if max_end is not None and ln.start_ms - max_end > GAP_MS:
            rep.gaps_over_2s += 1
        max_end = ln.end_ms if max_end is None else max(max_end, ln.end_ms)

    # 5. lines outside their scene's bounds
    scenes = {}
    for sc in ep.scenes:
        scenes.setdefault(sc.number, sc)
    for ln in lines:
        sc = scenes.get(ln.scene)
        if sc is None or sc.start_ms is None or sc.end_ms is None:
            continue
        if ln.start_ms < sc.start_ms or ln.end_ms > sc.end_ms:
            rep.out_of_scene.append(ln.id)
            warns.append(ParseWarning(code="OUT_OF_SCENE", ep=ep.ep, line_no=ln.src_line, reason=ln.id))
    return rep, warns


def build_parse_report(episodes: list[Episode], file_warnings: list[ParseWarning]) -> dict:
    """Run the validator on every episode (appending its warnings to ep.warnings) and
    return a numbers-only report. Never includes names or script text."""
    per_ep: dict[str, dict] = {}
    t_kinds: Counter[str] = Counter({k: 0 for k in KINDS})
    t_warn: Counter[str] = Counter()
    t_val: Counter[str] = Counter()
    t_pairs: Counter[str] = Counter()
    all_speakers: set[str] = set()
    t_scenes = t_lines = t_dur = 0
    for e in episodes:
        rep, vwarns = validate_episode(e)
        e.warnings.extend(vwarns)
        kinds = Counter({k: 0 for k in KINDS})
        kinds.update(x.kind for x in e.lines)
        speakers = {x.speaker.strip().upper() for x in e.lines if x.speaker}
        all_speakers |= speakers
        wcodes = Counter(w.code for w in e.warnings)
        vc = rep.counts()
        per_ep[f"E{e.ep:02d}"] = {
            "ep": e.ep,
            "source_id": e.source_id,
            "lines": len(e.lines),
            "lines_by_kind": dict(kinds),
            "scenes": len(e.scenes),
            "duration_ms": e.duration_ms,
            "distinct_speakers": len(speakers),
            "warnings_by_code": dict(sorted(wcodes.items())),
            "validator": vc,
        }
        t_kinds.update(kinds)
        t_warn.update(wcodes)
        for k, v in vc.items():
            if k != "overlaps_by_pair":
                t_val[k] += v
        t_pairs.update(vc["overlaps_by_pair"])
        t_scenes += len(e.scenes)
        t_lines += len(e.lines)
        t_dur += e.duration_ms
    totals = {
        "episodes": len(episodes),
        "scenes": t_scenes,
        "lines": t_lines,
        "lines_by_kind": dict(t_kinds),
        "total_duration_ms": t_dur,
        "distinct_speakers": len(all_speakers),
        "warnings_by_code": dict(sorted(t_warn.items())),
        "file_warnings_by_code": dict(sorted(Counter(w.code for w in file_warnings).items())),
        "validator": {**dict(t_val), "overlaps_by_pair": dict(sorted(t_pairs.items()))},
    }
    return {"totals": totals, "episodes": per_ep}
