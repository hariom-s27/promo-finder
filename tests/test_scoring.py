"""P08 scorer tests. Every fixture is INVENTED (no script text, no real IDs from the gold set)."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

from promo_finder import scoring as S
from promo_finder.checker import LineIndex
from promo_finder.models import Line
from promo_finder.tiou import set_tiou

ROOT = Path(__file__).resolve().parents[1]


def make_index(eps=(1, 2), n=40, step=5000):
    idx = LineIndex()
    for ep in eps:
        for i in range(1, n + 1):
            lid = f"E{ep:02d}-L{i:03d}"
            idx[lid] = Line(id=lid, ep=ep, idx=i, scene=1, kind="action", text="x",
                            start_ms=(i - 1) * step, end_ms=i * step)
    return idx


def G(gid, segs, kind="pos", grade=3, hook="H1", cliff="C1", row=0):
    return S.GoldPromo(gid, kind, grade if kind == "pos" else 0, tuple(segs), hook, cliff, row)


def P(pos, segs, pid=None):
    return S.PredPromo(pos, pid or f"P{pos:02d}", tuple(segs))


# ── tIoU ────────────────────────────────────────────────────────────────


def test_tiou_exact_cross_episode():
    pred = [(1, 0, 10000), (2, 0, 10000)]
    gold = [(1, 5000, 15000)]
    # inter 5000; union ep1 15000 + ep2 10000
    assert set_tiou(pred, gold) == 5000 / 25000


def test_tiou_no_time_crosses_episodes():
    assert set_tiou([(1, 0, 10000)], [(2, 0, 10000)]) == 0.0


def test_tiou_overlapping_segments_merged():
    assert set_tiou([(1, 0, 6000), (1, 4000, 10000)], [(1, 0, 10000)]) == 1.0


# ── building promos ─────────────────────────────────────────────────────


def test_gold_segments_come_from_line_ids():
    idx = make_index()
    rows = [{"gold_id": "Z01", "kind": "pos", "grade": "2", "seg1_start": "E01-L002", "seg1_end": "E01-L005",
             "seg2_start": "E02-L001", "seg2_end": "E02-L002", "hook_type": "H1", "cliff_type": "C2"}]
    g = S.gold_from_rows(rows, idx)[0]
    assert g.segments == ((1, 5000, 25000), (2, 0, 10000))
    assert (g.grade, g.row_no) == (2, 1)


@pytest.mark.parametrize("row", [
    {"gold_id": "Z01", "kind": "pos", "grade": "3", "seg1_start": "E09-L001", "seg1_end": "E09-L002"},  # unknown id
    {"gold_id": "Z01", "kind": "pos", "grade": "3"},  # no segments
    {"gold_id": "Z01", "kind": "neg", "grade": "2", "seg1_start": "E01-L001", "seg1_end": "E01-L004"},  # kind/grade
    {"gold_id": "Z01", "kind": "pos", "grade": "3", "seg1_start": "E01-L001", "seg1_end": ""},  # half span
])
def test_bad_gold_rows_stop(row):
    with pytest.raises(S.ScoringError):
        S.gold_from_rows([row], make_index())


def test_tool_stored_ms_must_equal_checker_ms():
    idx = make_index()
    seg = {"episode": 1, "start_ms": 0, "end_ms": 20000, "first_line_id": "E01-L001", "last_line_id": "E01-L004"}
    preds = S.tool_preds_from_L({"promos": [{"rank": 7, "promo_id": "X", "segments": [seg]}]}, idx)
    assert preds[0].segments == ((1, 0, 20000),) and preds[0].pos == 1 and preds[0].source_rank == 7
    with pytest.raises(S.ScoringError):
        S.tool_preds_from_L({"promos": [{"rank": 1, "promo_id": "X", "segments": [dict(seg, end_ms=20001)]}]}, idx)


def test_held_out_filter_and_assert():
    promos = [{"episode": 1, "within_episode_rank": 1, "segments": [{"episode": 1, "start_ms": 0, "end_ms": 1}]},
              {"episode": 5, "within_episode_rank": 1, "segments": [{"episode": 5, "start_ms": 0, "end_ms": 1}]},
              {"episode": 2, "within_episode_rank": 2, "segments": [{"episode": 2, "start_ms": 0, "end_ms": 1},
                                                                      {"episode": 6, "start_ms": 0, "end_ms": 1}]}]
    kept = S.held_out_only(promos)
    assert [S.baseline_id(p) for p in kept] == ["BL-E01-1"]
    S.assert_held_out(S.baseline_preds(kept), "x")
    with pytest.raises(S.ScoringError):
        S.assert_held_out(S.baseline_preds(promos), "x")


# ── matching ────────────────────────────────────────────────────────────


def test_greedy_tie_goes_to_lowest_gold_id():
    golds = [G("B02", [(1, 0, 10000)]), G("A07", [(1, 0, 10000)])]
    m = S.greedy_match([P(1, [(1, 0, 10000)])], golds, K=4, tau=0.5)
    assert [(x.gold_id, x.tiou) for x in m] == [("A07", 1.0)]


def test_greedy_is_by_rank_not_global():
    golds = [G("A01", [(1, 0, 10000)])]
    preds = [P(1, [(1, 0, 15000)]), P(2, [(1, 0, 10000)])]  # rank 2 is better but rank 1 goes first
    m = S.greedy_match(preds, golds, K=4, tau=0.5)
    assert [(x.pos, x.gold_id) for x in m] == [(1, "A01")]


def test_greedy_one_to_one_and_K_cut():
    golds = [G("A01", [(1, 0, 10000)]), G("A02", [(1, 20000, 30000)])]
    preds = [P(1, [(1, 0, 10000)]), P(2, [(1, 0, 10000)]), P(3, [(1, 20000, 30000)])]
    assert [x.gold_id for x in S.greedy_match(preds, golds, K=2, tau=0.5)] == ["A01"]
    assert [x.gold_id for x in S.greedy_match(preds, golds, K=3, tau=0.5)] == ["A01", "A02"]


def test_tau_threshold_inclusive():
    golds = [G("A01", [(1, 0, 10000)])]
    preds = [P(1, [(1, 0, 20000)])]  # tIoU exactly 0.5
    assert len(S.greedy_match(preds, golds, 2, 0.5)) == 1
    assert len(S.greedy_match(preds, golds, 2, 0.7)) == 0


# ── hook metrics ────────────────────────────────────────────────────────


def test_hook_hit_versus_hook_found():
    golds = [G("A01", [(1, 10000, 40000)]), G("A02", [(2, 0, 30000)])]
    preds = [
        P(1, [(1, 13000, 43000)]),          # tIoU 27/33 matched; start off by 3 s -> no hook-hit
        P(2, [(2, 1500, 3000), (2, 50000, 70000)]),  # low tIoU, start within 2 s -> hook-found only
    ]
    m = S.greedy_match(preds, golds, 4, 0.5)
    assert [x.gold_id for x in m] == ["A01"]
    assert S.hook_hit(m, preds, golds) == []
    assert [x.gold_id for x in S.hook_found(preds, golds, 4)] == ["A02"]


def test_hook_uses_first_segments_and_same_episode():
    assert S.hook_ok(((1, 1000, 5000), (2, 0, 1)), ((1, 2999, 9000),))
    assert not S.hook_ok(((2, 1000, 5000),), ((1, 1000, 9000),))
    assert not S.hook_ok(((1, 0, 5000), (1, 30000, 40000)), ((1, 30000, 40000),))  # second segment ignored
    assert S.hook_ok(((1, 3000, 5000),), ((1, 1000, 9000),))  # exactly 2000 ms


def test_hook_found_greedy_smallest_delta_then_gold_id():
    golds = [G("A02", [(1, 1000, 9000)]), G("A01", [(1, 1000, 8000)]), G("A03", [(1, 500, 9000)])]
    preds = [P(1, [(1, 1000, 9000)]), P(2, [(1, 1000, 9000)])]
    hf = S.hook_found(preds, golds, 4)
    assert [x.gold_id for x in hf] == ["A01", "A02"]


# ── list metrics ────────────────────────────────────────────────────────


def test_precision_at_10_uses_min_10_L_and_K_used():
    golds = [G(f"A{i:02d}", [(1, i * 20000, i * 20000 + 10000)]) for i in range(1, 4)]
    golds.append(G("N01", [(2, 0, 10000)], kind="neg"))
    preds = [P(1, [(1, 20000, 30000)]), P(2, [(2, 0, 10000)]), P(3, [(1, 60000, 70000)])]
    ev = S.evaluate_list(preds, golds, K=6)
    assert ev["L_size"] == 3 and ev["K_used"] == 3
    p10 = ev["primary"]["precision_at_10"]
    assert (p10["k"], p10["n"]) == (2, 3)
    assert ev["primary"]["recall_at_K"]["k"] == 2 and ev["primary"]["recall_at_K"]["n"] == 3
    assert ev["primary"]["negative_hit_rate"]["k"] == 1
    assert ev["matched_vector"] == {"A01": 1, "A02": 0, "A03": 1}


def test_recall_by_grade_and_n0_wilson_text():
    golds = [G("A01", [(1, 0, 10000)], grade=3), G("A02", [(1, 20000, 30000)], grade=2)]
    ev = S.evaluate_list([P(1, [(1, 0, 10000)])], golds, K=4)
    rbg = ev["primary"]["recall_by_grade"]
    assert (rbg["3"]["k"], rbg["3"]["n"], rbg["2"]["k"], rbg["2"]["n"]) == (1, 1, 0, 1)
    assert rbg["1"]["wilson95"] == "n/a (n=0)" and rbg["1"]["value"] is None
    assert ev["primary"]["negative_hit_rate"]["wilson95"] == "n/a (n=0)"


def test_negative_hits_not_one_to_one():
    negs = [G("N01", [(1, 0, 10000)], kind="neg"), G("N02", [(1, 0, 10000)], kind="neg"), G("N03", [(2, 0, 1000)], kind="neg")]
    preds = [P(1, [(1, 0, 10000)]), P(2, [(2, 0, 1000)])]
    assert S.negative_hits(preds, negs, K=2) == ["N01", "N02", "N03"]
    assert S.negative_hits(preds, negs, K=1) == ["N01", "N02"]


def test_any_match_count_exploratory():
    targets = [G("L01", [(1, 0, 10000)]), G("L02", [(1, 0, 10000)])]
    preds = [P(1, [(1, 0, 10000)]), P(2, [(1, 0, 10000)]), P(3, [(2, 0, 10000)])]
    assert S.any_match_count(preds, targets, 10) == 2  # not one-to-one


# ── statistics ──────────────────────────────────────────────────────────


def test_wilson_known_values():
    lo, hi = S.wilson(8, 16)
    assert lo == pytest.approx(0.2800, abs=1e-4) and hi == pytest.approx(0.7200, abs=1e-4)
    lo, hi = S.wilson(0, 16)
    assert lo == 0.0 and hi == pytest.approx(0.19361, abs=1e-4)
    assert S.wilson(0, 0) is None
    assert S.share(0, 0)["wilson95"] == "n/a (n=0)"


@pytest.mark.parametrize("a,b,p", [
    ([1] * 5, [0] * 5, 2 / 32),
    ([1, 1, 1, 0], [0, 0, 0, 1], 10 / 16),
    ([1, 1, 0, 0], [0, 0, 1, 1], 1.0),
    ([1, 0, 1], [1, 0, 1], 1.0),
])
def test_mcnemar_exact(a, b, p):
    assert S.mcnemar_exact(a, b)["p_two_sided"] == pytest.approx(p)


def test_percentile_linear_matches_numpy_definition():
    assert S.percentile_linear([1, 2, 3, 4], 50) == 2.5
    assert S.percentile_linear([1, 2, 3, 4], 2.5) == pytest.approx(1.075)
    assert S.percentile_linear([1, 2, 3, 4], 100) == 4


def test_bootstrap_deterministic():
    a = [1, 1, 0, 1, 0, 1, 1, 0, 0, 1, 1, 1, 0, 1, 0, 1]
    b = [0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 1, 0, 0, 0, 1]
    r1, r2 = S.paired_bootstrap(a, b), S.paired_bootstrap(a, b)
    assert r1 == r2 and r1["B"] == 10000 and r1["seed"] == 12345
    assert r1["mean_diff"] == pytest.approx(4 / 16)
    assert r1["ci95"][0] <= r1["mean_diff"] <= r1["ci95"][1]
    assert S.paired_bootstrap([1, 0], [1, 0])["ci95"] == [0.0, 0.0]


def test_cohen_kappa_known_and_undefined():
    r = S.cohen_kappa(["a", "a", "b", "b"], ["a", "b", "b", "b"])
    assert r["kappa"] == pytest.approx(0.5) and r["raw_agreement"] == 0.75
    u = S.cohen_kappa(["a", "a"], ["a", "a"])
    assert u["kappa"] is None and u["raw_agreement"] == 1.0 and "undefined" in u["kappa_note"]


def test_weighted_kappa_linear_known():
    r = S.weighted_kappa_linear([1, 2, 3], [1, 3, 3])
    assert r["kappa"] == pytest.approx(2 / 3) and r["raw_agreement"] == pytest.approx(2 / 3)
    assert S.weighted_kappa_linear([3, 3], [3, 3])["kappa"] is None


# ── label agreement ─────────────────────────────────────────────────────


def test_label_agreement_global_greedy_positives_only():
    A = [G("A01", [(1, 0, 10000)], hook="H1", grade=3), G("A02", [(1, 0, 11000)], hook="H2", grade=2),
         G("A09", [(2, 0, 10000)], kind="neg")]
    B = [G("Q01", [(1, 0, 11000)], row=1, hook="H2", grade=2), G("Q02", [(1, 0, 10000)], row=2, hook="H1", grade=3),
         G("Q03", [(2, 0, 10000)], kind="neg", row=3)]
    r = S.label_agreement(A, B)
    assert (r["n_A"], r["n_B"]) == (2, 2)  # negatives excluded
    assert [p[:2] for p in r["at_tau_0.5"]["pairs"]] == [["A01", "Q02"], ["A02", "Q01"]]
    assert r["match_f1"]["0.5"]["f1"] == 1.0
    assert r["at_tau_0.5"]["hook_type"]["raw_agreement"] == 1.0
    assert r["at_tau_0.5"]["note"] == "too small to interpret"


def test_label_agreement_ties_lower_a_id_then_lower_b_row():
    A = [G("A02", [(1, 0, 10000)]), G("A01", [(1, 0, 10000)])]
    B = [G("Q09", [(1, 0, 10000)], row=2), G("Q05", [(1, 0, 10000)], row=1)]
    pairs = S.global_greedy_pairs(A, B, 0.5)
    assert [(a.gold_id, b.gold_id) for a, b, _ in pairs] == [("A01", "Q05"), ("A02", "Q09")]


def test_label_agreement_global_not_by_order():
    A = [G("A01", [(1, 0, 10000)]), G("A02", [(1, 0, 9000)])]
    B = [G("Q01", [(1, 0, 9000)], row=1)]
    pairs = S.global_greedy_pairs(A, B, 0.5)
    assert [(a.gold_id, b.gold_id) for a, b, _ in pairs] == [("A02", "Q01")]  # 1.0 beats 0.9
    r = S.label_agreement(A, B)
    assert r["match_f1"]["0.5"]["f1"] == pytest.approx(2 / 3)


# ── ordering ────────────────────────────────────────────────────────────


def test_frozen_eval_order_and_reorder():
    rows = [{"promo_id": "p3", "S_no_funnel": 0.5, "pre_score": 9}, {"promo_id": "p1", "S_no_funnel": 0.5, "pre_score": 1},
            {"promo_id": "p2", "S_no_funnel": None, "pre_score": 5}, {"promo_id": "p4", "S_no_funnel": None, "pre_score": 5},
            {"promo_id": "p5", "S_no_funnel": 0.9, "pre_score": 0}]
    order = S.frozen_eval_order(rows, "S_no_funnel")
    assert order == ["p5", "p1", "p3", "p2", "p4"]
    preds = [P(i, [(1, 0, 1)], pid=f"p{i}") for i in range(1, 6)]
    re = S.reorder(preds, order)
    assert [(p.pos, p.promo_id) for p in re][:2] == [(1, "p5"), (2, "p1")]
    with pytest.raises(S.ScoringError):
        S.reorder(preds, order[:-1])


def test_frozen_eval_order_agrees_with_ranking_module():
    from promo_finder.ranking import evaluation_order
    rows = [{"promo_id": f"q{i}", "S_no_funnel": (None if i % 3 == 0 else (i % 4) / 4), "pre_score": i % 5}
            for i in range(20)]
    assert S.frozen_eval_order(rows, "S_no_funnel") == [r["promo_id"] for r in evaluation_order(rows, "S_no_funnel")]


# ── tool script ─────────────────────────────────────────────────────────


def _load_tool():
    spec = importlib.util.spec_from_file_location("score_p08", ROOT / "tools/score_p08.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tool_refuses_second_primary_run(tmp_path, monkeypatch):
    mod = _load_tool()
    (tmp_path / "outputs/eval").mkdir(parents=True)
    (tmp_path / "outputs/eval/metrics.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    assert mod.main(["score"]) == 2


def test_tool_stops_on_hash_mismatch(tmp_path, monkeypatch):
    mod = _load_tool()
    for rel, _ in mod.FILES.values():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("invented\n", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    assert mod.main(["score"]) == 3
    assert not (tmp_path / "outputs/eval/metrics.json").exists()
    ledger = mod.jload(tmp_path / "outputs/eval/scoring_ledger.json")
    assert len(ledger) == 1 and ledger[0]["status"] == "aborted, no metrics"


def test_lf_sha256_ignores_crlf(tmp_path):
    mod = _load_tool()
    (tmp_path / "a").write_bytes(b"x\r\ny\r\n")
    (tmp_path / "b").write_bytes(b"x\ny\n")
    assert mod.lf_sha256(tmp_path / "a") == mod.lf_sha256(tmp_path / "b")
