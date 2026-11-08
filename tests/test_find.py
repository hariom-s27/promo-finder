from __future__ import annotations

import json
from types import SimpleNamespace

import openai
import pytest

from promo_finder import cli, finding
from promo_finder.config import PricingCfg, PurposeCfg, load_config
from promo_finder.header import LIMITS
from promo_finder.llm import LLMClient, ProviderError
from promo_finder.understanding_common import UnderstandingError, write_json
from test_llm import FakeClock, http_error, resp


def prepare_context(cfg, episodes, baseline=True):
    out = cfg.root / "outputs/runs/dev/understanding"
    write_json(out / "show_header.json", {key: "invented" for key in LIMITS})
    write_json(out / "characters.json", {"characters": [
        {"speaker_label": "TEST SPEAKER", "role": "invented role", "relationships": []}]})
    if baseline:
        for episode in episodes:
            write_json(out / f"reveals_E{episode.ep:02d}.json", {"episode": episode.ep, "marks": [], "metadata": {}})


@pytest.fixture
def find_cfg(write_config, monkeypatch):
    cfg = load_config(write_config())
    cfg.pricing[cfg.active.picker] = PricingCfg(input_per_million_usd=0.25, output_per_million_usd=2)
    cfg.purposes = {name: PurposeCfg(reasoning_effort="low") for name in ("reveals", "moments")}
    monkeypatch.setattr(finding, "estimate_tokens", lambda text: (len(text) + 3) // 4)
    return cfg


@pytest.fixture
def dev(episode_factory):
    return [episode_factory(ep, [(i * 1000, (i + 1) * 1000) for i in range(4)]) for ep in (5, 6, 7, 8, 19, 20, 21, 22)]


class FindProvider:
    def __init__(self, empty=False, fail=False, retry=False):
        self.empty, self.fail, self.retry = empty, fail, retry
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise ValueError("invented failure text")
        if self.retry:
            self.retry = False
            raise http_error(openai.RateLimitError, 429, {"retry-after": "2"})
        props = kw["response_format"]["json_schema"]["schema"]["properties"]
        if "marks" in props:
            ids = props["marks"]["items"]["properties"]["line_id"]["enum"]
            ep = ids[0].split("-")[0]
            kinds = [] if self.empty else {"E05": ["resolution", "resolution"],
                                           "E19": ["reveal", "reveal", "reveal", "resolution"]}.get(ep, [])
            data = {"marks": [{"line_id": ids[i], "type": kind, "confidence": "high", "what": "invented event"}
                              for i, kind in enumerate(kinds)]}
        else:
            ids = props["hook_starts"]["items"]["properties"]["line_id"]["enum"]
            data = {"hook_starts": [{"line_id": ids[0], "hook_type": "H3", "strength": "3", "why": "invented hook"}],
                    "cliff_ends": [{"line_id": ids[-2], "cliff_type": "C1", "strength": "2", "why": "invented cliff"}]}
        return resp(json.dumps(data), model="fake-find-2026", pt=17, ct=7)


def client_for(cfg, provider):
    clock = FakeClock()
    return LLMClient(cfg, client_factory=lambda *args: provider, clock=clock, sleep=clock.sleep,
                     cache_dir=cfg.root / "outputs/runs/dev/understanding/.llm_cache", token_estimator=lambda text: len(text) // 4)


def test_dry_run_budget_estimates_and_no_outputs(find_cfg, dev):
    prepare_context(find_cfg, dev)
    before = set(find_cfg.root.rglob("*"))
    result = finding.dry_run(find_cfg, dev)
    assert result["planned_calls"] == 16 and result["output_budget_tokens"] == 16000
    assert result["parts"]["moments"]["dependency_allowance_tokens"] == 8000
    assert result["estimated_cost_usd"] == pytest.approx((result["estimated_input_tokens"] * 0.25 + 16000 * 2) / 1000000)
    assert set(find_cfg.root.rglob("*")) == before


def test_cli_dry_run_never_creates_client_or_loads_secrets(find_cfg, dev, monkeypatch, capsys):
    prepare_context(find_cfg, dev)
    monkeypatch.setattr(cli, "load_config", lambda: find_cfg)
    monkeypatch.setattr(finding, "load_requested", lambda *args: dev)
    def forbidden(*args, **kwargs):
        pytest.fail("dry-run performed a forbidden operation")
    monkeypatch.setattr(finding, "LLMClient", forbidden)
    monkeypatch.setattr("promo_finder.config.load_secrets", forbidden)
    assert cli.main(["find", "--dry-run"]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed)["planned_calls"] == 16
    assert "invented" not in printed and not (find_cfg.root / "outputs/runs/dev/moments").exists()


@pytest.mark.parametrize("spec", ["1", "5,11", "26-29", "42-45"])
def test_find_refuses_held_out_before_reading_or_secrets(find_cfg, monkeypatch, capsys, spec):
    monkeypatch.setattr(cli, "load_config", lambda: find_cfg)
    monkeypatch.setattr(finding, "load_requested", lambda *args: pytest.fail("held-out sources read"))
    monkeypatch.setattr("promo_finder.config.load_secrets", lambda *args: pytest.fail("secrets loaded"))
    assert cli.main(["find", "--eps", spec]) == 1
    assert capsys.readouterr().err.strip() == (
        "find: refused: held-out episodes require --allow-held-out; error=HELD_OUT_REFUSED")
    assert not (find_cfg.root / "outputs").exists()


def test_find_budget_refused_before_archive(find_cfg, dev):
    prepare_context(find_cfg, dev)
    find_cfg.max_calls_per_run = 15
    with pytest.raises(UnderstandingError):
        finding.run(find_cfg, dev)
    assert not (find_cfg.root / "outputs/runs/dev/understanding/archive_p02").exists()


def test_find_order_archive_counts_models_and_low_effort(find_cfg, dev):
    prepare_context(find_cfg, dev)
    provider = FindProvider()
    result = finding.run(find_cfg, dev, client=client_for(find_cfg, provider))
    assert result["status"] == "complete" and result["acceptance"]["total_marks"] == 6
    assert len(provider.calls) == 16
    assert all("marks" in row["response_format"]["json_schema"]["schema"]["properties"] for row in provider.calls[:8])
    assert all("hook_starts" in row["response_format"]["json_schema"]["schema"]["properties"] for row in provider.calls[8:])
    assert all(row["reasoning_effort"] == "low" and "temperature" not in row for row in provider.calls)
    assert result["llm"]["http_requests"] == 16 and result["llm"]["input_tokens"] == 272
    assert result["llm"]["output_tokens"] == 112 and result["llm"]["failures"] == 0
    assert result["llm"]["parts"]["moments"]["model_strings"] == ["fake-find-2026"]
    archive = find_cfg.root / "outputs/runs/dev/understanding/archive_p02"
    assert len(list(archive.glob("reveals_E*.json"))) == 8
    assert all(not json.loads(path.read_text(encoding="utf-8"))["marks"] for path in archive.glob("*.json"))
    assert len(list((find_cfg.root / "outputs/runs/dev/moments").glob("moments_E*.json"))) == 8


def test_archive_exists_before_first_provider_request(find_cfg, dev):
    prepare_context(find_cfg, dev)
    provider = FindProvider()
    original = provider.chat.completions.create
    def check_archive(**kw):
        assert len(list((find_cfg.root / "outputs/runs/dev/understanding/archive_p02").glob("*.json"))) == 8
        return original(**kw)
    provider.chat.completions.create = check_archive
    finding.run(find_cfg, dev, client=client_for(find_cfg, provider))


def test_cache_and_no_cache_keep_archive_unchanged(find_cfg, dev):
    prepare_context(find_cfg, dev)
    finding.run(find_cfg, dev, client=client_for(find_cfg, FindProvider()))
    archive = find_cfg.root / "outputs/runs/dev/understanding/archive_p02"
    before = {path.name: path.read_bytes() for path in archive.glob("*.json")}
    provider = FindProvider(fail=True)
    result = finding.run(find_cfg, dev, client=client_for(find_cfg, provider))
    assert provider.calls == [] and result["llm"]["cache_hits"] == 16
    assert result["llm"]["usd"] == result["llm"]["http_requests"] == 0
    fresh = FindProvider()
    finding.run(find_cfg, dev, client=client_for(find_cfg, fresh), no_cache=True)
    assert len(fresh.calls) == 16
    assert {path.name: path.read_bytes() for path in archive.glob("*.json")} == before


@pytest.mark.parametrize("marks,expected", [(2, "failed"), (3, "passed")])
def test_acceptance_boundary(marks, expected):
    result = finding.acceptance({"E05": {"reveal": 0, "resolution": marks}, "E19": {"reveal": 0, "resolution": 0}})
    assert result["status"] == expected and result["minimum_marks"] == 3


def test_acceptance_failure_finishes_both_parts_then_returns_failure(find_cfg, dev, monkeypatch, capsys):
    prepare_context(find_cfg, dev)
    provider = FindProvider(empty=True)
    result = finding.run(find_cfg, dev, client=client_for(find_cfg, provider))
    assert result["status"] == "acceptance_failed" and len(provider.calls) == 16
    monkeypatch.setattr(cli, "load_config", lambda: find_cfg)
    monkeypatch.setattr(finding, "load_requested", lambda *args: dev)
    monkeypatch.setattr("promo_finder.config.load_secrets", lambda *args: None)
    monkeypatch.setattr(finding, "run", lambda *args, **kwargs: result)
    assert cli.main(["find"]) == 1
    assert "invented" not in capsys.readouterr().out


def test_transport_accounting_and_safe_failure(find_cfg, dev):
    prepare_context(find_cfg, dev)
    result = finding.run(find_cfg, dev, client=client_for(find_cfg, FindProvider(retry=True)))
    assert result["llm"]["http_requests"] == 17 and result["llm"]["http_429s"] == 1
    assert result["llm"]["parts"]["reveals"]["calls"] == 8
    provider = FindProvider(fail=True)
    with pytest.raises(ProviderError):
        finding.run(find_cfg, dev, client=client_for(find_cfg, provider), no_cache=True)
    raw = (find_cfg.root / "outputs/runs/dev/moments/find_summary.json").read_text(encoding="utf-8")
    failed = json.loads(raw)
    assert failed["status"] == "failed" and failed["llm"]["failures"] == 1
    assert failed["llm"]["http_requests"] == 1 and "invented failure text" not in raw
