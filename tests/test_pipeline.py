from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from promo_finder import builder, cli, pipeline
from promo_finder.llm import LLMClient
from test_judging import cold_answer
from test_llm import FakeClock, resp


class UnifiedProvider:
    def __init__(self, fail_baseline=False):
        self.calls = []
        self.fail_baseline = fail_baseline
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["response_format"]["type"] == "json_object":
            system = kwargs["messages"][0]["content"].split("Return only JSON matching this schema: ", 1)[1]
            schema, _ = json.JSONDecoder().raw_decode(system)
        else:
            schema = kwargs["response_format"]["json_schema"]["schema"]
        props = schema["properties"]
        self.kinds = getattr(self, "kinds", [])
        self.kinds.append("ping" if list(props) == ["ok"] else "cold" if "hook_rating" in props else "other")
        if list(props) == ["ok"]: data = {"ok": True}
        elif "characters" in props:
            item = props["characters"]["items"]["properties"]
            data = {"characters": [{"speaker_label": label, "role": "invented", "relationships": [], "aliases": [],
                                     "first_line": item["first_line"]["enum"][0]} for label in item["speaker_label"]["enum"]], "mentioned_names": []}
        elif "genre" in props: data = dict.fromkeys(props, "invented")
        elif "marks" in props: data = {"marks": []}
        elif "hook_starts" in props:
            ids = props["hook_starts"]["items"]["properties"]["line_id"]["enum"]
            data = {"hook_starts": [{"line_id": ids[0], "hook_type": "H3", "strength": "3", "why": "invented"}],
                    "cliff_ends": [{"line_id": ids[3], "cliff_type": "C1", "strength": "3", "why": "invented"}]}
        elif "answers" in props:
            ids = props["answers"]["items"]["properties"]["promo_id"]["enum"]
            data = {"answers": [{"promo_id": key, "who": "invented", "stakes": "invented", "open_question": "invented", "resolved_inside": "no"} for key in ids]}
        elif "hook_rating" in props: data = cold_answer()
        elif "promos" in props:
            if self.fail_baseline: raise RuntimeError("invented failure")
            data = {"promos": [{"segments": [{"start_s": 0, "end_s": 20}], "why": "invented"}]}
        else: data = dict.fromkeys(("who", "stakes", "next"), "yes")
        return resp(json.dumps(data), model="invented-returned-model", pt=50, ct=20)


def make_pipeline_client(cfg, provider):
    clock = FakeClock()
    return LLMClient(cfg, client_factory=lambda *a: provider, clock=clock, sleep=clock.sleep,
                     token_estimator=lambda t: (len(t)+3)//4)


def test_pipeline_dry_run_no_secrets_clients_or_outputs(p07_cfg, episode_factory, monkeypatch, capsys):
    episodes = [episode_factory(n, [(i*5000, (i+1)*5000) for i in range(20)]) for n in (9,10,15,16,17)]
    monkeypatch.setattr(cli, "load_config", lambda: p07_cfg)
    monkeypatch.setattr(pipeline.understanding, "load_requested", lambda *a: episodes)
    monkeypatch.setattr(pipeline, "LLMClient", lambda *a, **kw: pytest.fail("client"))
    monkeypatch.setattr("promo_finder.config.load_secrets", lambda *a: pytest.fail("secrets"))
    assert cli.main(["run", "--eps", "9,10,15,16,17", "--run", "pilot", "--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["order"] == list(pipeline.ORDER)
    assert plan["planned_calls"] == 73 and plan["max_calls_per_run"] == 88
    assert plan["parts"]["reveals"]["calls"] == 5 and plan["parts"]["moments"]["calls"] == 5
    assert not (p07_cfg.root / "outputs").exists()


def test_pipeline_end_to_end_order_reuse_and_manifest(p07_cfg, episode_factory, monkeypatch):
    episodes = [episode_factory(n, [(i*5000, (i+1)*5000) for i in range(4)]) for n in (9,10)]
    provider = UnifiedProvider()
    client = make_pipeline_client(p07_cfg, provider)
    monkeypatch.setattr(builder, "previous_episode", lambda *a: None)
    result = pipeline.run(p07_cfg, episodes, client=client)
    assert result["status"] == "complete"
    assert list(result["stages"]) == list(pipeline.ORDER)
    saved = json.loads((p07_cfg.output_root / "run_manifest.json").read_text())
    assert saved["status"] == "complete" and saved["max_calls_per_run"] == 36
    assert saved["returned_model_strings"] == ["invented-returned-model"]
    assert saved["llm"]["parts"]["reveals:fakeprov"]["calls"] == 2
    assert saved["llm"]["parts"]["cold_judge:fakeprov"]["calls"] == 6
    assert result["ranking"]["coverage_selected"] == 1
    assert result["baseline"]["kept"] == 2
    baseline_call = next(c for c in provider.calls if '"promos"' in json.dumps(c["response_format"]))
    assert baseline_call["reasoning_effort"] == "low"
    assert "E09-L" not in baseline_call["messages"][1]["content"]
    with pytest.raises(Exception, match="already used"): pipeline.run(p07_cfg, episodes, client=client)


def test_mixed_fake_run_reviews_exclude_held_out(p07_cfg, episode_factory, monkeypatch):
    episodes = [episode_factory(n, [(i*5000, (i+1)*5000) for i in range(4)]) for n in (9,11)]
    episodes[1].lines[0].text = "invented sealed canary"
    monkeypatch.setattr(builder, "previous_episode", lambda *a: None)
    pipeline.run(p07_cfg, episodes, client=make_pipeline_client(p07_cfg, UnifiedProvider()), allow_held_out=True)
    for path in p07_cfg.output_root.rglob("*.md"):
        content = path.read_text(encoding="utf-8")
        assert "E11" not in content and "invented sealed canary" not in content
        assert "E09" in content
    assert (p07_cfg.output_root / "baseline/baseline_E11.json").exists()


def test_failure_records_partial_manifest_without_provider_message(p07_cfg, episode_factory, monkeypatch):
    episode = episode_factory(9, [(i*5000, (i+1)*5000) for i in range(4)])
    monkeypatch.setattr(builder, "previous_episode", lambda *a: None)
    with pytest.raises(Exception, match="phase failed"):
        pipeline.run(p07_cfg, [episode], client=make_pipeline_client(p07_cfg, UnifiedProvider(fail_baseline=True)))
    saved = json.loads((p07_cfg.output_root / "run_manifest.json").read_text())
    assert saved["status"] == "failed" and saved["stages"]["baseline"]["status"] == "failed"
    assert "invented failure" not in json.dumps(saved)


def test_groq_guard_refuses_before_secrets(p07_cfg, episode_factory, monkeypatch, capsys):
    p07_cfg.providers["groq"] = p07_cfg.providers["fakeprov"].model_copy(update={"rpm": 30, "tpm": 8000})
    p07_cfg.models[p07_cfg.active.judge].provider = "groq"
    episode = episode_factory(9, [(i*5000, (i+1)*5000) for i in range(4)])
    monkeypatch.setattr(cli, "load_config", lambda: p07_cfg)
    monkeypatch.setattr(pipeline.understanding, "load_requested", lambda *a: [episode])
    monkeypatch.setattr("promo_finder.config.load_secrets", lambda *a: pytest.fail("secrets"))
    assert cli.main(["run", "--eps", "9", "--run", "pilot"]) == 1
    assert "GROQ_DAILY_BUDGET_REFUSED" in capsys.readouterr().err


class GroqUnifiedProvider(UnifiedProvider):
    """Exposes rate-limit headers through the raw-response path the wrapper uses for Groq."""

    def __init__(self, remaining=1000):
        super().__init__()
        self.remaining = remaining
        completions = self.chat.completions
        completions.with_raw_response = SimpleNamespace(create=self.raw_create)

    def raw_create(self, **kwargs):
        parsed = self.create(**kwargs)
        return SimpleNamespace(headers={"x-ratelimit-remaining-requests": str(self.remaining)}, parse=lambda: parsed)


def groq_judge(cfg):
    cfg.providers["groq"] = cfg.providers["fakeprov"].model_copy(update={"rpm": 30, "tpm": 1_000_000})
    cfg.models[cfg.active.judge].provider = "groq"


def test_dry_run_plans_one_guard_refresh_ping_for_groq(p07_cfg, episode_factory):
    groq_judge(p07_cfg)
    episode = episode_factory(9, [(i*5000, (i+1)*5000) for i in range(4)])
    plan = pipeline.dry_run(p07_cfg, [episode])
    assert plan["parts"]["guard_refresh_ping"]["calls"] == 1
    assert plan["parts"]["guard_refresh_ping"]["provider"] == "groq"
    assert plan["providers"]["groq"]["calls"] == plan["parts"]["cold_judge"]["calls"] + plan["parts"]["fidelity"]["calls"] + 1


def test_stale_observation_is_refreshed_before_judge_phase(p07_cfg, episode_factory, monkeypatch):
    from promo_finder import budget
    groq_judge(p07_cfg)
    episodes = [episode_factory(n, [(i*5000, (i+1)*5000) for i in range(4)]) for n in (9, 10)]
    monkeypatch.setattr(builder, "previous_episode", lambda *a: None)
    budget.observe(p07_cfg, {"x-ratelimit-remaining-requests": "1000"})
    real_judge_run = pipeline.judging.run

    def judge_after_long_azure_stages(*a, **kw):
        # A stale observation would refuse here unless the refresh ping ran first.
        state = json.loads(budget.state_path(p07_cfg).read_text())
        assert state["remaining_requests"] == 777
        return real_judge_run(*a, **kw)

    def make_stale():
        old = json.loads(budget.state_path(p07_cfg).read_text())
        old["observed_at"] = "2000-01-01T00:00:00+00:00"
        budget.state_path(p07_cfg).write_text(json.dumps(old))

    real_build = pipeline.builder.run
    monkeypatch.setattr(pipeline.builder, "run", lambda *a, **kw: (make_stale(), real_build(*a, **kw))[1])
    monkeypatch.setattr(pipeline.judging, "run", judge_after_long_azure_stages)
    provider = GroqUnifiedProvider(remaining=777)
    result = pipeline.run(p07_cfg, episodes, client=make_pipeline_client(p07_cfg, provider))
    assert result["status"] == "complete"
    pings = [i for i, kind in enumerate(provider.kinds) if kind == "ping"]
    colds = [i for i, kind in enumerate(provider.kinds) if kind == "cold"]
    assert len(pings) == 1 and colds and pings[0] < colds[0]
    saved = json.loads((p07_cfg.output_root / "run_manifest.json").read_text())
    assert saved["stages"]["judge"]["llm"]["parts"]["guard_refresh_ping:groq"]["calls"] == 1


def test_failed_refresh_ping_fails_judge_stage_closed(p07_cfg, episode_factory, monkeypatch):
    groq_judge(p07_cfg)
    monkeypatch.setattr(pipeline.judging, "run", lambda *a, **kw: pytest.fail("judge ran without a fresh observation"))

    class Boom:
        def call(self, *a, **kw):
            from promo_finder.llm import LLMError
            raise LLMError("invented")

    with pytest.raises(Exception):
        pipeline.judge_stage(p07_cfg, [], Boom())


def test_all_held_out_fake_reviews_are_empty(episode_factory):
    from promo_finder import ranking
    episode = episode_factory(11, [(0, 20000)])
    assert "E11" not in builder.review([episode], {})
    text = ranking.markdown([{"segments": [{"episode": 11}]}], {"promo_ids": ["invented"]}, [episode])
    assert "E11" not in text and "invented" not in text
