"""Invented provider responses and fake clocks only. No network or real secrets."""

from __future__ import annotations

import copy
import json
import socket
from types import SimpleNamespace

import httpx
import openai
import pytest

from promo_finder import cli, judging, llm, pipeline
from promo_finder.accounting import summarize
from promo_finder.config import ConfigError, FoundryQuotaCfg, ModelCfg, PricingCfg, ProviderCfg, PurposeCfg, load_config, model_quota
from promo_finder.judge_arms import archive_groq, compare_arms
from promo_finder.llm import LLMClient, LLMError, ProviderError, RateLimited, RateLimiter, _parse_json, default_client_factory
from promo_finder.provider_protocol import foundry_base_url, rate_headers, require_foundry_ping
from promo_finder.run_context import digest, fingerprints, for_run
from promo_finder.understanding_common import write_json
from test_judging import Provider, client as judge_client, cold_answer, jcfg, setup, successful
from test_llm import FakeClock, FakeProvider, MSGS, SCHEMA, cfg, make_client, resp


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network forbidden"))
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network forbidden"))


@pytest.fixture
def foundry_cfg(cfg, monkeypatch):
    from shutil import copy2
    source = load_config().root
    (cfg.root / "config").mkdir(exist_ok=True)
    for name in ("score_formula.yaml", "eval_order.yaml", "baseline.yaml"):
        copy2(source / "config" / name, cfg.root / "config" / name)
    cfg.providers["azure_foundry"] = ProviderCfg(endpoint_env="AZURE_FOUNDRY_ENDPOINT", key_env="AZURE_FOUNDRY_API_KEY", mode="v1")
    cfg.models["azure_llama"] = ModelCfg(provider="azure_foundry", model="llama70", family="meta", structured_output="json_object", params={"max_completion_tokens": 2000})
    cfg.models["groq_qwen"] = cfg.models["fake_b"].model_copy()
    cfg.active.judge = "azure_llama"
    cfg.active.free_path_judge = "groq_qwen"
    cfg.purposes = {"cold_judge": PurposeCfg(max_completion_tokens=800), "fidelity": PurposeCfg(max_completion_tokens=256), "ping": PurposeCfg(max_completion_tokens=64)}
    cfg.pricing["azure_llama"] = PricingCfg(input_per_million_usd=.71, output_per_million_usd=.71, source="RESEARCH", description="list price (RESEARCH), koreacentral meter not confirmed")
    cfg.rate_limit.min_interval_s = 1.5
    cfg.max_calls_per_run = 100
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", "https://invented.cognitiveservices.azure.com/")
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "invented-foundry-key")
    return cfg


def error(status, message="invented error", headers=None):
    typ = {400: openai.BadRequestError, 401: openai.AuthenticationError, 403: openai.PermissionDeniedError,
           404: openai.NotFoundError, 429: openai.RateLimitError, 503: openai.InternalServerError}[status]
    request = httpx.Request("POST", "https://invented.invalid/openai/v1/chat/completions")
    return typ(message, response=httpx.Response(status, headers=headers or {}, request=request), body=None)


def call(client, **kwargs):
    return client.call("azure_llama", MSGS, SCHEMA, purpose="p07.cold_judge.invented", temperature=.7,
                       retry_temperature=.3, max_completion_tokens=800, **kwargs)


def ready_ping(cfg, state=None):
    state = state or {"response_mode": "json_object", "token_parameter": "max_completion_tokens", "settled": True,
                      "api_path": "v1", "endpoint_form": ".cognitiveservices.azure.com", "model_string": "invented-returned"}
    write_json(cfg.output_root / "logs/foundry_protocol.json", {"azure_foundry/llama70": state})
    write_json(cfg.output_root / "judge/ping_azure_llama.json", {"status": "ok", "deployment": "llama70", "protocol": state})


@pytest.mark.parametrize("suffix", ["", "/", "/openai", "/openai/", "/openai/v1", "/openai/v1/"])
def test_foundry_v1_client_normalizes_endpoint(foundry_cfg, monkeypatch, suffix):
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", "https://invented.cognitiveservices.azure.com" + suffix)
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: kwargs)
    monkeypatch.setattr(openai, "AzureOpenAI", lambda **kwargs: pytest.fail("legacy Azure client"))
    created = default_client_factory("azure_foundry", foundry_cfg.providers["azure_foundry"], "v1")
    assert created["base_url"] == "https://invented.cognitiveservices.azure.com/openai/v1/"
    assert created["api_key"] == "invented-foundry-key"
    assert created["max_retries"] == 0


@pytest.mark.parametrize("endpoint", ["http://invented.invalid", "https://invented.invalid/?api-key=invented", "https://invented.invalid/projects/invented"])
def test_foundry_endpoint_rejects_ambiguous_forms(endpoint):
    with pytest.raises(ValueError):
        foundry_base_url(endpoint)


def test_missing_foundry_credential_reports_name_only(foundry_cfg, monkeypatch):
    monkeypatch.delenv("AZURE_FOUNDRY_API_KEY")
    with pytest.raises(llm.MissingKey, match="AZURE_FOUNDRY_API_KEY"):
        default_client_factory("azure_foundry", foundry_cfg.providers["azure_foundry"], "v1")


@pytest.mark.parametrize("family", ["meta", "alibaba"])
def test_both_judge_families_differ_from_picker(foundry_cfg, family):
    foundry_cfg.models["azure_llama"].family = family
    judging.check_family(foundry_cfg)
    type(foundry_cfg).model_validate(foundry_cfg.model_dump())


def test_same_family_is_refused_in_config_and_runtime(foundry_cfg):
    foundry_cfg.models["azure_llama"].family = " OpenAI "
    with pytest.raises(ValueError):
        type(foundry_cfg).model_validate(foundry_cfg.model_dump())
    with pytest.raises(judging.FamilyRefused):
        judging.check_family(foundry_cfg)


def test_production_d74_config_and_prices_have_no_azure_qwen():
    cfg = load_config()
    assert cfg.active.judge == "azure_llama" and cfg.active.free_path_judge == "groq_qwen"
    assert "azure_qwen" not in cfg.models
    assert (cfg.models["azure_llama"].model, cfg.models["azure_llama"].family) == ("llama70", "meta")
    assert model_quota(cfg, "azure_llama") == {"tpm": 20000, "rpm": 20, "utilization": .85, "effective_tpm": 17000, "effective_rpm": 17}
    assert cfg.pricing["azure_llama"].input_per_million_usd == cfg.pricing["azure_llama"].output_per_million_usd == .71
    assert cfg.pricing["azure_llama"].description == "list price (RESEARCH), koreacentral meter not confirmed"


def test_llama_shape_has_temperature_no_thinking_and_records_reasoning(foundry_cfg):
    response = resp('<think>invented reasoning</think>{"ok":true}', model="invented-llama")
    response.usage.completion_tokens_details = SimpleNamespace(reasoning_tokens=7)
    client, provider, _, _ = make_client(foundry_cfg, [response])
    result = call(client)
    request = provider.calls[0]
    assert request["model"] == "llama70" and request["temperature"] == .7
    assert request["max_completion_tokens"] == 800 and request["response_format"] == {"type": "json_object"}
    assert "reasoning_effort" not in request and "extra_body" not in request
    assert "/no_think" not in json.dumps(request)
    assert result.data == {"ok": True} and result.reasoning_tokens == 7
    assert result.thinking_method == "not_applicable" and result.model_string == "invented-llama"
    cached = call(client)
    assert cached.cached and cached.reasoning_tokens == 7 and len(provider.calls) == 1
    assert summarize(client.records, foundry_cfg)["parts"]["cold_judge:azure_foundry"]["reasoning_tokens"] == 7


@pytest.mark.parametrize("text", ['<think>invented</think>{"ok":true}', '<THINK>invented\ntext</THINK> {"ok":true}', '<think>{"bad":1}</think><think>invented</think>```json\n{"ok":true}\n```'])
def test_think_blocks_are_removed_before_json(text):
    assert _parse_json(text) == {"ok": True}


def test_text_mode_parses_first_object_and_preserves_validation():
    assert _parse_json('invented prefix {"ok":true} {"ok":false}', first_object=True) == {"ok": True}
    with pytest.raises(ValueError):
        _parse_json('<think>{"ok":true}</think>invented text', first_object=True)
    with pytest.raises(ValueError):
        _parse_json('{"ok": NaN}', first_object=True)


def test_json_object_to_text_persists_across_clients(foundry_cfg):
    client, provider, _, _ = make_client(foundry_cfg, [error(400, "response_format is not supported"), resp('invented prefix {"ok":true} suffix')])
    result = call(client)
    assert result.response_mode == "text" and len(provider.calls) == 2
    assert provider.calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in provider.calls[1]
    assert provider.calls[0]["messages"] == provider.calls[1]["messages"]
    assert "Return only JSON matching this schema:" in provider.calls[1]["messages"][0]["content"]
    second, fake, _, _ = make_client(foundry_cfg, [resp('invented {"ok":true}')])
    assert call(second, no_cache=True).response_mode == "text"
    assert "response_format" not in fake.calls[0]


def test_successful_json_mode_is_fixed_for_the_run(foundry_cfg):
    client, provider, _, _ = make_client(foundry_cfg, [resp('{"ok":true}'), error(400, "response_format unsupported")])
    call(client)
    with pytest.raises(ProviderError):
        call(client, no_cache=True)
    assert len(provider.calls) == 2 and client.protocol("azure_llama")["response_mode"] == "json_object"


@pytest.mark.parametrize("first_parameter", ["response_format", "max_completion_tokens"])
def test_both_negotiations_preserve_caps_and_persist(foundry_cfg, first_parameter):
    second_parameter = "max_completion_tokens" if first_parameter == "response_format" else "response_format"
    client, provider, _, _ = make_client(foundry_cfg, [error(400, first_parameter + " unsupported"), error(400, second_parameter + " unsupported"), resp('{"ok":true}'), resp('{"ok":true}')])
    result = call(client)
    assert result.token_parameter == "max_tokens" and result.response_mode == "text"
    assert all(r.get("max_completion_tokens", r.get("max_tokens")) == 800 for r in provider.calls)
    client.call("azure_llama", MSGS, SCHEMA, purpose="p07.fidelity.invented", max_completion_tokens=256, temperature=.7)
    assert provider.calls[-1]["max_tokens"] == 256 and "max_completion_tokens" not in provider.calls[-1]
    assert "response_format" not in provider.calls[-1]


@pytest.mark.parametrize("finish,content", [("length", '{"ok":true}'), ("stop", "invented invalid JSON")])
def test_validation_retry_keeps_foundry_purpose_cap(foundry_cfg, finish, content):
    client, provider, _, _ = make_client(foundry_cfg, [resp(content, finish=finish), resp('{"ok":true}')])
    result = call(client)
    assert result.validation_retry_used and result.final_temperature == .3
    assert [r["temperature"] for r in provider.calls] == [.7, .3]
    assert [r["max_completion_tokens"] for r in provider.calls] == [800, 800]


@pytest.mark.parametrize("status,message", [(401, "invented unauthorized"), (403, "invented forbidden"), (404, "deployment llama70 not found"), (400, "Marketplace subscription required")])
def test_foundry_auth_deployment_marketplace_failure_never_switches(foundry_cfg, status, message):
    client, provider, _, modes = make_client(foundry_cfg, [error(status, message)])
    with pytest.raises(ProviderError):
        call(client)
    assert len(provider.calls) == 1 and modes == ["v1"]
    assert foundry_cfg.active.judge == "azure_llama"


def test_endpoint_routing_never_tries_another_form(foundry_cfg):
    client, provider, _, modes = make_client(foundry_cfg, [error(404, "route not found"), resp('{"ok":true}')])
    with pytest.raises(ProviderError):
        call(client)
    assert modes == ["v1"] and len(provider.calls) == 1
    assert client.records[-2]["endpoint_form"] == ".cognitiveservices.azure.com"


@pytest.mark.parametrize("provider_name", ["fakeprov", "groq", "azure_foundry"])
def test_success_and_error_headers_are_whitelisted_for_every_provider(foundry_cfg, provider_name):
    cfg = foundry_cfg
    key = "azure_llama" if provider_name == "azure_foundry" else "fake_b"
    if provider_name == "groq":
        cfg.providers["groq"] = cfg.providers["fakeprov"].model_copy()
        cfg.models[key].provider = "groq"
    headers = {"X-RateLimit-Remaining-Tokens": "19000", "x-ratelimit-remaining-requests": "900",
               "x-ratelimit-used-tokens": "1000",
               "retry-after-ms": "2", "authorization": "invented-sensitive", "set-cookie": "invented-sensitive"}
    failed = error(429, headers=headers)
    client, fake, _, _ = make_client(cfg, [failed, resp('{"ok":true}')])
    def create(**kwargs):
        response = fake._create(**kwargs)
        return SimpleNamespace(headers=headers, parse=lambda: response)
    fake.chat.completions.with_raw_response = SimpleNamespace(create=create)
    result = client.call(key, MSGS, SCHEMA, purpose="unit", max_completion_tokens=800)
    assert result.rate_limit_headers == rate_headers(headers)
    failures = [r for r in client.records if r.get("event") == "http_attempt_failed"]
    assert failures[0]["response_headers"] == rate_headers(headers)
    assert "invented-sensitive" not in client.log_path.read_text(encoding="utf-8")


def test_consecutive_429_stop_is_phase_wide_not_cap_exhaustion(foundry_cfg, monkeypatch):
    monkeypatch.setattr(llm, "MAX_TRIES", 2)
    client, provider, _, _ = make_client(foundry_cfg, [error(429) for _ in range(5)] + [resp('{"ok":true}')])
    for _ in range(2):
        with pytest.raises(ProviderError):
            call(client)
    with pytest.raises(RateLimited):
        call(client)
    assert len(provider.calls) == 5 and client.consecutive_429s == 5
    with pytest.raises(RateLimited):
        call(client)
    assert len(provider.calls) == 5
    client.begin_phase()
    assert call(client).data == {"ok": True}


def test_success_resets_429_streak(foundry_cfg):
    client, provider, _, _ = make_client(foundry_cfg, [error(429) for _ in range(4)] + [resp('{"ok":true}')] + [error(429) for _ in range(4)] + [resp('{"ok":true}')])
    call(client)
    call(client, no_cache=True)
    assert len(provider.calls) == 10 and client.consecutive_429s == 0


def test_fake_pipeline_records_rate_limited_status(p07_cfg, episode_factory):
    episode = episode_factory(9, [(i * 5000, (i + 1) * 5000) for i in range(4)])
    provider = FakeProvider([error(429) for _ in range(5)])
    clock = FakeClock()
    client = LLMClient(p07_cfg, client_factory=lambda *a: provider, clock=clock, sleep=clock.sleep)
    with pytest.raises(RateLimited):
        pipeline.run(p07_cfg, [episode], client=client)
    saved = json.loads((p07_cfg.output_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert saved["status"] == saved["stages"]["understand"]["status"] == "RATE_LIMITED"
    assert len(provider.calls) == 5


def test_judge_stops_instead_of_continuing_after_429s(jcfg, episode_factory):
    episode, _ = setup(jcfg, episode_factory)
    provider = Provider()
    original = provider.create
    def create(**kwargs):
        if "hook_rating" in kwargs["response_format"]["json_schema"]["schema"]["properties"]:
            provider.calls.append(kwargs)
            raise error(429)
        return original(**kwargs)
    provider.chat.completions.create = create
    with pytest.raises(RateLimited):
        judging.run(jcfg, [episode], judge_client(jcfg, provider))
    summary = json.loads((jcfg.output_root / "judge/judge_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "RATE_LIMITED" and summary["error_code"] == "RATE_LIMITED"
    assert len(provider.calls) == 6  # one answer key, then exactly five failed cold requests
    assert json.loads((jcfg.output_root / "judge/judge_E05.json").read_text(encoding="utf-8"))["partial"]


def test_dual_rolling_window_never_exceeds_eighty_five_percent(foundry_cfg):
    quota = model_quota(foundry_cfg, "azure_llama")
    clock = FakeClock()
    limiter = RateLimiter(quota["effective_rpm"], quota["effective_tpm"], clock=clock, sleep=clock.sleep, min_interval_s=1.5)
    history = []
    for tokens in ([100] * 25 + [8000, 9000, 17000, 300, 1700] * 5):
        entry = limiter.acquire(tokens)
        history.append(tuple(entry))
        window = [e for e in history if e[0] > entry[0] - 60]
        assert sum(e[1] for e in window) <= 17000 and len(window) <= 17
    assert all(b[0] - a[0] >= 1.5 for a, b in zip(history, history[1:]))
    with pytest.raises(LLMError):
        limiter.acquire(17001)
    assert max(clock.sleeps) <= 60


def test_foundry_reserves_input_plus_output_without_early_release(foundry_cfg):
    client, provider, clock, _ = make_client(foundry_cfg, [resp('{"ok":true}', pt=1, ct=1) for _ in range(3)])
    for _ in range(3):
        client.call("azure_llama", MSGS, SCHEMA, purpose="unit", max_completion_tokens=8500, no_cache=True)
    starts = [r for r in client.records if r.get("event") == "http_attempt_started"]
    assert all(r["reserved_tokens"] > 8500 for r in starts)
    assert clock.t >= 1120 and len(provider.calls) == 3


def test_remaining_token_header_delays_next_request(foundry_cfg):
    client, provider, clock, _ = make_client(foundry_cfg, [resp('{"ok":true}'), resp('{"ok":true}')])
    first = [True]
    def create(**kwargs):
        response = provider._create(**kwargs)
        headers = {"x-ratelimit-remaining-tokens": "3001", "x-ratelimit-reset-tokens": "60s"} if first.pop(0) else {}
        return SimpleNamespace(headers=headers, parse=lambda: response)
    # The second reply no longer advertises the exhausted window.
    first[:] = [True, False]
    provider.chat.completions.with_raw_response = SimpleNamespace(create=create)
    call(client)
    call(client, no_cache=True)
    assert clock.t >= 1060


def test_foundry_honours_long_retry_after_in_bounded_sleeps(foundry_cfg):
    client, _, clock, _ = make_client(foundry_cfg, [error(429, headers={"retry-after-ms": "65000"}), resp('{"ok":true}')])
    call(client)
    assert clock.t >= 1065 and max(clock.sleeps) <= 60


def test_ping_uses_judge_shape_and_records_fixed_protocol(foundry_cfg, monkeypatch, capsys):
    client, fake, _, _ = make_client(foundry_cfg, [error(400, "response_format unsupported"), error(400, "max_completion_tokens unsupported"), resp('invented {"ok":true}')])
    monkeypatch.setattr(cli, "load_config", lambda: foundry_cfg)
    monkeypatch.setattr(cli, "load_secrets", lambda *a: None)
    monkeypatch.setattr(llm, "LLMClient", lambda *a, **k: client)
    assert cli.main(["ping", "--models", "azure_llama", "--run", "dev", "--no-cache"]) == 0
    assert fake.calls[0]["temperature"] == .7 and fake.calls[0]["max_completion_tokens"] == 800
    assert fake.calls[0]["response_format"] == {"type": "json_object"}
    assert all(r.get("max_completion_tokens", r.get("max_tokens")) == 800 for r in fake.calls)
    ping = json.loads((foundry_cfg.output_root / "judge/ping_azure_llama.json").read_text(encoding="utf-8"))
    assert ping["protocol"]["settled"] and ping["protocol"]["response_mode"] == "text"
    assert ping["protocol"]["token_parameter"] == "max_tokens" and ping["model_string"]
    require_foundry_ping(foundry_cfg)
    assert "invented-foundry-key" not in capsys.readouterr().out


def test_ping_dry_run_has_no_secrets_or_client(foundry_cfg, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: foundry_cfg)
    monkeypatch.setattr(cli, "load_secrets", lambda *a: pytest.fail("secrets"))
    monkeypatch.setattr(llm, "LLMClient", lambda *a, **k: pytest.fail("provider"))
    assert cli.main(["ping", "--models", "azure_llama", "--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["calls"] == 1 and plan["max_calls_per_run"] == 5
    assert plan["requests"]["azure_llama"]["max_output_tokens"] == 800
    assert not (foundry_cfg.output_root / "judge/ping_azure_llama.json").exists()


@pytest.mark.parametrize("name", ["AZURE_FOUNDRY_API_KEY", "AZURE_FOUNDRY_ENDPOINT"])
def test_ping_missing_credential_prints_only_name(foundry_cfg, monkeypatch, capsys, name):
    monkeypatch.delenv(name)
    client = LLMClient(foundry_cfg)
    monkeypatch.setattr(cli, "load_config", lambda: foundry_cfg)
    monkeypatch.setattr(cli, "load_secrets", lambda *a: None)
    monkeypatch.setattr(llm, "LLMClient", lambda *a, **k: client)
    assert cli.main(["ping", "--models", "azure_llama", "--no-cache"]) == 1
    assert capsys.readouterr().out.strip() == name
    assert client.calls_made == 0
    row = json.loads((foundry_cfg.output_root / "judge/ping_azure_llama.json").read_text(encoding="utf-8"))
    assert row["missing_variable_name"] == name and row["credential_set"] == "azure_foundry"


def test_failed_ping_reports_http_code_and_credential_names_only(foundry_cfg, monkeypatch, capsys):
    failure = error(401)
    failure.body = {"error": {"code": "Unauthorized", "message": "invented-sensitive-body"}}
    client, fake, _, modes = make_client(foundry_cfg, [failure])
    monkeypatch.setattr(cli, "load_config", lambda: foundry_cfg)
    monkeypatch.setattr(cli, "load_secrets", lambda *a: None)
    monkeypatch.setattr(llm, "LLMClient", lambda *a, **k: client)
    assert cli.main(["ping", "--models", "azure_llama", "--no-cache"]) == 1
    row = json.loads(capsys.readouterr().out)
    assert row["exact_error_code"] == "HTTP_401" and row["provider_error_code"] == "Unauthorized"
    assert row["credential_set"] == "azure_foundry"
    assert row["credential_variable_names"] == ["AZURE_FOUNDRY_API_KEY", "AZURE_FOUNDRY_ENDPOINT"]
    assert "invented-sensitive" not in json.dumps(row)
    assert modes == ["v1"] and len(fake.calls) == 1


def test_successful_ping_required_and_can_be_inherited_by_pilot(foundry_cfg):
    with pytest.raises(LLMError, match="ping required"):
        require_foundry_ping(foundry_cfg)
    ready_ping(foundry_cfg)
    require_foundry_ping(foundry_cfg)
    require_foundry_ping(for_run(foundry_cfg, "pilot"))
    marker = foundry_cfg.output_root / "judge/ping_azure_llama.json"
    marker.write_text('{"status":"failed"}', encoding="utf-8")
    with pytest.raises(LLMError):
        require_foundry_ping(foundry_cfg)


def test_config_only_switch_changes_provider_and_keeps_picker_cache_identity(foundry_cfg):
    client, _, _, _ = make_client(foundry_cfg, [resp('{"ok":true}'), resp('{"ok":true}')])
    before = client.call(foundry_cfg.active.picker, MSGS, SCHEMA, purpose="key")
    foundry_cfg.active.judge = "groq_qwen"
    judging.check_family(foundry_cfg)
    again = client.call(foundry_cfg.active.picker, MSGS, SCHEMA, purpose="key")
    assert again.cached and again.cache_key == before.cache_key
    foundry_cfg.active.judge = "azure_llama"
    judging.check_family(foundry_cfg)
    assert call(client).model_string


def test_required_cache_hit_never_spends(foundry_cfg):
    client, fake, _, _ = make_client(foundry_cfg, [])
    with pytest.raises(LLMError, match="cache hit"):
        client.call(foundry_cfg.active.picker, MSGS, SCHEMA, purpose="key", cache_only=True)
    assert not fake.calls and client.calls_made == 0


def test_groq_arm_copy_counts_and_hashes_and_tamper_refusal(p07_cfg):
    sources = []
    for base in (p07_cfg.root / "outputs", p07_cfg.output_root):
        for stage in ("judge", "logs", "ranked"):
            path = base / stage / "invented.json"
            write_json(path, {"invented": stage})
            sources.append(path)
    original = {str(p): p.read_bytes() for p in sources}
    result = archive_groq(p07_cfg)
    assert result["file_count"] == 6 and result["file_count_by_arm"] == {"p05": 3, "p07": 3}
    assert result == archive_groq(p07_cfg)
    assert all(p.read_bytes() == original[str(p)] for p in sources)
    marker = json.loads((p07_cfg.output_root / "arms/groq/archive_manifest.json").read_text(encoding="utf-8"))
    assert len(marker["files_sha256"]) == result["file_count"]
    for rel, sha in marker["files_sha256"].items():
        assert digest(p07_cfg.output_root / "arms/groq" / rel) == sha
    (p07_cfg.output_root / "arms/groq/p05/judge/invented.json").write_text("invented changed", encoding="utf-8")
    with pytest.raises(Exception, match="hash mismatch"):
        archive_groq(p07_cfg)


@pytest.mark.parametrize("name", ["eval_order.yaml", "baseline.yaml"])
def test_other_frozen_hashes_fail_closed(p07_cfg, name):
    path = p07_cfg.root / "config" / name
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(Exception, match="hash mismatch"):
        fingerprints(p07_cfg, required=True)


def test_unknown_foundry_price_never_becomes_zero(foundry_cfg):
    foundry_cfg.pricing.pop("azure_llama")
    client, _, _, _ = make_client(foundry_cfg, [resp('{"ok":true}')])
    call(client)
    result = summarize(client.records, foundry_cfg)
    assert result["parts"]["cold_judge:azure_foundry"]["usd"] is None
    assert result["providers"]["azure_foundry"]["usd"] is None


def test_configured_price_ignores_nonbillable_route_metadata(foundry_cfg):
    client, _, _, _ = make_client(foundry_cfg, [resp('{"ok":true}', pt=11, ct=3)])
    call(client)
    assert any(r.get("purpose") == "azure_path" for r in client.records)
    summary = summarize(client.records, foundry_cfg)
    assert summary["providers"]["azure_foundry"]["usd"] == pytest.approx(14 * .71 / 1e6)


@pytest.mark.parametrize("scored,allowed", [(37, False), (38, True), (39, True)])
def test_live_pilot_requires_official_dev_coverage(foundry_cfg, scored, allowed):
    write_json(foundry_cfg.output_root / "ranked/promos_dev.json", {"summary": {"items": 39, "scored": scored, "judge_model_key": "azure_llama"}})
    pilot = for_run(foundry_cfg, "pilot")
    if allowed:
        pipeline.require_dev_acceptance(pilot)
    else:
        with pytest.raises(Exception, match="38/39"):
            pipeline.require_dev_acceptance(pilot)


def test_d70_guard_refresh_is_skipped_for_foundry(foundry_cfg):
    client = SimpleNamespace(call=lambda *a, **k: pytest.fail("Groq ping"))
    assert pipeline.refresh_groq_budget(foundry_cfg, client) is None


def test_foundry_dev_dry_run_uses_same_quota_and_cache_isolation(jcfg, episode_factory, monkeypatch, capsys):
    episode, _ = setup(jcfg, episode_factory)
    jcfg.models["azure_llama"] = ModelCfg(provider="azure_foundry", model="llama70", family="meta", structured_output="json_object", params={"max_completion_tokens": 2000})
    jcfg.providers["azure_foundry"] = ProviderCfg(endpoint_env="AZURE_FOUNDRY_ENDPOINT", key_env="AZURE_FOUNDRY_API_KEY", mode="v1")
    jcfg.active.judge = "azure_llama"
    jcfg.pricing["azure_llama"] = PricingCfg(input_per_million_usd=.71, output_per_million_usd=.71)
    monkeypatch.setattr(cli, "load_config", lambda: jcfg)
    monkeypatch.setattr(judging, "load_requested", lambda *a: [episode])
    monkeypatch.setattr(judging, "LLMClient", lambda *a, **k: pytest.fail("client"))
    monkeypatch.setattr("promo_finder.config.load_secrets", lambda *a: pytest.fail("secrets"))
    assert cli.main(["judge", "--eps", "5", "--run", "dev", "--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["judge_quota"]["effective_tpm"] == 17000 and plan["judge_quota"]["effective_rpm"] == 17
    assert plan["parts"]["cold_judge"]["model_key"] == "azure_llama"
    assert plan["parts"]["cold_judge"]["estimated_usd"] > 0


def test_foundry_pipeline_dry_run_reports_both_quotas_prices_and_no_groq(p07_cfg, episode_factory):
    cfg = p07_cfg
    cfg.providers["azure_foundry"] = ProviderCfg(endpoint_env="INVENTED_ENDPOINT", key_env="INVENTED_KEY")
    cfg.models["azure_llama"] = ModelCfg(provider="azure_foundry", model="llama70", family="meta", structured_output="json_object")
    cfg.active.judge = "azure_llama"
    cfg.pricing["azure_llama"] = PricingCfg(input_per_million_usd=.71, output_per_million_usd=.71)
    episodes = [episode_factory(n, [(i*5000, (i+1)*5000) for i in range(20)]) for n in (9, 10, 15, 16, 17)]
    result = pipeline.dry_run(cfg, episodes)
    assert result["planned_calls"] == 73 and result["max_calls_per_run"] == 88
    assert result["providers"]["azure_foundry"]["calls"] == 50
    assert result["providers"]["azure_foundry"]["estimated_usd"] > 0
    assert result["estimated_judge_pacing_s"] > 0 and "guard_refresh_ping" not in result["parts"]
    assert "groq" not in result["providers"]
    assert not cfg.output_root.exists()


def test_fifty_episode_estimate_uses_azure_llama_meter(foundry_cfg):
    from promo_finder.estimation import estimate_50
    from test_estimation import saved_pilot
    pilot = saved_pilot()
    pilot["llm"]["parts"] = {label.replace(":groq", ":azure_foundry"): row for label, row in pilot["llm"]["parts"].items()}
    estimate = estimate_50(foundry_cfg, pilot, {"kept": 20})
    assert estimate["azure_foundry"]["model_key"] == "azure_llama" and estimate["azure_foundry"]["deployment"] == "llama70"
    assert estimate["azure_foundry"]["usd"] == pytest.approx(54000 * .71 / 1e6)
    assert estimate["groq_calls"] == 0 and not estimate["two_day_split_if_needed"]
    assert estimate["daily_guard"]["status"] == "not_applicable" and estimate["fits_one_day"] is None


def test_judge_swap_agreement_uses_common_ids_and_tau_b(p07_cfg):
    def item(key, yes=True):
        runs = [successful(cold_answer(answer="yes" if yes else "no")) for _ in range(3)]
        candidate = {"promo_id": key, "reference": True, "invented": 1}
        return {"promo_id": key, "candidate": candidate, "reference": True, "runs": runs, "aggregate": judging.aggregate(runs, 3)}
    write_json(p07_cfg.root / "outputs/judge/judge_E05.json", {"items": [item("invented-a"), item("invented-b")]})
    archive_groq(p07_cfg)
    write_json(p07_cfg.output_root / "judge/judge_E05.json", {"items": [item("invented-a"), item("invented-b", False), item("invented-new")]})
    result = compare_arms(p07_cfg)
    assert result["common_items"] == 2
    assert result["questions"]["hook_now"] == {"agree": 1, "assessed": 2, "agreement": .5}
    assert result["kendall_S"]["n"] == 0 and result["kendall_S"]["tau_b"] is None


def test_judge_swap_tau_joins_scores_by_promo_identity(p07_cfg):
    def item(key, rating):
        data = cold_answer()
        data["hook_rating"] = str(rating)
        runs = [successful(data)]
        candidate = {"promo_id": key, "reference": False, "episode": 5, "flags": {}, "policy": [], "montage": False}
        return {"promo_id": key, "candidate": candidate, "reference": False, "runs": runs,
                "aggregate": judging.aggregate(runs), "answer_key": {"who": "invented"},
                "fidelity": {"status": "ok", "matches": dict.fromkeys(("who", "stakes", "next"), "yes")}}
    write_json(p07_cfg.root / "outputs/judge/judge_E05.json", {"items": [item("invented-a", 1), item("invented-b", 4)]})
    archive_groq(p07_cfg)
    write_json(p07_cfg.output_root / "judge/judge_E05.json", {"items": [item("invented-b", 1), item("invented-a", 4)]})
    result = compare_arms(p07_cfg)
    assert result["kendall_S"]["n"] == 2 and result["kendall_S"]["tau_b"] == -1


def test_failed_p07_episode_cache_is_available_for_judge_swap(p07_cfg, episode_factory, monkeypatch):
    from promo_finder import understanding
    episode = episode_factory(5, [(0, 20000)])
    key = "invented-cache"
    candidate = {"promo_id": key, "episode": 5, "line_ids": [episode.lines[0].id], "reference": True}
    runs = [successful()]
    old = {"promo_id": key, "candidate": candidate, "reference": True, "runs": runs, "aggregate": judging.aggregate(runs)}
    p07_cfg.models["groq_qwen"] = p07_cfg.models["fake_b"].model_copy(update={"model": "qwen/qwen3.8-27b"})
    write_json(p07_cfg.root / "outputs/judge/judge_E05.json", {"items": [old]})
    row = {"purpose": f"p05.cold_judge.{key}.run1", "model_key": "groq_qwen", "cache_key": "c" * 64,
           "response_mode": "json_object", "input_tokens": 30, "cached": False, "error": None}
    path = p07_cfg.output_root / "logs/llm_calls.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    write_json(p07_cfg.output_root / "judge/.llm_cache" / ("c" * 64 + ".json"),
               {"data": cold_answer(answer="no"), "model_string": "qwen/qwen3.8-27b", "response_mode": "json_object"})
    archive_groq(p07_cfg)
    write_json(p07_cfg.output_root / "judge/judge_E05.json", {"items": [old]})
    monkeypatch.setattr(understanding, "load_requested", lambda *a: [episode])
    result = compare_arms(p07_cfg)
    assert result["groq_source_by_item"][key] == "p07_cache"
    assert result["questions"]["hook_now"]["agreement"] == 0
