"""Extrapolate pilot metadata only; never load full-run episode content."""

from __future__ import annotations

import math

from .budget import check
from .config import model_quota
from .understanding_common import UnderstandingError


def estimate_50(cfg, pilot_manifest, build_summary):
    episodes = pilot_manifest["episodes"]
    if not episodes or pilot_manifest.get("status") != "complete":
        raise UnderstandingError("complete pilot accounting required")
    n = len(episodes)
    eligible_pilot = sum(ep < cfg.spoiler.late_series_start for ep in episodes)
    eligible_full = min(50, max(0, cfg.spoiler.late_series_start - 1))
    if not eligible_pilot:
        raise UnderstandingError("pilot has no builder-eligible episodes")
    chunks_full = math.ceil(50 / cfg.understanding.character_chunk_episodes)
    chunks_pilot = pilot_manifest["plan"]["parts"]["characters"]["calls"]
    observed = pilot_manifest["llm"]["parts"]
    estimates = {}
    for label, row in observed.items():
        name, provider = label.split(":", 1)
        episode_factor = eligible_full / eligible_pilot if name in {"answer_key", "cold_judge", "fidelity"} else 50 / n
        input_factor = episode_factor
        output_factor = chunks_full / chunks_pilot if name == "characters" else 1 if name == "header" else episode_factor
        call_factor = output_factor if name in {"characters", "header"} else episode_factor
        model_key = cfg.active.judge if name in {"cold_judge", "fidelity"} else cfg.active.picker
        price = cfg.pricing.get(model_key)
        inputs = math.ceil(row["input_tokens"] * input_factor)
        outputs = math.ceil(row["output_tokens"] * output_factor)
        estimates[label] = {"calls": math.ceil(row["calls"] * call_factor),
                            "http_requests": math.ceil(row["http_requests"] * call_factor),
                            "input_tokens": inputs, "output_tokens": outputs,
                            "usd": (inputs * price.input_per_million_usd + outputs * price.output_per_million_usd) / 1e6 if price else None if provider == "azure_foundry" else 0.0,
                            "model_key": model_key, "model": cfg.models[model_key].model,
                            "request_elapsed_s": row["request_elapsed_s"] * call_factor,
                            "input_scale": input_factor, "output_scale": output_factor, "call_scale": call_factor}
    groq = [r for name, r in estimates.items() if name.endswith(":groq")]
    calls = sum(r["calls"] for r in groq)
    is_foundry = cfg.models[cfg.active.judge].provider == "azure_foundry"
    if is_foundry and any(label.endswith(":groq") for label in estimates):
        raise UnderstandingError("pilot judge provider does not match official Foundry judge")
    guard = {"status": "not_applicable", "remaining_requests": None,
             "reason": "Foundry deployment quotas are per minute"} if is_foundry else check(cfg, calls)
    remaining = guard["remaining_requests"]
    full_budget = math.ceil(calls * cfg.rate_limit.groq.daily_safety_factor)
    measured_fits = None if is_foundry else guard["status"] == "passed" if guard["status"] not in {"missing", "stale"} else None
    split = []
    if measured_fits is not True and not is_foundry:
        for start, end in ((1, 25), (26, 50)):
            eligible = sum(ep < cfg.spoiler.late_series_start for ep in range(start, end + 1))
            day_calls = math.ceil(calls * eligible / eligible_full) if eligible_full else 0
            required = math.ceil(day_calls * cfg.rate_limit.groq.daily_safety_factor)
            split.append({"episode_range": [start, end], "eligible_builder_episodes": eligible,
                          "groq_calls": day_calls, "required_remaining_requests": required,
                          "fits_observed_remaining": required <= remaining if remaining is not None else None,
                          "fresh_daily_ping_required": True})
    per_ep_kept = build_summary["kept"] / eligible_pilot
    foundry = [r for name, r in estimates.items() if name.endswith(":azure_foundry")]
    foundry_estimate = None
    if foundry:
        quota = model_quota(cfg, cfg.active.judge)
        tokens = sum(r["input_tokens"] + r["output_tokens"] for r in foundry)
        requests = sum(r["http_requests"] for r in foundry)
        known_prices = all(r["usd"] is not None for r in foundry)
        foundry_estimate = {"model_key": cfg.active.judge, "deployment": cfg.models[cfg.active.judge].model,
                           "calls": sum(r["calls"] for r in foundry), "http_requests": requests,
                           "tokens": tokens, "usd": sum(r["usd"] for r in foundry) if known_prices else None,
                           "quota": quota,
                           "scaled_measured_elapsed_s": sum(r["request_elapsed_s"] for r in foundry),
                           "quota_throughput_time_s": max(tokens / quota["effective_tpm"] * 60,
                                                         requests / quota["effective_rpm"] * 60)}
    return {"estimate_only": True, "episodes": 50, "source_run": pilot_manifest["run"],
            "pilot_episodes": n, "character_chunks": chunks_full, "builder_eligible_episodes": eligible_full,
            "builder_kept_estimate": per_ep_kept * eligible_full, "parts": estimates,
            "azure_usd": sum(r["usd"] for name, r in estimates.items() if name.endswith(":azure")),
            "groq_calls": calls, "groq_http_requests": sum(r["http_requests"] for r in groq),
            "groq_time_s": sum(r["request_elapsed_s"] for r in groq),
            "azure_foundry": foundry_estimate,
            "required_remaining_requests": full_budget, "daily_guard": guard, "fits_one_day": measured_fits,
            "two_day_split_if_needed": split,
            "basis": "pilot measured charged usage and retries; input per episode; character output per chunk; header output once; builder/judge eligible episodes only",
            "limitations": ["five-episode sample", "content density and retry rates can change", "cache-hit billing is observed, not a guarantee",
                            "Groq-only daily checks; Foundry uses rolling per-deployment TPM and RPM"]}
