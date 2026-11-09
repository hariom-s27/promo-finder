"""P08b diagnostic: where are gold promos lost between the saved moments and the ranked list?

Replays the builder's hook x cliff loop (same helper functions, same rule order) with per-pair
attribution, so every drop can be traced to the rule that removed it. Pure functions: no I/O, no
network, no LLM. The replay must reproduce the saved builder output exactly (see `same_as_builder`);
the tool refuses to report otherwise.

Held-out episodes only. The fresh set (31-34) is sealed: `refuse_fresh` stops any request for it.
Everything returned is counts, gold IDs, line IDs and episode numbers; never script text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

from . import builder as B
from .checker import build_index, check_promo
from .config import Config
from .labelling import SEALED
from .policy import PolicyScanner
from .tiou import Seg, set_tiou

TAU = 0.5
RULES = B.RULES  # ("checker", "J2", "J4", "speakers", "resolution", "reveal", "late_series", "dedupe", "cap")
# order in which the builder removes a pair; checker first, then the per-promo rules, then the pool rules
ORDER = ("checker", "J2", "J4", "speakers", "resolution", "late_series", "reveal", "dedupe", "cap")
TABLE_ROWS = ("checker:TOO_SHORT", "checker:MONTAGE_CONSTRUCTION", "checker:other", "J2", "J4", "speakers",
              "resolution", "late_series", "reveal", "dedupe", "cap")


class SealedEpisode(Exception):
    """A request for a sealed fresh episode (blocks A and B; counts only until the score-once gate)."""


class DiagnosticMismatch(Exception):
    """The replay does not reproduce the saved builder output; nothing may be reported."""


def refuse_fresh(episodes: Iterable[int]) -> None:
    bad = sorted(set(int(e) for e in episodes) & set(SEALED))
    if bad:
        raise SealedEpisode("fresh episodes are sealed until the score-once gate")


# ── traced replay ───────────────────────────────────────────────────────


@dataclass
class Pair:
    ep: int
    hook: str
    cliff: str
    raw: tuple[Seg, ...]                  # hook start -> cliff end, one segment, whatever its length
    raw_status: str                       # ok | TOO_SHORT | TOO_LONG | other
    built: Optional[tuple[Seg, ...]]      # spans after montage/extension/reactions, when construction worked
    violations: frozenset                 # every rule that would remove it, independent of order
    first_drop: str = "kept"              # the builder's first removing rule (a RULES label) or "kept"
    drop_detail: str = ""                 # e.g. checker:TOO_SHORT
    extended: bool = False
    j4_flagged: bool = False
    resolution_flagged: bool = False
    resolution_positions: tuple = ()   # blocking resolution lines inside the span and where they sit
    promo: Optional[dict] = None

    @property
    def span(self) -> tuple[Seg, ...]:
        """The span the builder assesses: the constructed one when it exists, else the raw pair."""
        return self.built if self.built is not None else self.raw


@dataclass
class EpisodeTrace:
    ep: int
    generated: int = 0
    pairs: list[Pair] = field(default_factory=list)
    dropped: dict = field(default_factory=lambda: {rule: 0 for rule in RULES})
    candidates: list[dict] = field(default_factory=list)  # kept promos, builder format, ids assigned
    pool_size: int = 0                    # survivors before dedupe/cap
    extended_kept: int = 0
    j4_flagged_generated: int = 0


def _seg_tuples(segments) -> tuple[Seg, ...]:
    return tuple((s.ep, s.start_ms, s.end_ms) for s in segments)


def _label(prefix_errors: Sequence[str]) -> str:
    return "checker:" + "+".join(prefix_errors)


def _row_of(label: str) -> str:
    """Map a violation/drop label to a TABLE_ROWS row."""
    if label.startswith("checker:"):
        return label if label in ("checker:TOO_SHORT", "checker:MONTAGE_CONSTRUCTION") else "checker:other"
    return label


extend_end = B.extend_end                      # F2: the builder's implementation, shared


def trace_episode(episode, moment_data: dict, reveal_data: dict, intensity: list, policy: list, cfg: Config,
                  previous=None, *, j4_mode: str = "drop", j4_penalty: float = 0.25,
                  too_short_mode: str = "drop", resolution_mode: str = "drop",
                  resolution_penalty: float = 0.5, resolution_window_ms: int = 3000,
                  resolution_window_rule: str = "overlap") -> EpisodeTrace:
    """Mirror of builder.build_episode with attribution. With the default options it must reproduce the
    builder exactly; `flag` / `extend` are what-if prototypes of the F1 / F2 fixes, and
    resolution_mode="flag" is a what-if for a resolution flag-and-penalty change (proposal only), and
    "flag_unless_end" (F5b) drops a candidate only when a blocking resolution line sits at its end: it is the
    final line, or (rule "overlap") ends inside the last `resolution_window_ms`, or (rule "start") starts inside it."""
    if (j4_mode not in ("drop", "flag") or too_short_mode not in ("drop", "extend")
            or resolution_mode not in ("drop", "flag", "flag_unless_end")
            or resolution_window_rule not in ("overlap", "start") or resolution_window_ms < 0):
        raise ValueError("unknown variant option")
    B.validate_artifacts(episode, moment_data, reveal_data, intensity, policy)
    index = build_index([episode])
    recap_ids, _ = B.recap_lines(episode, previous, cfg)
    scanner = PolicyScanner()
    scanner.flags = policy
    smooth = {row["line_id"]: row["smooth"] for row in intensity}
    reveal_ids = {mark["line_id"] for mark in reveal_data["marks"] if mark["type"] == "reveal"}
    resolutions = {confidence: {m["line_id"] for m in reveal_data["marks"]
                                if m["type"] == "resolution" and m["confidence"] == confidence}
                   for confidence in ("low", "medium", "high")}
    resolution_ids = set().union(*(resolutions[c] for c in cfg.spoiler.resolution_block_confidence))
    confidence_of = B.resolution_confidence(reveal_data, resolution_ids)
    cliff_ids = {c["line_id"] for c in moment_data["cliff_ends"]}
    limits = B._limits(cfg)
    hard = cfg.builder.max_speakers + 1 if cfg.builder.max_speakers is not None else cfg.builder.speakers_hard
    trace = EpisodeTrace(ep=episode.ep)
    survivors: list[tuple[Pair, dict]] = []

    for hook in moment_data["hook_starts"]:
        for cliff in moment_data["cliff_ends"]:
            h, c = hook["line_id"], cliff["line_id"]
            if index[h].idx >= index[c].idx:
                continue
            trace.generated += 1
            raw = ((episode.ep, index[h].start_ms, index[c].end_ms),)
            spans = [(h, c)]
            checked = check_promo(spans, index, limits)
            raw_status = ("ok" if checked.ok else "TOO_SHORT" if checked.errors == ["TOO_SHORT"]
                          else "TOO_LONG" if checked.errors == ["TOO_LONG"] else "other")
            violations: set[str] = set()
            failed = None
            extended = False
            reaction_cut = False
            if checked.errors == ["TOO_LONG"]:
                montage = B.montage_spans(episode, h, c, index, cfg)
                if montage is None:
                    failed = "checker:MONTAGE_CONSTRUCTION"
                else:
                    spans = montage
            elif not checked.ok:
                grown = None
                if too_short_mode == "extend" and checked.errors == ["TOO_SHORT"]:
                    grown = extend_end(episode, index, h, c, cfg, resolution_ids, cliff_ids)
                if grown is None:
                    failed = _label(checked.errors)
                else:
                    spans, extended = [grown], True
            if failed is None:
                spans, reaction_cut, _reactions = B.include_reactions(episode, spans, index, cfg)
                checked = check_promo(spans, index, limits)
                if not checked.ok:
                    failed = _label(checked.errors)
            built = _seg_tuples(checked.segments) if failed is None else None
            if failed:
                violations.add(failed)
            # independent evaluation of every other rule on the best available span
            if checked.segments:
                ids = [key for seg in checked.segments for key in seg.line_ids]
                if B.answers_question(episode, spans, index):
                    violations.add("J2")
                speakers = [B._speakers(seg, index) for seg in checked.segments]
                j4 = len(speakers) == 2 and not speakers[0] & speakers[1]
                if j4 and j4_mode == "drop":
                    violations.add("J4")
                speaker_count = len(set().union(*speakers))
                if speaker_count >= hard:
                    violations.add("speakers")
                positions = resolution_positions(checked.segments, index, confidence_of, resolution_window_ms,
                                                 resolution_window_rule)
                at_end = any(p["at_end"] for p in positions)
                if positions and (resolution_mode == "drop" or (resolution_mode == "flag_unless_end" and at_end)):
                    violations.add("resolution")
                if episode.ep >= cfg.spoiler.late_series_start:
                    violations.add("late_series")
                if cfg.spoiler.reveal_mode == "block" and set(ids) & reveal_ids:
                    violations.add("reveal")
            else:
                j4, positions = False, []
            res_flag = bool(positions and "resolution" not in violations and resolution_mode != "drop")
            pair = Pair(ep=episode.ep, hook=h, cliff=c, raw=raw, raw_status=raw_status, built=built,
                        violations=frozenset(violations), extended=extended, j4_flagged=j4 and j4_mode == "flag",
                        resolution_flagged=res_flag, resolution_positions=tuple(positions))
            trace.pairs.append(pair)
            trace.j4_flagged_generated += pair.j4_flagged
            order = [label for rule in ORDER for label in sorted(violations)
                     if (label == rule or label.startswith(rule + ":"))]
            if order:
                pair.first_drop = order[0].split(":")[0]
                pair.drop_detail = order[0]
                trace.dropped[pair.first_drop] += 1
                continue
            # survivor: exactly the builder's promo dict
            flags = {"possible_recap": ids[0] in recap_ids, "reaction_cut": reaction_cut,
                     "contains_reveal": bool(set(ids) & reveal_ids),
                     "contains_low_conf_resolution": bool(set(ids) & resolutions["low"]),
                     "speakers_4": speaker_count == cfg.builder.speakers_soft}
            if pair.j4_flagged:
                flags["no_shared_speaker"] = True
            if extended:
                flags["extended"] = True
            if pair.resolution_flagged:
                flags["contains_blocking_resolution"] = True
            montage_flag = len(spans) == 2
            score = int(hook["strength"]) + int(cliff["strength"]) + sum(smooth[key] for key in ids) / len(ids)
            score -= sum(getattr(cfg.builder.penalties, flag) for flag in ("possible_recap", "reaction_cut", "speakers_4") if flags[flag])
            score -= cfg.builder.penalties.montage if montage_flag else 0
            if pair.j4_flagged:
                score -= j4_penalty
            if pair.resolution_flagged:
                score -= resolution_penalty
            promo = {"episode": episode.ep, "segments": [
                {"episode": seg.ep, "start_ms": seg.start_ms, "end_ms": seg.end_ms,
                 "first_line_id": seg.line_ids[0], "last_line_id": seg.line_ids[-1]} for seg in checked.segments],
                "line_ids": ids, "duration_s": checked.total_ms / 1000,
                "hook": {"line_id": h, "type": hook["hook_type"], "strength": hook["strength"]},
                "cliff": {"line_id": c, "type": cliff["cliff_type"], "strength": cliff["strength"], "source": cliff["source"]},
                "pre_score": score, "flags": flags, "policy": scanner.promo_flags(ids), "montage": montage_flag,
                "provenance": {"moments": B._provenance(moment_data), "reveals": B._provenance(reveal_data)},
                "_hook_order": index[h].idx, "_cliff_order": index[c].idx}
            pair.promo = promo
            survivors.append((pair, promo))

    pool = [promo for _pair, promo in survivors]
    trace.pool_size = len(pool)
    kept = []
    status: dict[int, str] = {}
    for promo in sorted(pool, key=B._sort_key):
        times = [(s["episode"], s["start_ms"], s["end_ms"]) for s in promo["segments"]]
        if any(set_tiou(times, [(s["episode"], s["start_ms"], s["end_ms"]) for s in old["segments"]]) > cfg.builder.dedupe_tiou
               for old in kept):
            status[id(promo)] = "dedupe"
        else:
            kept.append(promo)
    for promo in kept[cfg.builder.max_per_episode:]:
        status[id(promo)] = "cap"
    kept = kept[:cfg.builder.max_per_episode]
    reference, _ = B.dedupe_cap(pool, cfg)
    if reference != kept:
        raise DiagnosticMismatch("dedupe/cap replay differs from the builder")
    for pair, promo in survivors:
        pair.first_drop = status.get(id(promo), "kept")
        pair.drop_detail = pair.first_drop
        if pair.first_drop != "kept":
            trace.dropped[pair.first_drop] += 1
    for number, promo in enumerate(kept, 1):
        trace.candidates.append({"promo_id": f"P05-E{episode.ep:02d}-{number:03d}",
                                 **{k: v for k, v in promo.items() if not k.startswith("_")}})
        trace.extended_kept += bool(promo["flags"].get("extended"))
    if trace.generated != sum(trace.dropped.values()) + len(trace.candidates):
        raise DiagnosticMismatch("replay accounting invariant failed")
    return trace


def same_as_builder(trace: EpisodeTrace, saved_candidates: Sequence[Mapping], saved_summary: Mapping) -> list[str]:
    """Compare a v1-option replay with the saved builder output; returns the list of differences."""
    problems = []
    if list(trace.candidates) != list(saved_candidates):
        problems.append(f"E{trace.ep:02d}: candidates differ")
    if trace.generated != saved_summary["generated"]:
        problems.append(f"E{trace.ep:02d}: generated {trace.generated} != {saved_summary['generated']}")
    if trace.dropped != saved_summary["dropped"]:
        problems.append(f"E{trace.ep:02d}: dropped counts differ")
    if len(trace.candidates) != saved_summary["kept"]:
        problems.append(f"E{trace.ep:02d}: kept count differs")
    return problems


# ── matching against gold ───────────────────────────────────────────────


def matching_gold(span: Sequence[Seg], golds: Sequence, tau: float = TAU) -> list[str]:
    """Gold IDs with tIoU >= tau against `span` (not one-to-one; coverage, not scoring)."""
    return sorted(g.gold_id for g in golds if set_tiou(span, g.segments) >= tau)


def promo_segs(promo: Mapping) -> tuple[Seg, ...]:
    return tuple((int(s["episode"]), int(s["start_ms"]), int(s["end_ms"])) for s in promo["segments"])


def pool_matched(candidates_by_ep: Mapping[int, Sequence[Mapping]], golds: Sequence, tau: float = TAU) -> dict[str, list[str]]:
    """gold_id -> promo_ids of kept candidates with tIoU >= tau."""
    out = {g.gold_id: [] for g in golds}
    for cands in candidates_by_ep.values():
        for p in cands:
            segs = promo_segs(p)
            for gid in matching_gold(segs, golds, tau):
                out[gid].append(p["promo_id"])
    return out


def prefilter_recall(traces: Mapping[int, EpisodeTrace], golds: Sequence) -> dict:
    """(b) gold matched by ANY generated pair before the drop rules, raw span and constructed span."""
    raw, span = set(), set()
    for trace in traces.values():
        for pair in trace.pairs:
            raw.update(matching_gold(pair.raw, golds))
            span.update(matching_gold(pair.span, golds))
    ids = sorted(g.gold_id for g in golds)
    return {"n_gold": len(ids),
            "raw_pair": {"k": len(raw), "matched": sorted(raw), "unmatched": [i for i in ids if i not in raw]},
            "constructed_pair": {"k": len(span), "matched": sorted(span), "unmatched": [i for i in ids if i not in span]}}


def _categories(pair: Pair) -> set[str]:
    return {_row_of(v) for v in pair.violations}


def rule_table(traces: Mapping[int, EpisodeTrace], golds: Sequence, pool_gold: Mapping[str, Sequence[str]]) -> dict:
    """(c) per drop rule, among gold-matching pairs: first-drop counts and sole-blocker counts."""
    table = {row: {"first_drop_pairs": 0, "first_drop_gold": set(), "sole_blocker_pairs": 0,
                   "sole_blocker_gold": set(), "rescuable_gold": set(), "all_pairs_dropped": 0} for row in TABLE_ROWS}
    kept_pairs = kept_matching = 0
    per_gold = {g.gold_id: {"matching_pairs": 0, "kept_pairs": 0, "first_drop": {}, "sole_blocker": {}} for g in golds}
    matching_pairs = 0
    for trace in traces.values():
        for pair in trace.pairs:
            hit = matching_gold(pair.span, golds)
            if pair.first_drop == "kept":
                kept_pairs += 1
                kept_matching += bool(hit)
            else:
                table[_row_of(pair.drop_detail or pair.first_drop)]["all_pairs_dropped"] += 1
            if not hit:
                continue
            matching_pairs += 1
            first = "kept" if pair.first_drop == "kept" else _row_of(pair.drop_detail or pair.first_drop)
            cats = _categories(pair)
            sole = next(iter(cats)) if len(cats) == 1 else (first if (not cats and first in ("dedupe", "cap")) else None)
            for gid in hit:
                row = per_gold[gid]
                row["matching_pairs"] += 1
                if first == "kept":
                    row["kept_pairs"] += 1
                else:
                    row["first_drop"][first] = row["first_drop"].get(first, 0) + 1
                if sole in table:
                    row["sole_blocker"][sole] = row["sole_blocker"].get(sole, 0) + 1
            if first in table:
                table[first]["first_drop_pairs"] += 1
                table[first]["first_drop_gold"].update(hit)
            if sole in table:
                table[sole]["sole_blocker_pairs"] += 1
                table[sole]["sole_blocker_gold"].update(hit)
                table[sole]["rescuable_gold"].update(g for g in hit if not pool_gold.get(g))
    out = {}
    for row, v in table.items():
        out[row] = {"all_pairs_dropped": v["all_pairs_dropped"], "first_drop_pairs": v["first_drop_pairs"],
                    "first_drop_gold": sorted(v["first_drop_gold"]),
                    "sole_blocker_pairs": v["sole_blocker_pairs"], "sole_blocker_gold": sorted(v["sole_blocker_gold"]),
                    "rescuable_gold": sorted(v["rescuable_gold"])}
    return {"gold_matching_pairs": matching_pairs, "kept_pairs": kept_pairs, "kept_gold_matching_pairs": kept_matching,
            "rules": out,
            "per_gold": {gid: per_gold[gid] for gid in sorted(per_gold)}}


def pair_construction_counts(traces: Mapping[int, EpisodeTrace], golds: Sequence) -> dict:
    """How the raw hook-to-cliff spans sort by length, overall and among gold-matching pairs."""
    total = {"ok": 0, "TOO_SHORT": 0, "TOO_LONG": 0, "other": 0}
    matching = dict.fromkeys(total, 0)
    for trace in traces.values():
        for pair in trace.pairs:
            total[pair.raw_status] += 1
            matching[pair.raw_status] += bool(matching_gold(pair.span, golds))
    return {"pairs": total, "gold_matching_pairs": matching}


def episode_rank(candidates: Sequence[Mapping], promo_id: str) -> int:
    """1-based position of a promo in its episode's judge-selection order (pre_score desc, id asc)."""
    order = [p["promo_id"] for p in sorted(candidates, key=lambda p: (-p["pre_score"], p["promo_id"]))]
    return order.index(promo_id) + 1


def variant_coverage(candidates_by_ep: Mapping[int, Sequence[Mapping]], golds: Sequence, judged_top: int = 4,
                     alt_top: int = 6, negatives: Sequence = ()) -> dict:
    """(f) pool recall of a candidate set and whether each matched gold sits in a judged slot.
    `negatives` (gold grade 0) are checked the same way: which ones any kept / judged candidate reaches."""
    matched = pool_matched(candidates_by_ep, golds)
    by_id = {p["promo_id"]: (ep, p) for ep, cands in candidates_by_ep.items() for p in cands}
    per_gold = {}
    for g in sorted(golds, key=lambda g: g.gold_id):
        ranks = sorted(episode_rank(candidates_by_ep[by_id[pid][0]], pid) for pid in matched[g.gold_id])
        per_gold[g.gold_id] = {"matching_candidates": len(matched[g.gold_id]), "best_episode_rank": ranks[0] if ranks else None,
                               f"judged_top{judged_top}": bool(ranks) and ranks[0] <= judged_top,
                               f"judged_top{alt_top}": bool(ranks) and ranks[0] <= alt_top}
    hit = sorted(gid for gid, v in per_gold.items() if v["matching_candidates"])
    counts = [len(c) for c in candidates_by_ep.values()]
    neg_pool = pool_matched(candidates_by_ep, negatives) if negatives else {}
    neg_hit = sorted(n for n, ids in neg_pool.items() if ids)
    neg_judged = sorted(n for n, ids in neg_pool.items()
                        if any(episode_rank(candidates_by_ep[by_id[pid][0]], pid) <= judged_top for pid in ids))
    return {"n_gold": len(per_gold), "n_negatives": len(neg_pool),
            "negative_pool_hits": neg_hit, f"negative_judged_top{judged_top}_hits": neg_judged,
            "pool_recall": {"k": len(hit), "matched": hit,
                                                      "unmatched": sorted(set(per_gold) - set(hit))},
            f"matched_and_judged_top{judged_top}": sorted(g for g, v in per_gold.items() if v[f"judged_top{judged_top}"]),
            f"matched_and_judged_top{alt_top}": sorted(g for g, v in per_gold.items() if v[f"judged_top{alt_top}"]),
            "per_gold": per_gold,
            "candidates": {"total": sum(counts), "episodes": len(counts), "empty_episodes": sorted(
                ep for ep, c in candidates_by_ep.items() if not c)}}


def best_kept_rank(L: Sequence, golds: Sequence, judged_ids: set[str], top_k: int) -> list[dict]:
    """(d) per gold: its best-matching kept candidate in the frozen list L, where it sits and if it was judged."""
    out = []
    for g in sorted(golds, key=lambda g: g.gold_id):
        best, first_ok = None, None
        for p in L:
            t = set_tiou(p.segments, g.segments)
            if t > 0 and (best is None or t > best[0]):
                best = (t, p)
            if t >= TAU and first_ok is None:
                first_ok = p
        out.append({"gold_id": g.gold_id, "best_tiou": round(best[0], 4) if best else 0.0,
                    "best_pos": best[1].pos if best else None, "best_promo_id": best[1].promo_id if best else None,
                    "best_judged": best[1].promo_id in judged_ids if best else None,
                    "first_match_pos": first_ok.pos if first_ok else None,
                    "matched_within_K": bool(first_ok and first_ok.pos <= top_k)})
    return out


def top_episode_concentration(L: Sequence, top: int = 10) -> dict:
    """(e) episodes of the first `top` promos of L (episode of the first segment)."""
    counts: dict[int, int] = {}
    for p in L[:top]:
        ep = p.segments[0][0]
        counts[ep] = counts.get(ep, 0) + 1
    ordered = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return {"top": top, "per_episode": ordered, "distinct_episodes": len(ordered),
            "max_in_one_episode": max(counts.values()) if counts else 0,
            "top2_episodes_share": (sum(list(ordered.values())[:2]) / top) if counts else None}


def moment_coverage(moments_by_ep: Mapping[int, Mapping], index, golds: Sequence, tol_ms: int = 2000) -> dict:
    """Did the saved moments name the gold's boundaries at all? Hook = a hook line starting within tol of the
    gold's first-segment start; cliff = a cliff line ending within tol of the gold's last-segment end."""
    per_gold = {}
    for g in sorted(golds, key=lambda g: g.gold_id):
        (first_ep, first_start, _), (last_ep, _, last_end) = g.segments[0], g.segments[-1]
        hooks = moments_by_ep[first_ep]["hook_starts"]
        cliffs = moments_by_ep[last_ep]["cliff_ends"]
        per_gold[g.gold_id] = {
            "hook_found": any(abs(index[h["line_id"]].start_ms - first_start) <= tol_ms for h in hooks),
            "cliff_found": any(abs(index[c["line_id"]].end_ms - last_end) <= tol_ms for c in cliffs)}
    both = sorted(g for g, v in per_gold.items() if v["hook_found"] and v["cliff_found"])
    return {"tolerance_ms": tol_ms, "per_gold": per_gold,
            "hook_found": sorted(g for g, v in per_gold.items() if v["hook_found"]),
            "cliff_found": sorted(g for g, v in per_gold.items() if v["cliff_found"]),
            "both_found": both}


def max_pair_tiou(traces: Mapping[int, EpisodeTrace], golds: Sequence) -> dict:
    """Best tIoU any generated pair reaches with each gold: raw span and constructed span."""
    out = {g.gold_id: {"raw": 0.0, "constructed": 0.0} for g in golds}
    for trace in traces.values():
        for pair in trace.pairs:
            for g in golds:
                out[g.gold_id]["raw"] = max(out[g.gold_id]["raw"], set_tiou(pair.raw, g.segments))
                out[g.gold_id]["constructed"] = max(out[g.gold_id]["constructed"], set_tiou(pair.span, g.segments))
    return {gid: {k: round(v, 4) for k, v in row.items()} for gid, row in sorted(out.items())}


def diversity_cap(items: Sequence, episode_of, top: int = 10, per_episode: int = 2) -> list:
    """F3 prototype. Fill the first `top` places in order, skipping any item whose episode already has
    `per_episode` places; skipped items keep their relative order after the top. If too few eligible items
    remain the gaps are filled by order. Everything after the top keeps its original order."""
    chosen, deferred, counts = [], [], {}
    for item in items:
        if len(chosen) >= top:
            break
        ep = episode_of(item)
        if counts.get(ep, 0) >= per_episode:
            deferred.append(item)
            continue
        chosen.append(item)
        counts[ep] = counts.get(ep, 0) + 1
    for item in deferred:
        if len(chosen) >= top:
            break
        chosen.append(item)
    picked = {id(x) for x in chosen}
    return chosen + [x for x in items if id(x) not in picked]


resolution_positions = B.resolution_positions  # F5b: the builder's implementation, shared


def rescue_detail(traces: Mapping[int, EpisodeTrace], golds: Sequence, gold_ids: Iterable[str]) -> dict:
    """For each gold: the kept candidates that match it, their episode rank, and where their resolution lines sit."""
    by_id = {g.gold_id: g for g in golds}
    out = {}
    for gid in sorted(gold_ids):
        rows = []
        for trace in traces.values():
            pair_of = {(p.hook, p.cliff): p for p in trace.pairs if p.promo is not None}
            for cand in trace.candidates:
                if set_tiou(promo_segs(cand), by_id[gid].segments) < TAU:
                    continue
                pair = pair_of[(cand["hook"]["line_id"], cand["cliff"]["line_id"])]
                rows.append({"promo_id": cand["promo_id"], "episode_rank": episode_rank(trace.candidates, cand["promo_id"]),
                             "resolution_flagged": pair.resolution_flagged, "extended": pair.extended,
                             "montage": cand["montage"], "resolution_lines": list(pair.resolution_positions)})
        out[gid] = sorted(rows, key=lambda r: r["episode_rank"])
    return out


def resolution_end_summary(traces: Mapping[int, EpisodeTrace], golds: Sequence) -> dict:
    """Among pairs the builder removed with the resolution rule: is the resolution line at the end of the span
    (F5b still drops it) or earlier (F5b keeps it)? Overall and among gold-matching pairs."""
    buckets = {"<=3s": 0, "3-10s": 0, "10-20s": 0, ">20s": 0}
    total = {"pairs": 0, "at_end": 0, "earlier_only": 0}
    matching = {"pairs": 0, "at_end": 0, "earlier_only": 0, "at_end_gold": set(), "earlier_only_gold": set()}
    for trace in traces.values():
        for pair in trace.pairs:
            if pair.first_drop != "resolution":
                continue
            at_end = any(p["at_end"] for p in pair.resolution_positions)
            nearest = min(p["clip_seconds_after"] for p in pair.resolution_positions)
            buckets["<=3s" if nearest <= 3 else "3-10s" if nearest <= 10 else "10-20s" if nearest <= 20 else ">20s"] += 1
            key = "at_end" if at_end else "earlier_only"
            total["pairs"] += 1
            total[key] += 1
            hit = matching_gold(pair.span, golds)
            if hit:
                matching["pairs"] += 1
                matching[key] += 1
                matching[key + "_gold"].update(hit)
    matching["at_end_gold"] = sorted(matching["at_end_gold"])
    matching["earlier_only_gold"] = sorted(matching["earlier_only_gold"])
    return {"resolution_removed_pairs": total, "nearest_resolution_to_clip_end": buckets, "gold_matching": matching}


def gold_resolution_positions(golds: Sequence, index, confidence_by_ep: Mapping[int, Mapping[str, str]],
                              window_ms: int = 3000) -> dict:
    """Where do blocking resolution marks fall inside the human gold promos themselves?"""
    out = {}
    for g in sorted(golds, key=lambda g: g.gold_id):
        found, later = [], 0
        for number in range(len(g.segments) - 1, -1, -1):
            ep, start, end = g.segments[number]
            for line in index.episode_lines(ep):
                if line.start_ms >= start and line.end_ms <= end and line.id in confidence_by_ep.get(ep, {}):
                    found.append({"line_id": line.id, "confidence": confidence_by_ep[ep][line.id],
                                  "clip_seconds_after": round((end - line.end_ms + later) / 1000, 2),
                                  "at_end": number == len(g.segments) - 1 and line.end_ms > end - window_ms})
            later += end - start
        out[g.gold_id] = sorted(found, key=lambda x: -x["clip_seconds_after"])
    return out
