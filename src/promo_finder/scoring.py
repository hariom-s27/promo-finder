"""P08 scorer: tool and baseline vs the sealed gold set (eval/match_rule.md, frozen v1).

Pure computation. File reading lives in tools/score_p08.py. Nothing here reads or returns
script text, rationale or names: promos are IDs plus (episode, start_ms, end_ms) segments.

Pre-declared choices that the match rule leaves open (approved at P08 Part A):
  * hook-found greedy: each prediction (rank order) takes the unmatched gold with the
    smallest |delta start| <= 2000 ms in the same first-segment episode; ties -> lowest gold_id;
  * Wilson z = 1.959964; n = 0 gives no interval (None, shown as "n/a (n=0)");
  * bootstrap: random.Random(12345), rng.choices with replacement, B = 10,000,
    percentile = numpy "linear" definition;
  * label agreement (D43): positives only, GLOBAL greedy by highest tIoU first
    (ties: lower A gold_id, then lower B row number), one-to-one.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

from .checker import check_promo
from .tiou import Seg, set_tiou

HELD_OUT = frozenset({1, 2, 3, 4, 11, 12, 13, 14, 26, 27, 28, 29, 42, 43, 44, 45})
TAUS = (0.5, 0.3, 0.7)
PRIMARY_TAU = 0.5
HOOK_MS = 2000
Z95 = 1.959964
SPAN_ERRORS = {"UNKNOWN_ID", "CROSS_EP_SPAN", "REVERSED_SPAN", "BAD_SEGMENT_TIME"}


class ScoringError(ValueError):
    """A precondition of the match rule does not hold; scoring must stop."""


@dataclass(frozen=True)
class GoldPromo:
    gold_id: str
    kind: str  # "pos" | "neg"
    grade: int  # 1-3 for pos, 0 for neg
    segments: tuple[Seg, ...]
    hook_type: str = ""
    cliff_type: str = ""
    row_no: int = 0  # 1-based data row in its file


@dataclass(frozen=True)
class PredPromo:
    pos: int  # 1-based position in L (what "rank i" means in the match rule)
    promo_id: str
    segments: tuple[Seg, ...]
    source_rank: Optional[int] = None  # rank as stored in the source file


@dataclass(frozen=True)
class Match:
    pos: int
    promo_id: str
    gold_id: str
    tiou: float


# ── building promos ─────────────────────────────────────────────────────


def spans_of_row(row: Mapping[str, str]) -> list[tuple[str, str]]:
    spans = []
    for i in (1, 2, 3):
        a, b = (row.get(f"seg{i}_start") or "").strip(), (row.get(f"seg{i}_end") or "").strip()
        if a or b:
            if not (a and b):
                raise ScoringError(f"row {row.get('gold_id')}: seg{i} has only one end")
            spans.append((a, b))
    return spans


def segments_from_spans(spans: Sequence[tuple[str, str]], index, cfg=None) -> tuple[Seg, ...]:
    """Line IDs -> ms through the P01 checker (match rule §1). Span errors stop scoring;
    duration/segment-count checks do not apply to gold."""
    res = check_promo(list(spans), index, cfg)
    bad = SPAN_ERRORS.intersection(res.errors)
    if bad or not res.segments:
        raise ScoringError(f"unresolvable spans: {sorted(bad) or ['EMPTY']}")
    return tuple((s.ep, s.start_ms, s.end_ms) for s in res.segments)


def gold_from_rows(rows: Iterable[Mapping[str, str]], index, cfg=None) -> list[GoldPromo]:
    out, seen = [], set()
    for n, row in enumerate(rows, 1):
        gid = (row.get("gold_id") or "").strip()
        kind = (row.get("kind") or "").strip()
        if not gid or gid in seen:
            raise ScoringError(f"row {n}: missing or duplicate gold_id")
        if kind not in ("pos", "neg"):
            raise ScoringError(f"row {n}: kind must be pos/neg")
        seen.add(gid)
        spans = spans_of_row(row)
        if not spans:
            raise ScoringError(f"row {n}: no segments")
        grade = int((row.get("grade") or "0").strip() or 0)
        if (kind == "pos") != (grade in (1, 2, 3)):
            raise ScoringError(f"row {n}: kind/grade mismatch")
        out.append(GoldPromo(gid, kind, grade, segments_from_spans(spans, index, cfg),
                             (row.get("hook_type") or "").strip(), (row.get("cliff_type") or "").strip(), n))
    return out


def tool_preds_from_L(doc: Mapping, index, cfg=None) -> list[PredPromo]:
    """Tool L: segments rebuilt from line IDs (§1); stored ms must agree exactly."""
    out = []
    for pos, p in enumerate(doc["promos"], 1):
        spans = [(s["first_line_id"], s["last_line_id"]) for s in p["segments"]]
        segs = segments_from_spans(spans, index, cfg)
        stored = tuple((int(s["episode"]), int(s["start_ms"]), int(s["end_ms"])) for s in p["segments"])
        if segs != stored:
            raise ScoringError(f"{p['promo_id']}: stored ms differ from checker ms")
        out.append(PredPromo(pos, p["promo_id"], segs, p.get("rank")))
    return out


def stored_segments(p: Mapping) -> tuple[Seg, ...]:
    return tuple((int(s["episode"]), int(s["start_ms"]), int(s["end_ms"])) for s in p["segments"])


def baseline_id(p: Mapping) -> str:
    return f"BL-E{int(p['episode']):02d}-{int(p['within_episode_rank'])}"


def baseline_preds(promos: Sequence[Mapping]) -> list[PredPromo]:
    """Baseline: already-snapped segments (§6), output order kept."""
    return [PredPromo(pos, baseline_id(p), stored_segments(p), p.get("rank")) for pos, p in enumerate(promos, 1)]


def held_out_only(promos: Sequence[Mapping]) -> list[Mapping]:
    """Keep promos whose segments ALL lie in held-out episodes, order kept (§3)."""
    return [p for p in promos if p["segments"] and all(int(s["episode"]) in HELD_OUT for s in p["segments"])]


def assert_held_out(preds: Sequence[PredPromo], what: str) -> None:
    bad = [p.promo_id for p in preds if not p.segments or any(s[0] not in HELD_OUT for s in p.segments)]
    if bad:
        raise ScoringError(f"{what}: {len(bad)} promos not fully in held-out episodes")


def frozen_eval_order(rows: Sequence[Mapping], score: str) -> list[str]:
    """Independent re-implementation of config/eval_order.yaml: scored by `score` desc,
    then unscored by pre_score desc; ties promo_id ascending."""
    scored = sorted((r for r in rows if r.get(score) is not None), key=lambda r: (-r[score], r["promo_id"]))
    unscored = sorted((r for r in rows if r.get(score) is None), key=lambda r: (-r["pre_score"], r["promo_id"]))
    return [r["promo_id"] for r in scored + unscored]


def reorder(preds: Sequence[PredPromo], order: Sequence[str]) -> list[PredPromo]:
    by_id = {p.promo_id: p for p in preds}
    if set(order) != set(by_id) or len(order) != len(by_id):
        raise ScoringError("re-order list and L contain different promos")
    return [PredPromo(i, pid, by_id[pid].segments, by_id[pid].source_rank) for i, pid in enumerate(order, 1)]


# ── matching (§4) ───────────────────────────────────────────────────────


def greedy_match(preds: Sequence[PredPromo], golds: Sequence[GoldPromo], K: int, tau: float) -> list[Match]:
    used, out = set(), []
    for p in preds[:K]:
        best = None
        for g in golds:
            if g.gold_id in used:
                continue
            t = set_tiou(p.segments, g.segments)
            if t >= tau and (best is None or t > best[0] or (t == best[0] and g.gold_id < best[1])):
                best = (t, g.gold_id)
        if best:
            used.add(best[1])
            out.append(Match(p.pos, p.promo_id, best[1], best[0]))
    return out


def hook_ok(pred: Sequence[Seg], gold: Sequence[Seg]) -> bool:
    """FIRST segment vs FIRST segment: same episode and |delta start| <= 2000 ms."""
    if not pred or not gold:
        return False
    return pred[0][0] == gold[0][0] and abs(pred[0][1] - gold[0][1]) <= HOOK_MS


def hook_hit(matches: Sequence[Match], preds: Sequence[PredPromo], golds: Sequence[GoldPromo]) -> list[str]:
    P = {p.promo_id: p for p in preds}
    G = {g.gold_id: g for g in golds}
    return [m.gold_id for m in matches if hook_ok(P[m.promo_id].segments, G[m.gold_id].segments)]


def hook_found(preds: Sequence[PredPromo], golds: Sequence[GoldPromo], K: int) -> list[Match]:
    used, out = set(), []
    for p in preds[:K]:
        best = None
        for g in golds:
            if g.gold_id in used or not hook_ok(p.segments, g.segments):
                continue
            d = abs(p.segments[0][1] - g.segments[0][1])
            if best is None or d < best[0] or (d == best[0] and g.gold_id < best[1]):
                best = (d, g.gold_id)
        if best:
            used.add(best[1])
            out.append(Match(p.pos, p.promo_id, best[1], set_tiou(p.segments, next(g for g in golds if g.gold_id == best[1]).segments)))
    return out


def negative_hits(preds: Sequence[PredPromo], negatives: Sequence[GoldPromo], K: int, tau: float = PRIMARY_TAU) -> list[str]:
    """Negatives with tIoU >= tau against ANY top-K prediction (not one-to-one)."""
    return [n.gold_id for n in negatives if any(set_tiou(p.segments, n.segments) >= tau for p in preds[:K])]


def any_match_count(preds: Sequence[PredPromo], targets: Sequence[GoldPromo], top: int, tau: float = PRIMARY_TAU) -> int:
    """How many of the first `top` predictions reach tIoU >= tau with ANY target (D46, exploratory)."""
    return sum(1 for p in preds[:top] if any(set_tiou(p.segments, t.segments) >= tau for t in targets))


# ── statistics ──────────────────────────────────────────────────────────


def wilson(k: int, n: int, z: float = Z95) -> Optional[tuple[float, float]]:
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def share(k: int, n: int) -> dict:
    ci = wilson(k, n)
    return {"k": k, "n": n, "value": (k / n) if n else None,
            "wilson95": list(ci) if ci else "n/a (n=0)"}


def mcnemar_exact(a: Sequence[int], b: Sequence[int]) -> dict:
    if len(a) != len(b):
        raise ScoringError("paired vectors differ in length")
    n10 = sum(1 for x, y in zip(a, b) if x and not y)
    n01 = sum(1 for x, y in zip(a, b) if y and not x)
    n = n10 + n01
    p = 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(min(n10, n01) + 1)) / 2 ** n)
    return {"tool_only": n10, "baseline_only": n01, "discordant": n, "p_two_sided": p}


def percentile_linear(sorted_vals: Sequence[float], q: float) -> float:
    """numpy.percentile(..., method='linear') for q in [0, 100]."""
    h = (len(sorted_vals) - 1) * q / 100.0
    lo = math.floor(h)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (h - lo) * (sorted_vals[hi] - sorted_vals[lo])


def paired_bootstrap(a: Sequence[int], b: Sequence[int], B: int = 10_000, seed: int = 12345) -> dict:
    if len(a) != len(b) or not a:
        raise ScoringError("bootstrap needs equal, non-empty vectors")
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(d, k=n)) / n for _ in range(B))
    return {"mean_diff": sum(d) / n, "ci95": [percentile_linear(means, 2.5), percentile_linear(means, 97.5)],
            "B": B, "seed": seed, "n": n}


def cohen_kappa(x: Sequence, y: Sequence) -> dict:
    n = len(x)
    agree = sum(1 for a, b in zip(x, y) if a == b)
    out = {"n": n, "raw_agreement": (agree / n) if n else None, "kappa": None}
    if n == 0:
        return out
    cats = sorted(set(x) | set(y), key=str)
    pe = sum((list(x).count(c) / n) * (list(y).count(c) / n) for c in cats)
    po = agree / n
    if pe >= 1 - 1e-12:
        out["kappa_note"] = "undefined (expected agreement = 1)"
    else:
        out["kappa"] = (po - pe) / (1 - pe)
    return out


def weighted_kappa_linear(x: Sequence[int], y: Sequence[int], cats: Sequence[int] = (1, 2, 3)) -> dict:
    n = len(x)
    agree = sum(1 for a, b in zip(x, y) if a == b)
    out = {"n": n, "raw_agreement": (agree / n) if n else None, "kappa": None}
    if n == 0:
        return out
    k = len(cats)
    ix = {c: i for i, c in enumerate(cats)}
    w = lambda i, j: 1 - abs(i - j) / (k - 1)
    po = sum(w(ix[a], ix[b]) for a, b in zip(x, y)) / n
    px = [sum(1 for a in x if a == c) / n for c in cats]
    py = [sum(1 for b in y if b == c) / n for c in cats]
    pe = sum(w(i, j) * px[i] * py[j] for i in range(k) for j in range(k))
    if pe >= 1 - 1e-12:
        out["kappa_note"] = "undefined (expected agreement = 1)"
    else:
        out["kappa"] = (po - pe) / (1 - pe)
    return out


# ── label agreement (D43) ───────────────────────────────────────────────


def global_greedy_pairs(A: Sequence[GoldPromo], B: Sequence[GoldPromo], tau: float) -> list[tuple[GoldPromo, GoldPromo, float]]:
    cand = [(set_tiou(a.segments, b.segments), a, b) for a in A for b in B]
    cand = [c for c in cand if c[0] >= tau]
    cand.sort(key=lambda c: (-c[0], c[1].gold_id, c[2].row_no))
    ua, ub, out = set(), set(), []
    for t, a, b in cand:
        if a.gold_id in ua or b.gold_id in ub:
            continue
        ua.add(a.gold_id)
        ub.add(b.gold_id)
        out.append((a, b, t))
    return out


def label_agreement(A: Sequence[GoldPromo], B: Sequence[GoldPromo]) -> dict:
    A = [g for g in A if g.kind == "pos"]
    B = [g for g in B if g.kind == "pos"]
    out = {"n_A": len(A), "n_B": len(B), "match_f1": {}}
    for tau in TAUS:
        pairs = global_greedy_pairs(A, B, tau)
        tot = len(A) + len(B)
        out["match_f1"][str(tau)] = {"matched": len(pairs), "f1": (2 * len(pairs) / tot) if tot else None}
    pairs = global_greedy_pairs(A, B, PRIMARY_TAU)
    n = len(pairs)
    hook = sum(1 for a, b, _ in pairs if hook_ok(a.segments, b.segments))
    out["at_tau_0.5"] = {
        "n_pairs": n,
        "pairs": [[a.gold_id, b.gold_id, round(t, 6)] for a, b, t in pairs],
        "hook_within_2s": {"k": hook, "n": n, "raw_agreement": (hook / n) if n else None},
        "hook_type": cohen_kappa([a.hook_type for a, _, _ in pairs], [b.hook_type for _, b, _ in pairs]),
        "cliff_type": cohen_kappa([a.cliff_type for a, _, _ in pairs], [b.cliff_type for _, b, _ in pairs]),
        "grade": weighted_kappa_linear([a.grade for a, _, _ in pairs], [b.grade for _, b, _ in pairs]),
    }
    if n < 5:
        out["at_tau_0.5"]["note"] = "too small to interpret"
    return out


# ── one list, all §5 metrics ────────────────────────────────────────────


def evaluate_list(preds: Sequence[PredPromo], gold: Sequence[GoldPromo], K: int) -> dict:
    G = [g for g in gold if g.kind == "pos"]
    N = [g for g in gold if g.kind == "neg"]
    Kuse = min(K, len(preds))
    out = {"L_size": len(preds), "K": K, "K_used": Kuse, "G_size": len(G), "by_tau": {}}
    for tau in TAUS:
        m = greedy_match(preds, G, K, tau)
        out["by_tau"][str(tau)] = {
            "recall_at_K": share(len(m), len(G)),
            "precision_at_10": {"k": sum(1 for x in m if x.pos <= 10), "n": min(10, len(preds)),
                                "value": (sum(1 for x in m if x.pos <= 10) / min(10, len(preds))) if preds else None},
            "matches": [[x.pos, x.promo_id, x.gold_id, round(x.tiou, 6)] for x in m],
        }
    m = greedy_match(preds, G, K, PRIMARY_TAU)
    matched = {x.gold_id for x in m}
    hh = hook_hit(m, preds, G)
    hf = hook_found(preds, G, K)
    neg = negative_hits(preds, N, K)
    out["primary"] = {
        "recall_at_K": share(len(m), len(G)),
        "hook_hit": share(len(hh), len(G)),
        "hook_found": share(len(hf), len(G)),
        "precision_at_10": out["by_tau"]["0.5"]["precision_at_10"],
        "recall_by_grade": {str(gr): share(sum(1 for g in G if g.grade == gr and g.gold_id in matched),
                                           sum(1 for g in G if g.grade == gr)) for gr in (3, 2, 1)},
        "negative_hit_rate": share(len(neg), len(N)),
        "hook_hit_gold_ids": hh,
        "hook_found_pairs": [[x.pos, x.promo_id, x.gold_id, round(x.tiou, 6)] for x in hf],
        "negative_hit_gold_ids": neg,
    }
    out["matched_vector"] = {g.gold_id: int(g.gold_id in matched) for g in sorted(G, key=lambda g: g.gold_id)}
    return out


def per_gold_detail(preds: Sequence[PredPromo], gold: Sequence[GoldPromo], K: int) -> list[dict]:
    """Best tIoU per gold over the top K (diagnostic; for the failure catalogue)."""
    out = []
    for g in sorted(gold, key=lambda g: g.gold_id):
        best = (0.0, None)  # first prediction (lowest position) with the highest tIoU
        for p in preds[:K]:
            t = set_tiou(p.segments, g.segments)
            if best[1] is None or t > best[0]:
                best = (t, p)
        hook = [p.pos for p in preds[:K] if hook_ok(p.segments, g.segments)]
        out.append({"gold_id": g.gold_id, "kind": g.kind, "grade": g.grade, "segments": [list(s) for s in g.segments],
                    "best_tiou": round(best[0], 6), "best_pos": best[1].pos if best[1] else None,
                    "best_promo_id": best[1].promo_id if best[1] else None, "hook_ok_positions": hook})
    return out


def top_n_detail(preds: Sequence[PredPromo], gold: Sequence[GoldPromo], top: int = 10) -> list[dict]:
    out = []
    for p in preds[:top]:
        best = (0.0, None)  # highest tIoU; ties -> lowest gold_id
        for g in sorted(gold, key=lambda g: g.gold_id):
            t = set_tiou(p.segments, g.segments)
            if best[1] is None or t > best[0]:
                best = (t, g)
        out.append({"pos": p.pos, "promo_id": p.promo_id, "segments": [list(s) for s in p.segments],
                    "best_tiou": round(best[0], 6), "best_gold_id": best[1].gold_id if best[1] else None,
                    "best_gold_kind": best[1].kind if best[1] else None})
    return out
