from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from promo_finder.budget import MAX_AGE_S, DailyBudgetRefused, check, observe
from test_llm import MSGS, SCHEMA, cfg, make_client, resp

NOW = dt.datetime(2026, 11, 8, 8, tzinfo=dt.timezone.utc)


@pytest.mark.parametrize("remaining,passed", [(158, False), (159, True), (160, True)])
def test_daily_guard_ceiling(cfg, remaining, passed):
    observe(cfg, {"x-ratelimit-remaining-requests": str(remaining)}, NOW)
    if passed:
        result = check(cfg, 132, now=NOW, refuse=True)
        assert result["required_remaining_requests"] == 159
    else:
        with pytest.raises(DailyBudgetRefused) as caught:
            check(cfg, 132, now=NOW, refuse=True)
        assert caught.value.summary["status"] == "insufficient"


@pytest.mark.parametrize("headers", [{}, {"x-ratelimit-remaining-requests": "invalid"}, {"x-ratelimit-remaining-requests": "-1"}])
def test_missing_header_invalidates_previous_observation(cfg, headers):
    observe(cfg, {"x-ratelimit-remaining-requests": "1000"}, NOW)
    observe(cfg, headers, NOW)
    with pytest.raises(DailyBudgetRefused): check(cfg, 1, now=NOW, refuse=True)


def test_missing_stale_and_future_fail_closed(cfg):
    assert check(cfg, 1, now=NOW)["status"] == "missing"
    observe(cfg, {"x-ratelimit-remaining-requests": "1000"}, NOW)
    assert check(cfg, 1, now=NOW + dt.timedelta(seconds=MAX_AGE_S+1))["status"] == "stale"
    assert check(cfg, 1, now=NOW - dt.timedelta(seconds=1))["status"] == "stale"
    assert check(cfg, 0, now=NOW + dt.timedelta(days=1), refuse=True)["status"] == "passed"


def test_raw_response_captures_only_budget_metadata(cfg):
    cfg.providers["groq"] = cfg.providers["fakeprov"].model_copy()
    cfg.models["fake_b"].provider = "groq"
    client, fake, _, _ = make_client(cfg, [])
    raw = SimpleNamespace(headers={"x-ratelimit-remaining-requests": "900", "authorization": "invented-sensitive-value"},
                          parse=lambda: resp('{"ok": true}'))
    fake.chat.completions.with_raw_response = SimpleNamespace(create=lambda **kw: raw)
    client.call("fake_b", MSGS, SCHEMA, purpose="ping")
    assert check(cfg, 1)["remaining_requests"] == 900
    assert "invented-sensitive-value" not in (cfg.output_root / "judge/groq_rate_limit.json").read_text()
