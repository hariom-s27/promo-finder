from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from promo_finder.builder import build_episode
from promo_finder.config import load_config
from promo_finder.understanding_common import UnderstandingError, write_json
from test_builder import bundle, mark

spec = importlib.util.spec_from_file_location("p05_offline", Path(__file__).parents[1] / "tools/p05_offline.py")
offline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(offline)


@pytest.mark.parametrize("enabled", [set(), {"A1"}, {"A2"}, {"A3"}, {"A4"}, {"A1", "A2", "A3", "A4"}])
def test_switches_are_independent(write_config, enabled):
    cfg = offline.variant(load_config(write_config()), enabled)
    assert (cfg.spoiler.reveal_mode == "flag") == ("A1" in enabled)
    assert ("low" not in cfg.spoiler.resolution_block_confidence) == ("A2" in enabled)
    assert cfg.builder.speakers_hard == (5 if "A3" in enabled else 4)
    assert cfg.builder.j5_at_final_end == ("A4" not in enabled)


@pytest.mark.parametrize("confidence,blocked", [("low", False), ("medium", True), ("high", True)])
def test_resolution_confidence(write_config, episode_factory, confidence, blocked):
    cfg = load_config(write_config())
    data = bundle(episode_factory)
    mark(data, kind="resolution")
    data[2]["marks"][0]["confidence"] = confidence
    result, summary = build_episode(*data, cfg)
    assert bool(summary["dropped"]["resolution"]) == blocked
    assert summary["resolution_drops_by_confidence"][confidence] == int(blocked)
    if not blocked:
        assert result["candidates"][0]["flags"]["contains_low_conf_resolution"]


@pytest.mark.parametrize("speakers,kept,penalty", [(3, True, 0), (4, True, .25), (5, False, 0)])
def test_soft_hard_speakers(write_config, episode_factory, speakers, kept, penalty):
    cfg = load_config(write_config())
    data = bundle(episode_factory, cliff=4)
    for number, line in enumerate(data[0].lines[:5]):
        line.speaker = f"INVENTED {number % speakers}"
    output, summary = build_episode(*data, cfg)
    assert bool(output["candidates"]) == kept
    if kept:
        assert output["candidates"][0]["pre_score"] == pytest.approx(4.9 - penalty)
        assert output["candidates"][0]["flags"]["speakers_4"] == (speakers == 4)


@pytest.mark.parametrize("montage", [False, True])
def test_final_cliff_exact_and_first_piece_still_extends(write_config, episode_factory, montage):
    cfg = load_config(write_config())
    data = bundle(episode_factory, cliff=17 if montage else 3)
    cliff = 17 if montage else 3
    data[0].lines[cliff + 1].kind = "camera"
    if montage:
        data[0].lines[2].kind = "action"
    output, _ = build_episode(*data, cfg)
    promo = output["candidates"][0]
    assert promo["segments"][-1]["last_line_id"] == data[0].lines[cliff].id
    assert not promo["flags"]["reaction_cut"]
    if montage:
        assert promo["segments"][0]["last_line_id"] == data[0].lines[2].id


def test_archive_preserves_and_rejects_corruption(tmp_path):
    source = tmp_path / "outputs/promos"
    write_json(source / "candidates_E05.json", {"candidates": [{"promo_id": "P03-E05-001"}]})
    first = offline.archive(tmp_path)
    assert offline.archive(tmp_path) == first
    write_json(source / "archive_p03/candidates_E05.json", {})
    with pytest.raises(UnderstandingError, match="hash"):
        offline.archive(tmp_path)


def test_ten_ablation_rows_reproduce_baseline(write_config, episode_factory, monkeypatch):
    cfg = load_config(write_config())
    data = bundle(episode_factory)
    ep = data[0]
    for name, item in (("moments/moments", data[1]), ("understanding/reveals", data[2]),
                       ("understanding/intensity", data[3]), ("understanding/policy", data[4])):
        write_json(cfg.root / f"outputs/{name}_E05.json", item)
    _, baseline = build_episode(*data, offline.variant(cfg, set()))
    write_json(cfg.root / "outputs/promos/archive_p03/build_summary.json", {"episodes": {"E05": baseline}})
    monkeypatch.setattr(offline.builder, "previous_episode", lambda *args: None)
    result = offline.ablations(cfg, [ep])
    assert len(result["variants"]) == 10
    assert all(row["kept"] == 1 for row in result["variants"].values())
