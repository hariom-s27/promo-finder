"""LLM wrapper tests with a fake provider. No network."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from promo_finder.config import ConfigError, load_config, load_secrets
from promo_finder.llm import (BudgetExceeded, EmptyOrTruncated, LLMClient, LLMError, RateLimiter,
                              SchemaError, schema_errors, to_strict)

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
MSGS = [{"role": "user", "content": "invented prompt text 12345"}]


def resp(content, finish="stop", model="fake-model-2026", pt=11, ct=3):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)],
        model=model, usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct))


class FakeProvider:
    """Stands in for openai.OpenAI: .chat.completions.create(**kw) pops scripted replies."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def http_error(cls, status, headers=None):
    req = httpx.Request("POST", "https://fake.invalid/v1/chat/completions")
    return cls("fake error", response=httpx.Response(status, headers=headers or {}, request=req), body=None)


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


@pytest.fixture
def cfg(write_config, monkeypatch):
    monkeypatch.setenv("FAKE_API_KEY", "fake-key-value-not-real")
    monkeypatch.setenv("FAKE_AZURE_KEY", "fake-azure-key-not-real")
    monkeypatch.setenv("FAKE_AZURE_ENDPOINT", "https://fake-azure.invalid/")
    return load_config(write_config())


def make_client(cfg, replies, **kw):
    fake = FakeProvider(replies)
    clock = FakeClock()
    modes = []

    def factory(provider, pcfg, mode):
        modes.append(mode)
        return fake

    c = LLMClient(cfg, client_factory=factory, clock=clock, sleep=clock.sleep,
                  token_estimator=lambda t: len(t) // 4, **kw)
    return c, fake, clock, modes


def read_log(cfg):
    p = cfg.root / "outputs" / "logs" / "llm_calls.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]


# ------------------------------------------------------------ cache
def test_cache_miss_then_hit(cfg):
    c, fake, _, _ = make_client(cfg, [resp('{"ok": true}'), resp('{"ok": true}')])
    r1 = c.call("fake_a", MSGS, SCHEMA, purpose="t")
    assert r1.data == {"ok": True} and not r1.cached and r1.model_string == "fake-model-2026"
    assert r1.usage.input_tokens == 11 and r1.usage.output_tokens == 3
    r2 = c.call("fake_a", MSGS, SCHEMA, purpose="t")
    assert r2.cached and r2.data == {"ok": True} and r2.cache_key == r1.cache_key
    assert len(fake.calls) == 1
    assert (cfg.root / ".cache" / "llm" / f"{r1.cache_key}.json").is_file()
    r3 = c.call("fake_a", MSGS, SCHEMA, purpose="t", no_cache=True)
    assert not r3.cached and len(fake.calls) == 2


def test_cache_key_changes_with_input(cfg):
    c, fake, _, _ = make_client(cfg, [resp('{"ok": true}'), resp('{"ok": false}')])
    a = c.call("fake_a", MSGS, SCHEMA, purpose="t")
    b = c.call("fake_a", [{"role": "user", "content": "different"}], SCHEMA, purpose="t")
    assert a.cache_key != b.cache_key and len(fake.calls) == 2


# ------------------------------------------------------------ request shape
def test_request_shape_no_temperature_and_extra_body(cfg):
    c, fake, _, _ = make_client(cfg, [resp('{"ok": true}')])
    c.call("fake_a", MSGS, SCHEMA, purpose="t")
    kw = fake.calls[0]
    assert "temperature" not in kw and "temperature" not in kw.get("extra_body", {})
    assert kw["reasoning_effort"] == "minimal" and kw["max_completion_tokens"] == 1000
    assert kw["extra_body"] == {"include_reasoning": False}
    rf = kw["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["additionalProperties"] is False
    assert rf["json_schema"]["schema"]["required"] == ["ok"]


# ------------------------------------------------------------ empty / truncated
def test_empty_reply_retries_with_double_tokens(cfg):
    c, fake, _, _ = make_client(cfg, [resp(""), resp('{"ok": true}')])
    r = c.call("fake_a", MSGS, SCHEMA, purpose="t")
    assert r.data == {"ok": True}
    assert [k["max_completion_tokens"] for k in fake.calls] == [1000, 2000]


def test_truncated_twice_raises_and_caps_tokens(cfg):
    c, fake, _, _ = make_client(cfg, [resp('{"ok": tr', finish="length"), resp("", finish="length")])
    with pytest.raises(EmptyOrTruncated):
        c.call("fake_b", MSGS, SCHEMA, purpose="t")
    assert [k["max_completion_tokens"] for k in fake.calls] == [10000, 16000]
    assert not list((cfg.root / ".cache" / "llm").glob("*.json"))  # failures are never cached


# ------------------------------------------------------------ schema
def test_schema_failure_retry_then_raise(cfg):
    c, fake, _, _ = make_client(cfg, [resp('{"ok": "yes"}'), resp("not json at all")])
    with pytest.raises(SchemaError):
        c.call("fake_a", MSGS, SCHEMA, purpose="t")
    assert len(fake.calls) == 2


def test_schema_failure_then_success(cfg):
    c, fake, _, _ = make_client(cfg, [resp('{"ok": true, "extra": 1}'), resp('{"ok": true}')])
    assert c.call("fake_a", MSGS, SCHEMA, purpose="t").data == {"ok": True}


def test_schema_validator_subset():
    s = to_strict({"type": "object", "properties": {
        "spans": {"type": "array", "minItems": 1, "items": {"type": "object", "properties": {
            "first": {"type": "string"}, "last": {"type": "string"}}}},
        "score": {"type": "integer", "minimum": 0, "maximum": 10},
        "kind": {"enum": ["a", "b"]}}})
    good = {"spans": [{"first": "E01-L001", "last": "E01-L002"}], "score": 3, "kind": "a"}
    assert schema_errors(good, s) == []
    assert schema_errors({**good, "score": True}, s)            # bool is not an integer
    assert schema_errors({**good, "spans": []}, s)
    assert schema_errors({**good, "kind": "z"}, s)
    assert schema_errors({"spans": [{"first": "x"}], "score": 1, "kind": "a"}, s)


# ------------------------------------------------------------ family check / config
def test_family_check_rejects_same_family(write_config):
    with pytest.raises(ConfigError, match="self-judging"):
        load_config(write_config(picker="fake_a", judge="fake_az"))


def test_family_check_accepts_different_family(write_config):
    assert load_config(write_config(picker="fake_a", judge="fake_b")).active.judge == "fake_b"


def test_active_tbd_rejected(write_config):
    with pytest.raises(ConfigError, match="TBD"):
        load_config(write_config(picker="fake_a", judge="fake_tbd"))


def test_tbd_model_skipped(cfg):
    assert "fake_tbd" not in cfg.usable_models()
    c, _, _, _ = make_client(cfg, [])
    with pytest.raises(LLMError):
        c.call("fake_tbd", MSGS, SCHEMA, purpose="t")


# ------------------------------------------------------------ limiter
def test_limiter_rpm():
    clk = FakeClock()
    lim = RateLimiter(rpm=2, clock=clk, sleep=clk.sleep)
    lim.acquire(1)
    clk.t += 10
    lim.acquire(1)
    assert lim.wait_time(1) == pytest.approx(50.0)   # oldest at t0 expires at t0+60, now t0+10
    lim.acquire(1)
    assert clk.sleeps == [pytest.approx(50.0)]


def test_limiter_tpm():
    clk = FakeClock()
    lim = RateLimiter(tpm=100, clock=clk, sleep=clk.sleep)
    lim.acquire(60)          # t=0
    clk.t += 10
    lim.acquire(30)          # t=10
    clk.t += 10              # now t=20; used 90
    assert lim.wait_time(10) == 0.0
    assert lim.wait_time(50) == pytest.approx(40.0)  # must wait for the 60-token entry (t=0) to expire
    assert lim.wait_time(80) == pytest.approx(50.0)  # must wait for both entries
    clk.t += 60
    assert lim.wait_time(100) == 0.0                 # window empty again


def test_limiter_settle_updates_tokens():
    clk = FakeClock()
    lim = RateLimiter(tpm=100, clock=clk, sleep=clk.sleep)
    e = lim.acquire(10)
    lim.settle(e, 95)
    assert lim.wait_time(10) == pytest.approx(60.0)


# ------------------------------------------------------------ pacing / backoff
def test_429_waits_for_retry_after(cfg):
    c, fake, clk, _ = make_client(cfg, [http_error(openai.RateLimitError, 429, {"retry-after": "7"}),
                                        resp('{"ok": true}')])
    assert c.call("fake_a", MSGS, SCHEMA, purpose="t").data == {"ok": True}
    assert clk.sleeps == [7.0]


def test_5xx_exponential_backoff_max_5(cfg):
    errs = [http_error(openai.InternalServerError, 500) for _ in range(5)]
    c, fake, clk, _ = make_client(cfg, errs)
    with pytest.raises(LLMError):
        c.call("fake_a", MSGS, SCHEMA, purpose="t")
    assert len(fake.calls) == 5
    assert clk.sleeps == [1.0, 2.0, 4.0, 8.0]


# ------------------------------------------------------------ azure fallback
def test_azure_falls_back_once(cfg):
    v1 = FakeProvider([http_error(openai.NotFoundError, 404)])
    fb = FakeProvider([resp('{"ok": true}', model="gpt-5-mini-2025-08-07"), resp('{"ok": true}')])
    modes = []

    def factory(provider, pcfg, mode):
        modes.append(mode)
        return {"v1": v1, "fallback": fb}[mode]

    c = LLMClient(cfg, client_factory=factory, token_estimator=lambda t: 1, sleep=lambda s: None)
    r = c.call("fake_az", MSGS, SCHEMA, purpose="t")
    assert r.api_path == "fallback" and r.model_string == "gpt-5-mini-2025-08-07"
    assert modes == ["v1", "fallback"]
    c.call("fake_az", [{"role": "user", "content": "second"}], SCHEMA, purpose="t")
    assert modes == ["v1", "fallback"] and len(fb.calls) == 2  # sticks with what worked
    events = [x.get("event", "") for x in read_log(cfg)]
    assert any("trying fallback" in e for e in events) and any("in use: fallback" in e for e in events)


def test_azure_v1_ok(cfg):
    c, fake, _, modes = make_client(cfg, [resp('{"ok": true}')])
    assert c.call("fake_az", MSGS, SCHEMA, purpose="t").api_path == "v1"
    assert modes == ["v1"]


# ------------------------------------------------------------ budget / dry run / log
def test_budget_stops_run(write_config, monkeypatch):
    monkeypatch.setenv("FAKE_API_KEY", "fake-key-value-not-real")
    cfg = load_config(write_config(max_calls=2))
    c, fake, _, _ = make_client(cfg, [resp('{"ok": true}')] * 5)
    c.call("fake_a", [{"role": "user", "content": "1"}], SCHEMA, purpose="t")
    c.call("fake_a", [{"role": "user", "content": "2"}], SCHEMA, purpose="t")
    c.call("fake_a", [{"role": "user", "content": "1"}], SCHEMA, purpose="t")  # cache hit: free
    with pytest.raises(BudgetExceeded):
        c.call("fake_a", [{"role": "user", "content": "3"}], SCHEMA, purpose="t")
    assert len(fake.calls) == 2


def test_dry_run_makes_no_calls(cfg):
    c, fake, _, _ = make_client(cfg, [], dry_run=True)
    r = c.call("fake_a", MSGS, SCHEMA, purpose="t")
    assert r.dry_run and r.usage.input_tokens > 0 and fake.calls == []


def test_transport_retries_count_toward_budget(write_config, monkeypatch):
    monkeypatch.setenv("FAKE_API_KEY", "fake-key-value-not-real")
    cfg = load_config(write_config(max_calls=2))
    c, fake, _, _ = make_client(cfg, [http_error(openai.RateLimitError, 429),
                                     http_error(openai.InternalServerError, 500), resp('{"ok": true}')])
    with pytest.raises(BudgetExceeded):
        c.call("fake_a", MSGS, SCHEMA, purpose="p02.characters.chunk_01")
    assert len(fake.calls) == c.calls_made == 2
    failed = [row for row in c.records if row.get("event") == "http_attempt_failed"]
    assert [row["request_number"] for row in failed] == [1, 2]
    assert all(row["purpose"] == "p02.characters.chunk_01" for row in failed)
    assert len([row for row in c.records if row.get("event") == "transport_retry"]) == 2
    assert all("fake-key-value-not-real" not in json.dumps(row) for row in c.records)


def test_successful_transport_retry_has_exact_physical_count(cfg):
    c, fake, _, _ = make_client(cfg, [http_error(openai.RateLimitError, 429), resp('{"ok": true}')])
    c.call("fake_a", MSGS, SCHEMA, purpose="p02.header")
    assert len(fake.calls) == c.calls_made == 2
    assert c.records[-1]["request_number"] == 2


def test_retry_summary_counts_transport_and_rejected_response_usage(cfg):
    from promo_finder.understanding import call_summary

    c, _, _, _ = make_client(cfg, [http_error(openai.RateLimitError, 429),
                                  resp('{"ok": "invalid"}'), resp('{"ok": true}')])
    c.call("fake_a", MSGS, SCHEMA, purpose="p02.header")
    part = call_summary(c, cfg)["parts"]["header"]
    assert part["calls"] == 1 and part["requests"] == 3 and part["retries"] == 2
    assert part["http_failures"] == 1 and part["response_failures"] == 1 and part["failed_calls"] == 0
    assert part["input_tokens"] == 22 and part["output_tokens"] == 6


def test_call_log_has_hash_not_prompt_or_key(cfg):
    c, _, _, _ = make_client(cfg, [resp('{"ok": true}')])
    c.call("fake_a", MSGS, SCHEMA, purpose="unit")
    c.call("fake_a", MSGS, SCHEMA, purpose="unit")
    raw = (cfg.root / "outputs" / "logs" / "llm_calls.jsonl").read_text(encoding="utf-8")
    assert "invented prompt text" not in raw and "fake-key-value-not-real" not in raw
    recs = [row for row in read_log(cfg) if row.get("event") != "http_attempt_started"]
    assert len(recs) == 2 and [r["cached"] for r in recs] == [False, True]
    for r in recs:
        for k in ("time", "purpose", "provider", "model_string", "prompt_sha256",
                  "input_tokens", "output_tokens", "latency_ms", "cached", "error"):
            assert k in r
        assert len(r["prompt_sha256"]) == 64


def test_error_message_scrubs_key(cfg):
    leak = http_error(openai.AuthenticationError, 401)
    leak.message = "Incorrect API key provided: fake-key-value-not-real"
    c, _, _, _ = make_client(cfg, [leak])
    with pytest.raises(LLMError) as ei:
        c.call("fake_a", MSGS, SCHEMA, purpose="t")
    assert "fake-key-value-not-real" not in str(ei.value)


# ------------------------------------------------------------ secrets
def test_missing_secrets_file_prints_names_only(write_config, monkeypatch, capsys, tmp_path):
    cfg = load_config(write_config())
    monkeypatch.setenv("KUKU_SECRETS_FILE", str(tmp_path / "absent.env"))
    for n in ("FAKE_API_KEY", "FAKE_AZURE_KEY", "FAKE_AZURE_ENDPOINT"):
        monkeypatch.delenv(n, raising=False)
    with pytest.raises(SystemExit):
        load_secrets(cfg)
    err = capsys.readouterr().err
    assert "FAKE_API_KEY" in err and "FAKE_AZURE_KEY" in err and "FAKE_AZURE_ENDPOINT" in err
    assert "=" not in err


def test_secrets_file_loaded_with_override(write_config, monkeypatch, tmp_path):
    cfg = load_config(write_config())
    f = tmp_path / "test-secrets.env"
    f.write_text("FAKE_API_KEY=from-file-value\n", encoding="utf-8")
    monkeypatch.setenv("KUKU_SECRETS_FILE", str(f))
    monkeypatch.setenv("FAKE_API_KEY", "old")
    assert load_secrets(cfg) == f
    import os
    assert os.environ["FAKE_API_KEY"] == "from-file-value"


def test_effort_override_changes_cache_key_and_preserves_default(cfg):
    c, fake, _, _ = make_client(cfg, [resp('{"ok": true}')] * 3)
    default = c.call("fake_a", MSGS, SCHEMA, purpose="t")
    low = c.call("fake_a", MSGS, SCHEMA, purpose="t", reasoning_effort="low")
    assert default.cache_key != low.cache_key
    assert c.call("fake_a", MSGS, SCHEMA, purpose="t", reasoning_effort="low").cached
    c.call("fake_a", MSGS, SCHEMA, purpose="t", no_cache=True)
    assert [row["reasoning_effort"] for row in fake.calls] == ["minimal", "low", "minimal"]
    assert cfg.models["fake_a"].params["reasoning_effort"] == "minimal"


def test_spacing_across_calls_and_retry(cfg):
    cfg.rate_limit.min_interval_s = 1.5
    c, fake, clock, _ = make_client(cfg, [http_error(openai.RateLimitError, 429, {"retry-after": "0.25"}),
                                         resp('{"ok": true}'), resp('{"ok": true}')])
    starts = []
    original = fake._create
    def timed(**kwargs):
        starts.append(clock())
        return original(**kwargs)
    fake.chat.completions.create = timed
    c.call("fake_a", MSGS, SCHEMA, purpose="t")
    c.call("fake_a", MSGS, SCHEMA, purpose="t", no_cache=True)
    assert starts == [1000, 1001.5, 1003]
    assert c.calls_made == 3
    assert sum(clock.sleeps) == pytest.approx(3)


@pytest.mark.parametrize("header,expected", [
    ({"retry-after": "60"}, 60), ({"retry-after": "60.01"}, 1),
    ({"retry-after": "0"}, 1), ({"retry-after": "-1"}, 1),
    ({"retry-after": "nan"}, 1), ({"retry-after": "inf"}, 1),
    ({"retry-after": "invalid"}, 1), ({}, 1),
    ({"retry-after-ms": "1500"}, 1.5), ({"retry-after-ms": "60000"}, 60),
    ({"retry-after-ms": "60001"}, 1), ({"retry-after-ms": "0"}, 1),
    ({"retry-after-ms": "2000", "retry-after": "9"}, 2),
])
def test_bounded_retry_after(cfg, header, expected):
    c, _, clock, _ = make_client(cfg, [http_error(openai.RateLimitError, 429, header), resp('{"ok": true}')])
    c.call("fake_a", MSGS, SCHEMA, purpose="t")
    assert clock.sleeps == [expected]
    assert c.calls_made == 2


def test_retry_after_config_bound_and_disable(cfg):
    cfg.rate_limit.max_retry_after_s = 3
    c, _, clock, _ = make_client(cfg, [http_error(openai.RateLimitError, 429, {"retry-after": "4"}), resp('{"ok": true}')])
    c.call("fake_a", MSGS, SCHEMA, purpose="t")
    assert clock.sleeps == [1]
    cfg.rate_limit.honour_retry_after = False
    c, _, clock, _ = make_client(cfg, [http_error(openai.RateLimitError, 429, {"retry-after": "2"}), resp('{"ok": true}')])
    c.call("fake_a", MSGS, SCHEMA, purpose="t", no_cache=True)
    assert clock.sleeps == [1]


@pytest.mark.parametrize("offset,expected", [(7, 7), (61, 1), (-2, 1)])
def test_retry_after_http_date(cfg, monkeypatch, offset, expected):
    from email.utils import formatdate
    monkeypatch.setattr("promo_finder.llm.time.time", lambda: 1700000000)
    c, _, clock, _ = make_client(cfg, [http_error(openai.RateLimitError, 429,
        {"Retry-After": formatdate(1700000000 + offset, usegmt=True)}), resp('{"ok": true}')])
    c.call("fake_a", MSGS, SCHEMA, purpose="t")
    assert clock.sleeps == [expected]


def test_spacing_shared_by_models_and_azure_paths(cfg):
    cfg.rate_limit.min_interval_s = 1.5
    clock = FakeClock()
    starts = []
    v1 = FakeProvider([http_error(openai.NotFoundError, 404)])
    fallback = FakeProvider([resp('{"ok": true}')])
    def factory(provider, pcfg, mode):
        fake = {"v1": v1, "fallback": fallback}[mode]
        original = fake.chat.completions.create
        def timed(**kw):
            starts.append(clock())
            return original(**kw)
        fake.chat.completions.create = timed
        return fake
    c = LLMClient(cfg, client_factory=factory, clock=clock, sleep=clock.sleep, token_estimator=lambda text: 1)
    c.call("fake_az", MSGS, SCHEMA, purpose="t")
    assert starts == [1000, 1001.5] and c.calls_made == 2
    c, _, clock, _ = make_client(cfg, [resp('{"ok": true}')] * 2)
    c.call("fake_a", MSGS, SCHEMA, purpose="t")
    c.call("fake_b", MSGS, SCHEMA, purpose="t")
    assert clock.sleeps == [1.5]


def test_provider_concurrency_is_bounded(cfg):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    cfg.rate_limit.max_concurrent = 1
    entered, release, second_started = threading.Event(), threading.Event(), threading.Event()
    lock = threading.Lock()
    active = maximum = 0
    def create(**kw):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        entered.set()
        assert release.wait(5)
        with lock:
            active -= 1
        return resp('{"ok": true}')
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    c = LLMClient(cfg, client_factory=lambda *args: fake, token_estimator=lambda text: 1)
    def second():
        second_started.set()
        return c.call("fake_a", [{"role": "user", "content": "invented second"}], SCHEMA, purpose="t")
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(c.call, "fake_a", MSGS, SCHEMA, purpose="t")
        assert entered.wait(5)
        other = executor.submit(second)
        assert second_started.wait(5)
        release.set()
        assert first.result().data == other.result().data == {"ok": True}
    assert maximum == 1 and c.calls_made == 2


@pytest.mark.parametrize("patch", [
    {"rate_limit": {"max_concurrent": 0}}, {"rate_limit": {"min_interval_s": -1}},
    {"rate_limit": {"max_retry_after_s": 61}}, {"spoiler": {"reveal_mode": "invalid"}},
    {"builder": {"max_per_episode": 0}}, {"builder": {"max_segments": 3}},
    {"builder": {"montage_first_min_s": 21, "montage_first_max_s": 20}},
    {"builder": {"penalties": {"montage": -1}}}, {"builder": {"recap_similarity": 1.1}},
])
def test_invalid_p03_config(write_config, patch):
    import yaml
    path = write_config()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw.update(patch)
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
