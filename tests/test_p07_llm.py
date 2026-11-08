from __future__ import annotations

import copy
import json

import openai
import pytest

from promo_finder import cli, judging
from promo_finder.llm import SchemaError, estimate_tokens, json_messages, to_strict
from test_judging import cold_answer, successful
from test_llm import MSGS, SCHEMA, cfg, http_error, make_client, resp


@pytest.mark.parametrize("mutation", ["json", "type", "enum", "missing", "extra", "evidence", "rating"])
def test_json_object_validates_and_retries_at_point_three(cfg, episode_factory, mutation):
    from promo_finder.judge_prompts import QUESTIONS, cold_request
    episode = episode_factory(5, [(0, 20000)])
    messages, schema, _ = cold_request(episode.lines, list(QUESTIONS))
    invalid = cold_answer()
    if mutation == "type": invalid["hook_now"] = 1
    elif mutation == "enum": invalid["hook_now"]["answer"] = "invalid"
    elif mutation == "missing": invalid.pop("standalone")
    elif mutation == "extra": invalid["additional"] = 0
    elif mutation == "evidence": invalid["hook_now"]["evidence"] = "E05-L001"
    elif mutation == "rating": invalid["hook_rating"] = 3
    cfg.models["fake_b"].structured_output = "json_object"
    client, provider, _, _ = make_client(cfg, [resp("invalid" if mutation == "json" else json.dumps(invalid)), resp(json.dumps(cold_answer()))])
    result = client.call("fake_b", messages, schema, purpose="p05.cold_judge.invented.run1", temperature=.7, retry_temperature=.3)
    assert result.validation_retry_used and result.final_temperature == .3
    assert [call["temperature"] for call in provider.calls] == [.7, .3]
    assert all(call["response_format"] == {"type": "json_object"} for call in provider.calls)
    system = provider.calls[0]["messages"][0]["content"]
    prefix, rest = system.split("Return only JSON matching this schema: ", 1)
    sent_schema, _ = json.JSONDecoder().raw_decode(rest)
    assert sent_schema == to_strict(schema)
    assert rest.index('"additionalProperties":false') < rest.index("Questions:")
    assert len({r["logical_call_id"] for r in client.records}) == 1
    assert sum(r.get("event") == "response_retry" for r in client.records) == 1
    again = client.call("fake_b", messages, schema, purpose="cached", temperature=.7, retry_temperature=.3)
    assert again.cached and again.validation_retry_used and again.final_temperature == .3


def test_json_object_invalid_twice_is_terminal(cfg):
    cfg.models["fake_b"].structured_output = "json_object"
    client, provider, _, _ = make_client(cfg, [resp("invalid"), resp("invalid")])
    with pytest.raises(SchemaError):
        client.call("fake_b", MSGS, SCHEMA, purpose="judge", temperature=.7, retry_temperature=.3)
    assert len(provider.calls) == 2
    assert not list(client.cache_dir.glob("*.json"))


@pytest.mark.parametrize("status", [429, 503])
def test_json_object_preserves_transport_backoff(cfg, status):
    cfg.models["fake_b"].structured_output = "json_object"
    error = http_error(openai.RateLimitError if status == 429 else openai.InternalServerError, status)
    client, provider, clock, _ = make_client(cfg, [error, resp('{"ok": true}')])
    result = client.call("fake_b", MSGS, SCHEMA, purpose="judge", temperature=.7, retry_temperature=.3)
    assert clock.sleeps == [1] and len(provider.calls) == 2
    assert not result.validation_retry_used


def test_mode_changes_cache_but_azure_strict_identity_stays(cfg):
    client, provider, _, _ = make_client(cfg, [resp('{"ok": true}'), resp('{"ok": true}')])
    old = client.call("fake_b", MSGS, SCHEMA, purpose="old")
    cfg.models["fake_b"].structured_output = "json_object"
    changed = client.call("fake_b", MSGS, SCHEMA, purpose="new")
    assert old.cache_key != changed.cache_key


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_is_invalid(cfg, value):
    client, _, _, _ = make_client(cfg, [resp('{"ok": '+value+'}'), resp('{"ok": '+value+'}')])
    with pytest.raises(SchemaError):
        client.call("fake_b", MSGS, SCHEMA, purpose="invalid")


def test_retry_diagnostic_does_not_change_official_aggregate():
    first, second, third = successful(), successful(), successful()
    third["answers"]["hook_now"]["answer"] = "no"
    third["metadata"] = {"validation_retry_used": True, "final_temperature": .3}
    item = {"runs": [first, second, third]}
    item["aggregate"] = judging.aggregate(item["runs"], 3)
    original = copy.deepcopy(item)
    diagnostic = judging.retry_diagnostics([item])
    assert diagnostic["hook_now"]["final_samples_from_0_3_retry"] == 1
    assert diagnostic["hook_now"]["successful_final_samples"] == 3
    assert diagnostic["hook_now"]["excluding_retried_samples"] == {"flipped_items": 0, "measured_items": 1, "flip_rate": 0}
    assert item == original and item["aggregate"]["per_question_disagreement"]["hook_now"] == 1


def test_retry_exclusion_requires_two_clean_successes():
    a, b, c = successful(), successful(), successful()
    for row in (b, c): row["metadata"] = {"validation_retry_used": True, "final_temperature": .3}
    result = judging.retry_diagnostics([{"runs": [a, b, c]}])
    assert all(q["excluding_retried_samples"]["measured_items"] == 0 for q in result.values())


@pytest.mark.parametrize("targets,calls,code", [("featherless_llama", 1, 0), ("groq_qwen", 1, 0), ("featherless_llama,groq_qwen", 2, 0), ("invalid", 0, 1), ("groq_qwen,groq_qwen", 0, 1)])
def test_ping_target_selection_without_secrets(cfg, monkeypatch, capsys, targets, calls, code):
    for key in ("groq_qwen", "featherless_llama"):
        cfg.models[key] = cfg.models["fake_b"].model_copy()
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(cli, "load_secrets", lambda *a: pytest.fail("secrets"))
    assert cli.main(["ping", "--models", targets, "--dry-run"]) == code
    if not code: assert json.loads(capsys.readouterr().out)["calls"] == calls


def test_offline_token_estimate_never_initializes_encoding(monkeypatch):
    from promo_finder import llm
    import tiktoken
    monkeypatch.setattr(llm, "_ENC", None)
    monkeypatch.setattr(llm, "_ENC_FAILED", False)
    monkeypatch.setattr(tiktoken, "get_encoding", lambda *a: pytest.fail("tokenizer download"))
    assert estimate_tokens("invented") > 0
