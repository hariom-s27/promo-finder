"""D79 error-metadata tests; entirely fake responses and no network."""
import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from promo_finder.llm import ProviderError
from promo_finder.provider_protocol import failed_request_metadata
from test_p07a import foundry_cfg, no_network, call, error
from test_llm import cfg, make_client


@pytest.mark.parametrize("wrapper", [False, True])
@pytest.mark.parametrize("inner_name", ["innererror", "innerError", "inner_error"])
def test_whitelisted_error_codes_and_filter_flags(wrapper, inner_name):
    detail = {"code": "Bad Request", "message": "invented-sensitive-message",
              inner_name: {"code": "ResponsibleAIPolicyViolation", "message": "invented-sensitive-inner",
                           "content_filter_result": {
                               "sexual": {"filtered": True, "severity": "high", "message": "invented-sensitive-category"},
                               "violence": {"filtered": False, "severity": "safe", "score": .1},
                               "jailbreak": {"detected": False, "filtered": False},
                               "unknown_category": {"filtered": True, "message": "invented-sensitive-unknown"}}}}
    body = {"error": detail} if wrapper else detail
    failure = error(400)
    failure.body = body
    metadata = failed_request_metadata(failure)
    assert metadata == {"http_status_code": 400, "provider_error_code": "Bad Request",
                        "provider_innererror_code": "ResponsibleAIPolicyViolation",
                        "content_filter_categories": {"sexual": {"filtered": True, "severity": "high"},
                                                       "violence": {"filtered": False, "severity": "safe"},
                                                       "jailbreak": {"detected": False, "filtered": False}}}
    assert "invented-sensitive" not in json.dumps(metadata) and '"score"' not in json.dumps(metadata)


def test_error_metadata_can_use_raw_response_without_sdk_body():
    failure = error(400)
    failure.response = httpx.Response(400, json={"error": {"code": "content_filter", "innererror": {
        "code": "PolicyViolation", "content_filter_results": {"self_harm": {"filtered": True, "severity": "medium"}}}}},
        request=httpx.Request("POST", "https://invented.invalid"))
    metadata = failed_request_metadata(failure)
    assert metadata["provider_error_code"] == "content_filter"
    assert metadata["provider_innererror_code"] == "PolicyViolation"
    assert metadata["content_filter_categories"] == {"self_harm": {"filtered": True, "severity": "medium"}}


@pytest.mark.parametrize("body", [None, "invented-sensitive-body", {"message": "invented-sensitive-message"},
                                  {"error": {"code": ["invalid"], "innererror": "invalid",
                                             "content_filter_results": {"sexual": {"filtered": "yes", "severity": []}}}}])
def test_missing_or_malformed_error_metadata_is_safe(body):
    failure = error(400)
    failure.body = body
    metadata = failed_request_metadata(failure)
    assert metadata == {"http_status_code": 400, "provider_error_code": None,
                        "provider_innererror_code": None, "content_filter_categories": {}}


def test_network_failure_has_explicit_absent_provider_metadata():
    assert failed_request_metadata(RuntimeError("invented-sensitive-error")) == {
        "http_status_code": None, "provider_error_code": None,
        "provider_innererror_code": None, "content_filter_categories": {}}


def test_every_failed_request_logs_only_whitelisted_error_metadata(foundry_cfg):
    failure = error(400)
    failure.body = {"error": {"code": "content_filter", "message": "invented-sensitive-body",
                              "innererror": {"code": "PolicyViolation", "content_filter_result": {
                                  "hate": {"filtered": False, "severity": "safe"},
                                  "sexual": {"filtered": True, "severity": "high"}}}}}
    client, provider, _, _ = make_client(foundry_cfg, [failure])
    with pytest.raises(ProviderError):
        call(client)
    rows = [r for r in client.records if r.get("event") == "http_attempt_failed"]
    assert len(rows) == len(provider.calls) == 1
    assert rows[0]["provider_innererror_code"] == "PolicyViolation"
    assert rows[0]["content_filter_categories"]["sexual"]["filtered"] is True
    assert "invented-sensitive-body" not in client.log_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("yes,no,unmeasured,expected", [(41, 4, 0, "REVERT"), (40, 5, 0, "ADOPT"),
    (5, 40, 0, "ADOPT"), (4, 41, 0, "REVERT"), (45, 0, 0, "REVERT"), (40, 0, 5, "REVERT")])
def test_d80_predeclared_minority_rule(yes, no, unmeasured, expected):
    from promo_finder.judge_experiments import d80_decision
    items = [{"aggregate": {"answers": {"standalone": value}}} for value in ["yes"]*yes + ["no"]*no + [None]*unmeasured]
    result = d80_decision(items)
    assert result["decision"] == expected and result["minority_items"] == min(yes, no)
    assert result["expected_items"] == 45 and result["required_minority_items"] == 5


def test_d80_refuses_a_changed_denominator():
    from promo_finder.judge_experiments import d80_decision
    with pytest.raises(ValueError, match="45"):
        d80_decision([])


def test_d80_changes_only_standalone_system_line_not_clip_or_schema(episode_factory, monkeypatch):
    from promo_finder import judge_prompts as prompts
    expected = 'someone who has never seen this show can follow the basic situation from this clip alone — who is in conflict and roughly what is at stake. Backstory and names are not required; answer "no" only if the clip is confusing without earlier episodes.'
    assert prompts.QUESTIONS["standalone"] == expected
    episode = episode_factory(5, [(0, 20000)])
    new_messages, new_schema, new_mapping = prompts.cold_request(episode.lines, list(prompts.QUESTIONS))
    monkeypatch.setitem(prompts.QUESTIONS, "standalone", "a stranger can tell who is in conflict and what is at stake.")
    old_messages, old_schema, old_mapping = prompts.cold_request(episode.lines, list(prompts.QUESTIONS))
    assert new_schema == old_schema and new_mapping == old_mapping
    assert new_messages[1:] == old_messages[1:]
    old_lines, new_lines = old_messages[0]["content"].splitlines(), new_messages[0]["content"].splitlines()
    assert [(a, b) for a, b in zip(old_lines, new_lines) if a != b] == [
        ('standalone: a stranger can tell who is in conflict and what is at stake.', 'standalone: ' + expected)]
