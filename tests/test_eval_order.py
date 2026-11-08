from __future__ import annotations

import copy
import json

import pytest

from promo_finder import judging, ranking
from promo_finder.understanding_common import UnderstandingError, write_json
from test_judging import Provider, client, jcfg, setup


def test_evaluation_order_scored_lanes_then_unscored_by_pre_score():
    rows = [{"promo_id": name, "S": score, "S_no_funnel": no_funnel, "pre_score": pre, "lane": lane}
            for name, score, no_funnel, pre, lane in (("b", .8, .5, 1, "reserve"), ("a", .8, .7, 2, "needs_human"),
                ("d", None, None, 10, "needs_human"), ("c", None, None, 10, "needs_human"), ("e", None, None, 11, "reserve"))]
    assert [r["promo_id"] for r in ranking.evaluation_order(rows)] == ["a", "b", "e", "c", "d"]
    assert [r["promo_id"] for r in ranking.evaluation_order(rows, "S_no_funnel")] == ["a", "b", "e", "c", "d"]


def test_top_four_and_repeat_only_top_one(jcfg, episode_factory):
    episode, candidate = setup(jcfg, episode_factory)
    items = [{**copy.deepcopy(candidate), "promo_id": f"invented-{n}", "pre_score": score}
             for n, score in enumerate((1, 5, 5, 2, 4, 0, 3))]
    write_json(jcfg.output_root / "promos/candidates_E05.json", {"episode": 5, "candidates": items})
    prepared = judging.prepare(jcfg, [episode], full_run=True)
    assert [p["promo_id"] for p in prepared[5]] == ["invented-1", "invented-2", "invented-4", "invented-6"]
    assert list(judging.run_counts(prepared[5], jcfg, full_run=True).values()) == [3, 1, 1, 1]
    summary = judging.run(jcfg, [episode], client(jcfg, Provider()), full_run=True)
    assert summary["current_items"] == 4 and summary["reference_items"] == 0
    assert summary["llm"]["parts"]["cold_judge:fakeprov"]["calls"] == 6
    assert summary["llm"]["parts"]["fidelity:fakeprov"]["calls"] == 4
    from pathlib import Path
    from shutil import copy2
    copy2(Path(__file__).parents[1] / "config/score_formula.yaml", jcfg.root / "config/score_formula.yaml")
    ranked = ranking.run(jcfg, [episode])
    assert ranked["items"] == 7 and ranked["scored"] == 4
    saved = json.loads((jcfg.output_root / "ranked/promos_dev.json").read_text())
    assert [p["promo_id"] for p in saved["promos"][-3:]] == ["invented-3", "invented-0", "invented-5"]


def test_frozen_selection_mismatch_refused(p07_cfg):
    ranking.validate_eval_order(p07_cfg)
    p07_cfg.judge.full_run.top_per_episode = 3
    with pytest.raises(UnderstandingError, match="frozen"): ranking.validate_eval_order(p07_cfg)


def test_judge_daily_guard_precedes_all_provider_requests(jcfg, episode_factory):
    from promo_finder.budget import DailyBudgetRefused
    episode, _ = setup(jcfg, episode_factory)
    jcfg.providers["groq"] = jcfg.providers["fakeprov"].model_copy()
    jcfg.models[jcfg.active.judge].provider = "groq"
    provider = Provider()
    with pytest.raises(DailyBudgetRefused):
        judging.run(jcfg, [episode], client(jcfg, provider))
    assert not provider.calls
