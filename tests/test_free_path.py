"""Free-demo behavior with invented inputs and fake providers only."""
import json
from pathlib import Path

import pytest

from promo_finder import builder, pipeline
from promo_finder.budget import observe
from promo_finder.config import ConfigError, load_config, required_key_names
from promo_finder.judging import check_family
from test_pipeline import GroqUnifiedProvider, make_pipeline_client

ROOT = Path(__file__).resolve().parents[1]


def test_free_overlay_changes_only_the_approved_roles_batching_and_answer_cap():
    before = (ROOT / "config.yaml").read_bytes()
    base = load_config()
    free = load_config(overlay="config/free.yaml")
    assert free.active.picker == "groq_oss" and free.active.judge == "groq_qwen"
    assert free.models[free.active.picker].model == "openai/gpt-oss-120b"
    assert free.models[free.active.picker].family == "openai"
    assert free.models[free.active.judge].family == "alibaba"
    check_family(free)
    a, b = base.model_dump(), free.model_dump()
    for value in (a, b):
        value["active"].pop("picker")
        value["active"].pop("judge")
        value["understanding"].pop("character_chunk_episodes")
        value["purposes"]["answer_key"].pop("max_completion_tokens")
    assert base.understanding.character_chunk_episodes == 4
    assert free.understanding.character_chunk_episodes == 1
    assert free.purposes["answer_key"].max_completion_tokens == 4500
    assert base.purposes["answer_key"].max_completion_tokens == 6000
    assert a == b and (ROOT / "config.yaml").read_bytes() == before
    assert free.free_demo and not base.free_demo
    assert required_key_names(free) == ["GROQ_API_KEY"]
    assert not load_config(overlay="config/v2.yaml").free_demo
    assert load_config().active == base.active


@pytest.mark.parametrize("text", ["active: {free_path_judge: bad}", "active: {picker: 1}", "active: []",
                                  "models: {}", "judge: {}", "purposes: {}", "pricing: {}"])
def test_role_overlay_does_not_open_other_settings(write_config, text):
    cfgp = write_config()
    overlay = cfgp.parent / "bad.yaml"
    overlay.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(cfgp, overlay=overlay)


@pytest.mark.parametrize("section", ["character_chunk_episodes: 2", "character_chunk_episodes: true", "other: 1"])
def test_free_batching_whitelist_is_singleton_only(tmp_path, section):
    import shutil
    shutil.copy2(ROOT / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "overlay.yaml").write_text(
        "active: {picker: groq_oss, judge: groq_qwen}\nunderstanding: {" + section + "}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="singleton"):
        load_config(tmp_path / "config.yaml", overlay="overlay.yaml")


def test_official_role_overlay_cannot_change_character_batching(tmp_path):
    import shutil
    shutil.copy2(ROOT / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "overlay.yaml").write_text("understanding: {character_chunk_episodes: 1}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="free-role"):
        load_config(tmp_path / "config.yaml", overlay="overlay.yaml")


@pytest.mark.parametrize("patch", ["{answer_key: {max_completion_tokens: 4501}}", "{cold_judge: {max_completion_tokens: 4500}}",
                                  "{answer_key: {max_completion_tokens: 4500, reasoning_effort: high}}", "{}"])
def test_free_cap_whitelist_refuses_other_changes(tmp_path, patch):
    import shutil
    shutil.copy2(ROOT / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "overlay.yaml").write_text("active: {picker: groq_oss, judge: groq_qwen}\npurposes: " + patch, encoding="utf-8")
    with pytest.raises(ConfigError, match="answer-key cap"):
        load_config(tmp_path / "config.yaml", overlay="overlay.yaml")


def free_fixture(cfg):
    cfg._free_demo = True
    cfg.providers["groq"] = cfg.providers["fakeprov"].model_copy(update={"rpm": 30, "tpm": 1_000_000})
    for role in (cfg.active.picker, cfg.active.judge):
        cfg.models[role].provider = "groq"
    return cfg


def test_free_dry_run_never_opens_baseline_clients_or_credentials(p07_cfg, episode_factory, monkeypatch):
    cfg = free_fixture(p07_cfg)
    monkeypatch.setattr(pipeline.baseline, "dry_run", lambda *a, **kw: pytest.fail("baseline"))
    monkeypatch.setattr(pipeline, "LLMClient", lambda *a, **kw: pytest.fail("client"))
    monkeypatch.setattr("promo_finder.config.load_secrets", lambda *a: pytest.fail("credentials"))
    plan = pipeline.dry_run(cfg, [episode_factory(23, [(i*5000, (i+1)*5000) for i in range(4)])])
    assert "baseline" not in plan["parts"] and "baseline" not in plan["order"]
    assert plan["providers"]["groq"]["calls"] == plan["planned_calls"]
    assert sum(m["calls"] for m in plan["models"].values()) == plan["planned_calls"]
    assert plan["known_picker_request_checks"][0]["episodes"] == [23]
    assert not cfg.output_root.exists()


def test_free_pipeline_completes_without_comparison_baseline(p07_cfg, episode_factory, monkeypatch):
    cfg = free_fixture(p07_cfg)
    episode = episode_factory(23, [(i*5000, (i+1)*5000) for i in range(4)])
    monkeypatch.setattr(builder, "previous_episode", lambda *a: None)
    monkeypatch.setattr(pipeline.baseline, "run", lambda *a, **kw: pytest.fail("baseline"))
    monkeypatch.setattr(pipeline.baseline, "dry_run", lambda *a, **kw: pytest.fail("baseline plan"))
    observe(cfg, {"x-ratelimit-remaining-requests": "1000"})
    result = pipeline.run(cfg, [episode], client=make_pipeline_client(cfg, GroqUnifiedProvider()))
    assert result["status"] == "complete" and result["baseline"]["status"] == "skipped"
    assert "baseline" not in result["stages"]
    assert result["stages"]["snap/check"]["status"] == "complete"
    assert not list((cfg.output_root / "baseline").glob("baseline_E*.json"))
    saved = json.loads((cfg.output_root / "run_manifest.json").read_text())
    assert saved["plan"]["comparison_baseline"] == "skipped: free demo, not evaluation"


def test_actual_free_config_completes_with_fake_provider(tmp_path, episode_factory, monkeypatch):
    from promo_finder.demo import prepare, table_rows
    cfg = prepare(tmp_path, [("episode-023-Episode 23.txt", b"invented fixture")])
    episode = episode_factory(23, [(i*5000, (i+1)*5000) for i in range(4)])
    monkeypatch.setattr(builder, "previous_episode", lambda *a: None)
    observe(cfg, {"x-ratelimit-remaining-requests": "1000"})
    result = pipeline.run(cfg, [episode], client=make_pipeline_client(cfg, GroqUnifiedProvider()))
    assert result["status"] == "complete"
    rows = table_rows(cfg)
    assert rows and rows[0]["episode"] == 23 and "Hook: invented" in rows[0]["why"]
    assert {"score", "lane", "start–end", "hook_type", "cliff_type"} <= rows[0].keys()
    summary = json.loads((cfg.output_root / "moments/find_summary.json").read_text())
    assert summary["pricing"] is None


def test_free_plan_exposes_an_oversize_picker_request(p07_cfg, episode_factory):
    cfg = free_fixture(p07_cfg)
    episode = episode_factory(23, [(i*5000, (i+1)*5000) for i in range(4)])
    # Picker and judge have independent providers here so judge pacing still fits.
    cfg.models[cfg.active.judge].provider = "fakeprov"
    cfg.providers["groq"].tpm = 1
    plan = pipeline.dry_run(cfg, [episode])
    assert not plan["known_picker_requests_fit"]
    check = plan["known_picker_request_checks"][0]
    assert check["reserved_tokens"] > check["configured_tpm"]


def test_free_request_checks_reconcile_to_per_model_budgets(tmp_path, episode_factory):
    from promo_finder.demo import prepare
    cfg = prepare(tmp_path, [(f"episode-{ep:03d}-Episode {ep}.txt", b"invented fixture") for ep in (23, 24)])
    episodes = [episode_factory(ep, [(i * 5000, (i + 1) * 5000) for i in range(4)]) for ep in (23, 24)]
    plan = pipeline.dry_run(cfg, episodes)
    assert plan["parts"]["characters"]["calls"] == 2
    assert [row["episodes"] for row in plan["known_picker_request_checks"]] == [[23], [24]]
    for key, model in plan["models"].items():
        rows = [row for row in plan["request_checks"] if row["model_key"] == key]
        assert sum(row["calls"] for row in rows) == model["calls"]
        assert sum(row["reserved_tokens"] * row["calls"] for row in rows) == model["total_token_budget"]
        assert model["daily_token_limit"] == 200000
    largest = plan["largest_request_upper_bound"]
    assert largest["reserved_tokens"] == max(row["reserved_tokens"] for row in plan["request_checks"])
