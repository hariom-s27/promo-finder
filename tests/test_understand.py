from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from promo_finder import cli, understanding
from promo_finder.config import PricingCfg, load_config
from promo_finder.llm import LLMClient, ProviderError
from promo_finder.understanding_common import UnderstandingError, cost_usd


@pytest.fixture(autouse=True)
def offline_estimator(monkeypatch):
    monkeypatch.setattr(understanding, "estimate_tokens", lambda text: (len(text) + 3) // 4)


@pytest.fixture
def cfg(write_config):
    cfg = load_config(write_config())
    cfg.pricing[cfg.active.picker] = PricingCfg(input_per_million_usd=0.25, output_per_million_usd=2)
    return cfg


@pytest.fixture
def dev(episode_factory):
    return [episode_factory(ep, [(0, 10), (10, 20)]) for ep in [5, 6, 7, 8, 19, 20, 21, 22]]


class FakeUnderstandingProvider:
    def __init__(self, omit_characters=False, fail=False):
        self.calls = []
        self.omit = omit_characters
        self.fail = fail
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise ValueError("invented provider failure")
        props = kwargs["response_format"]["json_schema"]["schema"]["properties"]
        if "characters" in props:
            item = props["characters"]["items"]["properties"]
            chars = [] if self.omit else [{"speaker_label": label, "role": " ".join(["invented"] * 8),
                "relationships": [], "aliases": [], "first_line": item["first_line"]["enum"][0]}
                for label in item["speaker_label"]["enum"]]
            data = {"characters": chars, "mentioned_names": []}
        elif "marks" in props:
            item = props["marks"]["items"]["properties"]
            data = {"marks": [{"line_id": item["line_id"]["enum"][-1], "type": "reveal",
                               "confidence": "medium", "what": " ".join(["invented"] * 14)}]}
        else:
            data = {field: " ".join(["invented"] * 30) for field in props}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data)), finish_reason="stop")],
                               model="fake-understanding-2026", usage=SimpleNamespace(prompt_tokens=17, completion_tokens=7))


def client_for(cfg, provider):
    return LLMClient(cfg, client_factory=lambda *args: provider,
                     cache_dir=cfg.root / "outputs/runs/dev/understanding/.llm_cache",
                     token_estimator=lambda text: (len(text) + 3) // 4, sleep=lambda seconds: None)


def test_dev_dry_run_call_count_and_cost(cfg, dev):
    result = understanding.dry_run(cfg, dev)
    assert result["planned_calls"] == 11
    assert [part["calls"] for part in result["parts"].values()] == [2, 1, 8]
    assert result["estimated_output_tokens"] == 11_000  # invented config: 1000 per call
    assert result["estimated_cost_usd"] == pytest.approx(
        (result["estimated_input_tokens"] * 0.25 + 11_000 * 2) / 1_000_000)
    assert not (cfg.root / "outputs").exists()


def test_cli_dry_run_creates_no_client_or_secrets_or_outputs(cfg, dev, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(understanding, "load_requested", lambda *args: dev)
    def forbidden(*args, **kwargs):
        pytest.fail("dry run attempted provider or secrets access")
    monkeypatch.setattr(understanding, "LLMClient", forbidden)
    monkeypatch.setattr("promo_finder.config.load_secrets", forbidden)
    assert cli.main(["understand", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["planned_calls"] == 11
    assert not (cfg.root / "outputs").exists()


@pytest.mark.parametrize("spec", ["1", "5,11", "26-29", "42-45"])
def test_cli_held_out_refused_before_loading(cfg, monkeypatch, capsys, spec):
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(understanding, "load_requested", lambda *args: pytest.fail("held-out loaded"))
    assert cli.main(["understand", "--eps", spec, "--dry-run"]) == 1
    assert "held-out" in capsys.readouterr().err
    assert not (cfg.root / "outputs").exists()


def test_load_requested_parses_only_selected_sources(cfg, episode_factory, monkeypatch):
    cfg.data_dir = cfg.root
    files = [Path("episode-001-Episode 9000001.txt"), Path("episode-005-Episode 9000005.txt")]
    monkeypatch.setattr(understanding, "find_episode_files", lambda directory: files)
    parsed = []
    def parse(path):
        parsed.append(path)
        return episode_factory(5, [(0, 10)])
    monkeypatch.setattr(understanding, "parse_file", parse)
    assert [e.ep for e in understanding.load_requested(cfg, [5])] == [5]
    assert parsed == [files[1]]


def test_budget_preflight_refuses_without_output(cfg, dev):
    cfg.max_calls_per_run = 10
    with pytest.raises(UnderstandingError, match="planned calls"):
        understanding.dry_run(cfg, dev)
    assert not (cfg.root / "outputs").exists()


def test_pipeline_fake_provider_outputs_trims_models_and_cost(cfg, dev):
    provider = FakeUnderstandingProvider()
    client = client_for(cfg, provider)
    summary = understanding.run(cfg, dev, client=client)
    assert summary["status"] == "complete" and len(provider.calls) == client.calls_made == 11
    assert summary["coverage"] == 1 and not summary["coverage_below_target"]
    assert summary["llm"]["requests"] == 11 and summary["llm"]["cache_hits"] == 0
    assert summary["llm"]["input_tokens"] == 187 and summary["llm"]["output_tokens"] == 77
    assert summary["llm"]["cost_estimate_usd"] == pytest.approx((187 * 0.25 + 77 * 2) / 1_000_000)
    assert summary["trims_by_field"]["characters"]["role"] == 2
    assert summary["trims_by_field"]["reveals"]["what"] == 8
    assert summary["llm"]["parts"]["characters"]["model_strings"] == ["fake-understanding-2026"]
    out = cfg.root / "outputs/runs/dev/understanding"
    assert len(list(out.glob("intensity_E*.json"))) == len(dev)
    assert len(list(out.glob("policy_E*.json"))) == len(dev)
    assert len(list(out.glob("reveals_E*.json"))) == len(dev)
    assert len(list((out / ".llm_cache").glob("*.json"))) == 11
    assert not (cfg.root / ".cache/llm").exists()
    for call in provider.calls:
        assert "temperature" not in call
        assert call["reasoning_effort"] == "minimal"
        assert call["response_format"]["json_schema"]["strict"] is True
        def check(node):
            if isinstance(node, dict):
                assert "pattern" not in node and "minLength" not in node
                if isinstance(node.get("type"), str):
                    assert set(node) <= {"type", "properties", "required", "additionalProperties", "enum", "items", "description"}
                for child in node.values():
                    check(child)
            elif isinstance(node, list):
                for child in node:
                    check(child)
        check(call["response_format"]["json_schema"]["schema"])


def test_low_coverage_continues_and_writes_all_outputs(cfg, dev):
    provider = FakeUnderstandingProvider(omit_characters=True)
    summary = understanding.run(cfg, dev, client=client_for(cfg, provider))
    assert len(provider.calls) == 11 and summary["status"] == "complete"
    assert summary["coverage_below_target"] is True
    out = cfg.root / "outputs/runs/dev/understanding"
    sheet = json.loads((out / "characters.json").read_text(encoding="utf-8"))
    assert sheet["coverage_below_target"] is True
    assert (out / "show_header.json").is_file() and len(list(out.glob("reveals_E*.json"))) == 8


def test_cache_hits_cost_zero_and_no_cache_forces_requests(cfg, dev):
    first = FakeUnderstandingProvider()
    understanding.run(cfg, dev, client=client_for(cfg, first))
    second = FakeUnderstandingProvider(fail=True)
    summary = understanding.run(cfg, dev, client=client_for(cfg, second))
    assert second.calls == [] and summary["llm"]["cache_hits"] == 11
    assert summary["llm"]["input_tokens"] == summary["llm"]["output_tokens"] == 0
    assert summary["llm"]["cost_estimate_usd"] == 0
    third = FakeUnderstandingProvider()
    understanding.run(cfg, dev, client=client_for(cfg, third), no_cache=True)
    assert len(third.calls) == 11


def test_failure_writes_safe_summary_and_counts(cfg, dev):
    provider = FakeUnderstandingProvider(fail=True)
    with pytest.raises(ProviderError):
        understanding.run(cfg, dev, client=client_for(cfg, provider))
    summary = json.loads((cfg.root / "outputs/runs/dev/understanding/run_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "failed" and summary["error_code"] == "PROVIDER_ERROR"
    assert summary["llm"]["parts"]["characters"]["failed_calls"] == 1
    assert summary["llm"]["parts"]["characters"]["http_failures"] == 1
    assert summary["llm"]["parts"]["characters"]["retries"] == 0
    assert "invented provider failure" not in json.dumps(summary)


def test_cached_results_are_revalidated(cfg, dev):
    provider = FakeUnderstandingProvider()
    client = client_for(cfg, provider)
    understanding.run(cfg, dev, client=client)
    cache_files = list(client.cache_dir.glob("*.json"))
    for path in cache_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data.get("data"), dict) and "characters" in data["data"]:
            data["data"]["characters"][0]["first_line"] = "E05-L999"
            path.write_text(json.dumps(data), encoding="utf-8")
            break
    with pytest.raises(UnderstandingError, match="revalidation"):
        understanding.run(cfg, dev, client=client_for(cfg, provider))


def test_prices_and_unknown_rates(cfg):
    assert cost_usd(cfg, 1_000_000, 1_000_000) == 2.25
    cfg.pricing.clear()
    assert cost_usd(cfg, 1, 1) is None
