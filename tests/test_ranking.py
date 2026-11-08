from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
import yaml

from promo_finder import judging, ranking
from promo_finder.config import load_config
from test_judging import cold_answer, successful


@pytest.fixture
def formula():
    return yaml.safe_load((Path(__file__).parents[1] / "config/score_formula.yaml").read_text())


def pair():
    promo = {"episode": 1, "flags": {}, "policy": {}, "montage": False}
    record = {"answer_key": {"who": "invented"}, "aggregate": judging.aggregate([successful()]),
              "fidelity": {"status": "ok", "matches": dict.fromkeys(("who", "stakes", "next"), "yes")}}
    return promo, record


def test_all_components_and_official_score(formula):
    p, j = pair()
    values = ranking.components(p, j, formula)
    assert values == pytest.approx({"H": .75, "C": 1, "A": 1, "F": 1, "P": 0, "R": 0, "B": 0,
                                    "F_no_funnel": 1, "S": .925, "S_equal": .95, "S_no_funnel": .925})


@pytest.mark.parametrize("flag,risk", [("contains_reveal", .5), ("contains_low_conf_resolution", 1)])
def test_spoiler_risk_precedence_and_sensitivity(formula, flag, risk):
    p, j = pair()
    p["episode"] = 50
    p["flags"][flag] = True
    values = ranking.components(p, j, formula)
    assert values["R"] == risk
    assert values["F"] == .5 * (1-risk)
    assert values["F_no_funnel"] == 1-risk
    assert values["S_no_funnel"] == pytest.approx(values["S"] + .2*(values["F_no_funnel"]-values["F"]))


def test_hook_penalty_cliff_share_and_orphan_floor(formula):
    p, j = pair()
    data = cold_answer()
    data["hook_now"]["answer"] = "no"
    data["standalone"]["answer"] = "no"
    data["orphan_line"]["answer"] = "yes"
    data["ends_unresolved"]["answer"] = "no"
    j["aggregate"] = judging.aggregate([successful(data), successful(data), successful()], 3)
    j["fidelity"]["matches"] = dict.fromkeys(("who", "stakes", "next"), "no")
    values = ranking.components(p, j, formula)
    assert values["H"] == .375
    assert values["C"] == pytest.approx(1/3)
    assert values["A"] == 0


@pytest.mark.parametrize("category,expected", list(ranking.POLICY.items()))
def test_policy_weights(formula, category, expected):
    p, j = pair()
    p["policy"] = {category: ["invented-id"]}
    assert ranking.components(p, j, formula)["P"] == expected


def test_policy_max_and_all_penalties_clamped(formula):
    p, j = pair()
    p["policy"] = {"violence": [], "sexual": []}
    p["flags"] = dict.fromkeys(("possible_recap", "reaction_cut", "speakers_4"), True)
    p["montage"] = True
    values = ranking.components(p, j, formula)
    assert values["P"] == .7 and values["B"] == 1 and values["F"] == values["F_no_funnel"] == 0


@pytest.mark.parametrize("match,expected", [("yes", 1), ("partly", .75), ("no", .5)])
def test_fidelity_contribution(formula, match, expected):
    p, j = pair()
    j["fidelity"]["matches"] = dict.fromkeys(("who", "stakes", "next"), match)
    assert ranking.components(p, j, formula)["A"] == expected


@pytest.mark.parametrize("case,expected", [("none", []), ("policy", ["policy"]), ("flip", ["flip_rate"]), ("reveal", ["reveal_and_ending"])])
def test_review_rules(formula, case, expected):
    p, j = pair()
    values = ranking.components(p, j, formula)
    if case == "policy": values["P"] = .7
    if case == "flip": j["aggregate"]["flip_rate"] = .4
    if case == "reveal":
        p["flags"]["contains_reveal"] = True
        j["aggregate"]["answers"]["spoils_ending"] = "yes"
    assert ranking.review_reasons(p, j, values, formula) == expected


def test_flip_below_threshold_and_single_unmeasured(formula):
    p, j = pair()
    values = ranking.components(p, j, formula)
    for flip in (.2, None):
        j["aggregate"]["flip_rate"] = flip
        assert not ranking.review_reasons(p, j, values, formula)


@pytest.mark.parametrize("xs,ys,expected", [([1,2,3], [1,2,3], 1), ([1,2,3], [3,2,1], -1),
                                          ([1,1,2], [1,1,2], 1), ([1,1], [1,2], None), ([], [], None)])
def test_kendall_tau_b(xs, ys, expected):
    assert ranking.kendall_tau_b(xs, ys)["tau_b"] == expected


def test_kendall_asymmetric_ties():
    assert ranking.kendall_tau_b([1,1,2], [1,2,3])["tau_b"] == pytest.approx(2/(6**.5))


def row(number, family="H1", ids=None, human=False):
    return {"promo_id": f"invented-{number}", "S": 1-number*.01, "hook_type": family,
            "line_ids": ids or [f"invented-line-{number}"], "needs_human_reasons": ["policy"] if human else []}


def test_launch_control_diversity_overlap_and_fill():
    rows = [row(1), row(2, "H2", rows_ids := ["invented-line-1"]), row(3, "H2"), row(4), row(5, "H3"), row(6, "H4", human=True), row(7)]
    result = ranking.launch_batch(rows)
    assert result["promo_ids"] == ["invented-1", "invented-3", "invented-5", "invented-4", "invented-7"]
    assert result["family_relaxed_fill"] == ["invented-4", "invented-7"]
    assert result["shortfall"] == 0


def test_launch_shortfall_keeps_no_overlap():
    result = ranking.launch_batch([row(1), row(2, "H2", ["invented-line-1"])])
    assert result["promo_ids"] == ["invented-1"] and result["shortfall"] == 4


def test_missing_evidence_has_no_fabricated_score(formula):
    p, j = pair()
    j["fidelity"]["status"] = "failed"
    assert ranking.components(p, j, formula) is None
    assert ranking.review_reasons(p, j, None, formula) == ["missing_evidence"]


def test_formula_hash_and_penalties(write_config):
    cfg = load_config(write_config())
    target = cfg.root / "config/score_formula.yaml"
    target.parent.mkdir(parents=True)
    shutil.copy2(Path(__file__).parents[1]/"config/score_formula.yaml", target)
    _, digest = ranking.load_formula(cfg)
    assert len(digest) == 64
    cfg.builder.penalties.speakers_4 = .1
    with pytest.raises(Exception, match="penalties"):
        ranking.load_formula(cfg)
