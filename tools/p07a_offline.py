"""P07a count-only evidence, archival and DEV preflight. No credentials or network."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter

from promo_finder.config import load_config
from promo_finder.judge_arms import archive_groq, compare_arms
from promo_finder.judging import dry_run
from promo_finder.run_context import fingerprints, for_run
from promo_finder.understanding import load_requested
from promo_finder.understanding_common import UnderstandingError, write_json


def diagnostic(cfg, utc_day):
    sources = {}
    for path in (cfg.root / "outputs/logs/llm_calls.jsonl", cfg.root / "outputs/runs/dev/logs/llm_calls.jsonl"):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows = [r for r in rows if r.get("provider") == "groq" and
                dt.datetime.fromisoformat(r["time"]).astimezone(dt.timezone.utc).date().isoformat() == utc_day]
        charged = [r for r in rows if not r.get("cached") and not r.get("dry_run") and type(r.get("input_tokens")) is int]
        errors = [r for r in rows if r.get("event") == "http_attempt_failed"]
        last_ok = max((r["time"] for r in charged if not r.get("error")), default=None)
        streak = [r for r in errors if last_ok and r["time"] > last_ok]
        first_429 = next((r for r in errors if r.get("error") == "HTTP_429"), None)
        sources[path.relative_to(cfg.root).as_posix()] = {
            "input_tokens": sum(r["input_tokens"] for r in charged),
            "output_tokens": sum(r.get("output_tokens", 0) or 0 for r in charged),
            "http_errors": dict(Counter(r["error"] for r in errors)),
            "first_429_utc": first_429["time"] if first_429 else None,
            "last_success_utc": last_ok,
            "terminal_streak": {"start_utc": streak[0]["time"] if streak else None,
                                "end_utc": streak[-1]["time"] if streak else None,
                                "http_errors": dict(Counter(r["error"] for r in streak)),
                                "duration_s": (dt.datetime.fromisoformat(streak[-1]["time"]) - dt.datetime.fromisoformat(streak[0]["time"])).total_seconds() if streak else 0}}
    return {"utc_day": utc_day, "sources": sources,
            "logged_groq_tokens": sum(r["input_tokens"] + r["output_tokens"] for r in sources.values()),
            "tpd_conclusion": "INFERENCE: failed P05 HTTP 400 requests may have consumed unlogged tokens; TPD exhaustion is plausible but unconfirmed",
            "groq_guard_change": "none; deferred to P09"}


def dev_dry_run(cfg):
    from promo_finder.cli import PING_SCHEMA, targeted_ping_budget
    from promo_finder.llm import _prompt_text, estimate_tokens, json_messages, to_strict
    archive = archive_groq(cfg)
    frozen = fingerprints(cfg, required=True)
    plan = dry_run(cfg, load_requested(cfg, [5, 6, 7, 8, 19, 20, 21, 22]))
    if (plan["current_items"], plan["reference_items"], plan["answer_key_cache"]["valid_cache_hits"]) != (39, 6, 8):
        raise UnderstandingError("DEV items, references or required cache hits changed; stop")
    plan["max_calls_per_run"] = plan["recommended_budget"]
    plan["budget_covers_plan"] = True
    model_key = cfg.active.judge
    ping_in = estimate_tokens(_prompt_text(json_messages(
        [{"role": "user", "content": "Return only JSON with ok set to true."}], to_strict(PING_SCHEMA)), {}))
    price = cfg.pricing.get(model_key)
    ping = {"model_key": model_key, "calls": 1, "estimated_input_tokens": ping_in,
            "output_budget_tokens": 800, "temperature": .7, "initial_response_format": {"type": "json_object"},
            "max_calls_per_run": targeted_ping_budget(cfg, [model_key]),
            "estimated_usd": (ping_in * price.input_per_million_usd + 800 * price.output_per_million_usd) / 1e6 if price else None}
    return {"status": "STOP_BEFORE_LIVE", "plan": plan, "ping": ping, "archive": archive, **frozen,
            "expected_time": {"judge_pacing_s": plan["estimated_judge_pacing_s"],
                              "basis": "zero-latency reservation schedule at both effective quotas; add response latency, header delays, negotiation and retries",
                              "total_wall_time_s": None},
            "next_live_commands": ["ping --models azure_llama --run dev --no-cache",
                                   "judge --eps 5-8,19-22 --run dev", "rank --eps 5-8,19-22 --run dev"],
            "pending": ["APPROVED before live ping", "official ping must succeed; never switch automatically", "at least 38/39 scored before pilot", "pilot dry run then STOP"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("archive-groq", "diagnose", "dev-dry-run", "compare-judges"))
    ap.add_argument("--utc-day", default="2026-11-08")
    args = ap.parse_args(argv)
    cfg = for_run(load_config(), "dev")
    if args.action == "archive-groq":
        result = archive_groq(cfg)
    elif args.action == "diagnose":
        result = diagnostic(cfg, args.utc_day)
        write_json(cfg.output_root / "judge/p07a_groq_diagnostic.json", result)
    elif args.action == "dev-dry-run":
        result = dev_dry_run(cfg)
        write_json(cfg.output_root / "judge/p07a_dev_dry_run.json", result)
    else:
        result = compare_arms(cfg)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
