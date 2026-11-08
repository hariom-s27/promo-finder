"""Fail-closed Groq daily-request guard; metadata only, no credentials."""

from __future__ import annotations

import datetime as dt
import json
import math

from .understanding_common import UnderstandingError, write_json

# A recent observation is required even if the provider's daily reset is later.
MAX_AGE_S = 300


class DailyBudgetRefused(UnderstandingError):
    code = "GROQ_DAILY_BUDGET_REFUSED"


def state_path(cfg):
    return cfg.root / ".cache/tmp/groq_daily_budget.json"


def observe(cfg, headers, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    normalized = {str(k).lower(): str(v) for k, v in headers.items()}
    raw = normalized.get("x-ratelimit-remaining-requests")
    # A response without the required header invalidates a previous observation.
    try:
        remaining = int(raw)
        if remaining < 0:
            remaining = None
    except (TypeError, ValueError):
        remaining = None
    value = {"observed_at": now.isoformat(), "remaining_requests": remaining,
             "source": "x-ratelimit-remaining-requests"}
    write_json(state_path(cfg), value)
    write_json(cfg.output_root / "judge/groq_rate_limit.json", value)
    return value


def check(cfg, planned_calls, *, now=None, refuse=False):
    now = now or dt.datetime.now(dt.timezone.utc)
    required = math.ceil(planned_calls * cfg.rate_limit.groq.daily_safety_factor)
    value = {}
    try:
        value = json.loads(state_path(cfg).read_text(encoding="utf-8"))
        age = (now - dt.datetime.fromisoformat(value["observed_at"])).total_seconds()
    except (OSError, ValueError, KeyError, TypeError):
        age = None
    remaining = value.get("remaining_requests")
    fresh = age is not None and 0 <= age <= MAX_AGE_S
    known = type(remaining) is int and remaining >= 0
    status = "passed" if planned_calls == 0 else "missing" if not known else "stale" if not fresh else "insufficient" if required > remaining else "passed"
    result = {"status": status, "planned_groq_calls": planned_calls, "safety_factor": cfg.rate_limit.groq.daily_safety_factor,
              "required_remaining_requests": required, "remaining_requests": remaining if known else None,
              "observation_age_s": age, "maximum_age_s": MAX_AGE_S, "observed_at": value.get("observed_at")}
    if refuse and status != "passed":
        exc = DailyBudgetRefused("fresh Groq ping and sufficient daily requests required")
        exc.summary = result
        raise exc
    return result
