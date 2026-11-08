from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from promo_finder import builder, cli, finding
from promo_finder.config import load_config
from promo_finder.understanding_common import UnderstandingError, write_json
from test_builder import bundle


def save(cfg, data):
    episode, moments, reveals, intensity, policy = data
    tag = f"E{episode.ep:02d}"
    write_json(cfg.root / f"outputs/moments/moments_{tag}.json", moments)
    for name, value in (("reveals", reveals), ("intensity", intensity), ("policy", policy)):
        write_json(cfg.root / f"outputs/understanding/{name}_{tag}.json", value)


def test_build_cli_no_secrets_no_calls_and_count_only_console(write_config, episode_factory, monkeypatch, capsys):
    cfg = load_config(write_config())
    data = bundle(episode_factory)
    save(cfg, data)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(builder, "load_requested", lambda *args: [data[0]])
    def forbidden(*args, **kwargs):
        pytest.fail("code-only build accessed secrets or provider")
    monkeypatch.setattr("promo_finder.config.load_secrets", forbidden)
    monkeypatch.setattr(finding, "LLMClient", forbidden)
    assert cli.main(["build"]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed)["kept"] == 1 and "invented" not in printed and "TEST SPEAKER" not in printed
    out = cfg.root / "outputs/promos"
    result = json.loads((out / "candidates_E05.json").read_text(encoding="utf-8"))
    promo = result["candidates"][0]
    assert {"promo_id", "episode", "segments", "line_ids", "duration_s", "hook", "cliff", "pre_score", "flags",
            "policy", "montage", "provenance"} == promo.keys()
    assert promo["provenance"]["reveals"]["model_string"] == "invented-model"
    assert "invented line" in (out / "dev_review.md").read_text(encoding="utf-8")
    assert (out / "build_summary.json").is_file()


@pytest.mark.parametrize("spec", ["1", "5,11", "26-29", "42-45"])
def test_build_held_out_refused_before_artifacts_or_sources(write_config, monkeypatch, capsys, spec):
    cfg = load_config(write_config())
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(builder, "load_requested", lambda *args: pytest.fail("held-out sources read"))
    monkeypatch.setattr(builder, "read_json", lambda *args: pytest.fail("held-out artifacts read"))
    monkeypatch.setattr("promo_finder.config.load_secrets", lambda *args: pytest.fail("secrets read"))
    assert cli.main(["build", "--eps", spec]) == 1
    assert capsys.readouterr().err.strip() == (
        "build: refused: held-out episodes require --allow-held-out; error=HELD_OUT_REFUSED")
    assert not (cfg.root / "outputs").exists()


@pytest.mark.parametrize("damage", ["version", "id", "smooth", "missing_smooth", "duplicate_smooth", "provenance", "source", "policy"])
def test_invalid_artifacts_fail_before_outputs(write_config, episode_factory, damage):
    cfg = load_config(write_config())
    data = list(copy.deepcopy(bundle(episode_factory)))
    if damage == "version":
        data[2]["metadata"]["version"] = 1
    elif damage == "id":
        data[1]["hook_starts"][0]["line_id"] = "E05-L999"
    elif damage == "smooth":
        data[3][0]["smooth"] = float("nan")
    elif damage == "missing_smooth":
        data[3].pop()
    elif damage == "duplicate_smooth":
        data[3][1]["line_id"] = data[3][0]["line_id"]
    elif damage == "provenance":
        data[1]["metadata"] = {}
    elif damage == "source":
        data[1]["cliff_ends"][0]["source"] = "invalid"
    else:
        data[4] = [{"line_id": "E05-L999", "category": "violence", "term": "punch"}]
    save(cfg, data)
    with pytest.raises(UnderstandingError):
        builder.run(cfg, [data[0]])
    assert not (cfg.root / "outputs/promos").exists()


def test_missing_input_does_not_replace_existing_output(write_config, episode_factory):
    cfg = load_config(write_config())
    data = bundle(episode_factory)
    save(cfg, data)
    old = cfg.root / "outputs/promos/candidates_E05.json"
    write_json(old, {"invented_existing": True})
    (cfg.root / "outputs/understanding/intensity_E05.json").unlink()
    before = old.read_bytes()
    with pytest.raises(UnderstandingError):
        builder.run(cfg, [data[0]])
    assert old.read_bytes() == before


def test_predecessor_parses_only_available_unsealed_episode(write_config, episode_factory, monkeypatch):
    cfg = load_config(write_config())
    episode = bundle(episode_factory, ep=19)[0]
    files = [Path("episode-004-Episode 9000004.txt"), Path("episode-018-Episode 9000018.txt"),
             Path("episode-019-Episode 9000019.txt")]
    monkeypatch.setattr(builder, "find_episode_files", lambda *args: files)
    read = []
    def parse(path):
        read.append(path)
        return episode_factory(18, [(0, 1000)])
    monkeypatch.setattr(builder, "parse_file", parse)
    assert builder.previous_episode(cfg, episode, {}).ep == 18
    assert read == [files[1]]


def test_multi_episode_summary_statistics_and_recap_methods(write_config, episode_factory):
    cfg = load_config(write_config())
    first, second = bundle(episode_factory), bundle(episode_factory, ep=6, cliff=17)
    save(cfg, first)
    save(cfg, second)
    summary = builder.run(cfg, [first[0], second[0]])
    assert summary["kept"] == 2 and summary["montage_count"] == 1 and summary["montage_share"] == 0.5
    assert summary["duration_s"] == {"min": 20, "median": 20, "max": 20}
    assert summary["recap_flagged_kept_by_method"] == {"similarity": 1, "fallback": 1}
    assert summary["reveal_mode_comparison"] == {"block": 2, "flag": 2}
