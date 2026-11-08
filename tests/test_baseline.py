from __future__ import annotations

import inspect
import json
import re
import subprocess

import pytest

from promo_finder import baseline, checker, cli
from promo_finder.checker import build_index, snap_nearest_boundaries
from promo_finder.header import LIMITS


def raw(*segments):
    return {"promos": [{"segments": [{"start_s": a, "end_s": b} for a, b in segments], "why": "invented rationale"}]}


def test_baseline_exact_prompt_schema_and_input(p07_cfg, episode_factory):
    spec = baseline.load_spec(p07_cfg)
    episode = episode_factory(9, [(0, 12300), (12300, 25000)])
    messages = baseline.messages(episode, dict.fromkeys(LIMITS, "invented"), spec)
    assert messages[0]["content"] == spec["prompt"]
    assert "00:00.0–00:12.3 | dialogue | TEST SPEAKER |" in messages[1]["content"]
    assert not re.search(r"E\d{2}-L\d+", json.dumps(messages))
    assert not any(k in messages[1]["content"] for k in ("characters", "marks", "moments", "judge"))
    assert not any('"'+k+'"' in json.dumps(spec["schema"]) for k in ("enum", "pattern", "minItems", "maxItems"))
    assert not baseline.response_errors(raw((.123, 21.456)), spec)


@pytest.mark.parametrize("data", [raw(), {"promos": [raw((0, 20))["promos"][0]] * 6}, raw((0, 1), (2, 3), (4, 5)), raw((float("nan"), 20)), raw((True, 20))])
def test_baseline_code_validates_cardinality_and_numbers(p07_cfg, data):
    assert baseline.response_errors(data, baseline.load_spec(p07_cfg))


@pytest.mark.parametrize("start,end,expected", [(6, 26, ("E09-L002", "E09-L003")),
    (5, 25, ("E09-L001", "E09-L002")), (19, 1, ("E09-L003", "E09-L001"))])
def test_nearest_starts_ends_and_earlier_ties(episode_factory, start, end, expected):
    episode = episode_factory(9, [(0, 10000), (10000, 20000), (20000, 30000)])
    spans, _, _ = snap_nearest_boundaries(9, start*1000, end*1000, build_index([episode]))
    assert spans == expected


def test_duplicate_boundaries_tie_by_earlier_line(episode_factory):
    episode = episode_factory(9, [(0, 10000), (0, 10000)])
    assert snap_nearest_boundaries(9, 0, 10000, build_index([episode]))[0] == ("E09-L001", "E09-L001")


def test_invented_endpoints_count_before_repair(p07_cfg, episode_factory):
    episode = episode_factory(9, [(0, 10000), (10000, 20000), (20000, 30000)])
    result = baseline.snap_promos(raw((-1, 31)), episode, p07_cfg)
    assert result["invented_timestamps"] == 2 and len(result["kept"]) == 1
    assert result["raw"]["promos"][0]["segments"][0] == {"start_s": -1, "end_s": 31}


@pytest.mark.parametrize("segments,reason", [([(0, 10)], "TOO_SHORT"), ([(0, 80)], "TOO_LONG"),
    ([(40, 10)], "REVERSED_SPAN"), ([(50, 70), (0, 20)], "OUT_OF_ORDER"), ([(0, 30), (20, 40)], "OVERLAP")])
def test_checker_drops_with_reasons(p07_cfg, episode_factory, segments, reason):
    episode = episode_factory(9, [(i*10000, (i+1)*10000) for i in range(10)])
    result = baseline.snap_promos(raw(*segments), episode, p07_cfg)
    assert not result["kept"] and reason in result["drops"][0]["reasons"]
    if reason in {"TOO_SHORT", "TOO_LONG"}: assert len(result["sensitivity_kept"]) == 1
    else: assert not result["sensitivity_kept"]


def test_nonpositive_actual_line_time_is_dropped(p07_cfg, episode_factory):
    episode = episode_factory(9, [(10000, 10000)])
    result = baseline.snap_promos(raw((10, 10)), episode, p07_cfg)
    assert result["drops"][0]["reasons"] == ["BAD_SEGMENT_TIME"]


def test_unknown_episode_and_word_trim(p07_cfg):
    data = raw((0, 20))
    data["promos"][0]["why"] = " ".join(["invented"]*20)
    result = baseline.snap_promos(data, None, p07_cfg)
    assert result["drops"][0]["reasons"] == ["UNKNOWN_EPISODE"]
    assert len(result["snapped"][0]["why"].split()) == 12 and result["why_trims"] == 1


def test_round_robin_retains_original_rank_gaps():
    def row(ep, rank): return {"episode": ep, "within_episode_rank": rank}
    result = baseline.round_robin({10: {"kept": [row(10, 1), row(10, 2)]}, 9: {"kept": [row(9, 1), row(9, 3)]}})
    assert [(r["episode"], r["within_episode_rank"]) for r in result] == [(9,1), (10,1), (10,2), (9,3)]


def test_old_snap_function_source_unchanged():
    from pathlib import Path
    project = Path(__file__).resolve().parents[1]
    original = subprocess.run(["git", "show", "HEAD:src/promo_finder/checker.py"], cwd=project, capture_output=True, text=True, check=True).stdout
    original_function = original[original.index("def snap_to_lines("):].strip()
    assert inspect.getsource(checker.snap_to_lines).strip() == original_function


@pytest.mark.parametrize("command", ["run", "baseline", "understand", "find", "build", "judge", "rank"])
def test_pipeline_commands_refuse_held_out_before_secrets(p07_cfg, monkeypatch, capsys, command):
    monkeypatch.setattr(cli, "load_config", lambda: p07_cfg)
    monkeypatch.setattr("promo_finder.config.load_secrets", lambda *a: pytest.fail("secret access"))
    assert cli.main([command, "--eps", "9,11"]) == 1
    assert "HELD_OUT_REFUSED" in capsys.readouterr().err
    assert not p07_cfg.output_root.exists()
