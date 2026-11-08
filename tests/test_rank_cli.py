from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from promo_finder import cli, judging, ranking
from promo_finder.config import load_config
from promo_finder.understanding_common import UnderstandingError
from test_judging import jcfg, setup, Provider, client


@pytest.mark.parametrize("eps", ["1", "5,11", "26-29", "42-45"])
def test_rank_refusal_before_any_reads(write_config, monkeypatch, capsys, eps):
    cfg = load_config(write_config())
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(ranking, "load_requested", lambda *a: pytest.fail("sealed input read"))
    assert cli.main(["rank", "--eps", eps]) == 1
    assert "HELD_OUT_REFUSED" in capsys.readouterr().err
    assert not (cfg.root / "outputs").exists()


def test_end_to_end_rank_and_sensitivity_artifacts(jcfg, episode_factory):
    ep, _ = setup(jcfg, episode_factory)
    judging.run(jcfg, [ep], client(jcfg, Provider()))
    shutil.copy2(Path(__file__).parents[1]/"config/score_formula.yaml", jcfg.root / "config/score_formula.yaml")
    summary = ranking.run(jcfg, [ep])
    assert summary["items"] == 1 and summary["lane_counts"]["launch_batch"] == 1
    data = json.loads((jcfg.root / "outputs/runs/dev/ranked/promos_dev.json").read_text())
    row = data["promos"][0]
    assert row["batch_role"] == "control" and row["S_no_funnel"] is not None
    assert row["formula_sha256"] == summary["formula_sha256"]
    assert (jcfg.root / "outputs/runs/dev/ranked/promos_dev.md").is_file()


def test_stale_candidate_is_refused(jcfg, episode_factory):
    ep, _ = setup(jcfg, episode_factory)
    judging.run(jcfg, [ep], client(jcfg, Provider()))
    shutil.copy2(Path(__file__).parents[1]/"config/score_formula.yaml", jcfg.root / "config/score_formula.yaml")
    path = jcfg.root / "outputs/runs/dev/promos/candidates_E05.json"
    data = json.loads(path.read_text())
    data["candidates"][0]["pre_score"] += 1
    path.write_text(json.dumps(data))
    with pytest.raises(UnderstandingError, match="stale"):
        ranking.run(jcfg, [ep])
