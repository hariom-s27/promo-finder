from __future__ import annotations

import json

import pytest

from promo_finder import cli, judging
from promo_finder.config import load_config
from test_judging import jcfg, setup
from test_llm import FakeProvider, FakeClock, resp
from promo_finder.llm import LLMClient


@pytest.mark.parametrize("eps", ["1", "5,11", "26-29", "42-45"])
def test_held_out_refused_before_reads(write_config, monkeypatch, capsys, eps):
    cfg = load_config(write_config())
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(judging, "load_requested", lambda *a: pytest.fail("sealed input read"))
    monkeypatch.setattr("promo_finder.config.load_secrets", lambda *a: pytest.fail("secrets loaded"))
    assert cli.main(["judge", "--eps", eps]) == 1
    assert "HELD_OUT_REFUSED" in capsys.readouterr().err
    assert not (cfg.root / "outputs").exists()


def test_dry_run_without_secrets_or_provider(jcfg, episode_factory, monkeypatch, capsys):
    ep, _ = setup(jcfg, episode_factory)
    monkeypatch.setattr(cli, "load_config", lambda: jcfg)
    monkeypatch.setattr(judging, "load_requested", lambda *a: [ep])
    monkeypatch.setattr(judging, "LLMClient", lambda *a, **k: pytest.fail("provider created"))
    monkeypatch.setattr("promo_finder.config.load_secrets", lambda *a: pytest.fail("secrets loaded"))
    assert cli.main(["judge", "--eps", "5", "--dry-run"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["planned_calls"] == 5
    assert "invented meaning" not in json.dumps(output)


@pytest.mark.parametrize("ok,expected_requests", [(True, 2), (False, 2)])
def test_targeted_pings_check_true_and_stop_on_qwen_failure(jcfg, monkeypatch, capsys, ok, expected_requests):
    for key, family in (("groq_qwen", "alibaba"), ("featherless_llama", "meta")):
        jcfg.models[key] = jcfg.models["fake_b"].model_copy(update={"family": family})
    provider = FakeProvider([resp(json.dumps({"ok": ok})), resp(json.dumps({"ok": ok}))])
    clock = FakeClock()
    actual = LLMClient(jcfg, client_factory=lambda *a: provider, clock=clock, sleep=clock.sleep)
    monkeypatch.setattr(cli, "load_config", lambda: jcfg)
    monkeypatch.setattr(cli, "load_secrets", lambda *a: None)
    monkeypatch.setattr("promo_finder.llm.LLMClient", lambda *a, **k: actual)
    assert cli.main(["ping", "--models", "groq_qwen,featherless_llama", "--no-cache", "--fail-fast"]) == (0 if ok else 1)
    assert len(provider.calls) == expected_requests
    rows = json.loads((jcfg.root / "outputs/judge/pings.json").read_text())["models"]
    assert len(rows) == (2 if ok else 1)
    assert '"data"' not in capsys.readouterr().out
