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


def test_call_log_has_hash_not_prompt_or_key(cfg):
    c, _, _, _ = make_client(cfg, [resp('{"ok": true}')])
    c.call("fake_a", MSGS, SCHEMA, purpose="unit")
    c.call("fake_a", MSGS, SCHEMA, purpose="unit")
    raw = (cfg.root / "outputs" / "logs" / "llm_calls.jsonl").read_text(encoding="utf-8")
    assert "invented prompt text" not in raw and "fake-key-value-not-real" not in raw
    recs = read_log(cfg)
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
