"""One-command pipeline and an offline dependency-aware upper-bound plan."""

from __future__ import annotations

import json
import math
import sys
import time

from . import baseline, builder, finding, header, judge_prompts, judging, moments, ranking, understanding
from .accounting import summarize
from .budget import check as daily_check
from .checker import build_index, check_promo
from .characters import chunks
from .config import model_quota
from .labelling import parse_eps
from .llm import LLMClient, RateLimiter, _prompt_text, estimate_tokens, json_messages, to_strict
from .run_context import fingerprints, manifest
from .understanding_common import UnderstandingError, write_json

ORDER = ("understand", "find", "build", "judge", "rank", "baseline", "snap/check")
GUARD_PING_MESSAGES = [{"role": "user", "content": "Return only JSON with ok set to true."}]
GUARD_PING_PURPOSE = "p07.guard_refresh_ping"


def guard_ping_schema():
    return {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


def refresh_groq_budget(cfg, client):
    """Uncached Groq ping; the wrapper records its rate-limit header for the daily guard.

    Earlier Azure stages can outlast the guard's freshness window, so the judge
    phase gets a fresh observation instead of failing after Azure spend. Any
    failure here propagates and fails the judge stage (fail closed).
    """
    judge = cfg.active.judge
    if cfg.models[judge].provider != "groq":
        return None
    result = client.call(judge, GUARD_PING_MESSAGES, guard_ping_schema(), purpose=GUARD_PING_PURPOSE, no_cache=True,
                         response_validator=lambda data: [] if data.get("ok") is True else ["$.ok: expected true"],
                         **judging.purpose_options(cfg, "ping"))
    return {"status": "ok", "model_string": getattr(result, "model_string", None)}


def judge_stage(cfg, episodes, client, *, no_cache=False, allow_held_out=False):
    refresh = refresh_groq_budget(cfg, client)
    result = judging.run(cfg, episodes, client=client, no_cache=no_cache, full_run=True, allow_held_out=allow_held_out)
    if refresh is not None:
        result["guard_refresh_ping"] = refresh
    return result


def pacing(cfg, reservations):
    quota = model_quota(cfg, cfg.active.judge)
    now = [0.0]
    limiter = RateLimiter(quota["effective_rpm"], quota["effective_tpm"], clock=lambda: now[0],
                          sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
                          min_interval_s=cfg.rate_limit.min_interval_s)
    for reservation in reservations:
        if quota["effective_tpm"] and reservation > quota["effective_tpm"]:
            raise UnderstandingError("planned request exceeds judge TPM")
        limiter.acquire(reservation)
    return now[0]


def dry_run(cfg, episodes, *, allow_held_out=False):
    finding.check_selection([e.ep for e in episodes], allow_held_out)
    understanding.validate_inputs(episodes)
    judging.check_family(cfg)
    fingerprints(cfg, required=True)
    ranking.validate_eval_order(cfg)
    understood = understanding.dry_run(cfg, episodes, allow_held_out)
    picker = cfg.active.picker
    picker_provider = cfg.models[picker].provider
    judge = cfg.active.judge
    judge_provider = cfg.models[judge].provider
    cap = int(cfg.models[picker].params["max_completion_tokens"])
    parts = {}
    for name, row in understood["parts"].items():
        parts[name] = {**row, "provider": picker_provider, "model_key": picker,
                       "output_budget_tokens": row["estimated_output_tokens"], "estimated_usd": row["estimated_cost_usd"]}
    empty_header = dict.fromkeys(header.LIMITS, "")
    empty_sheet = {"characters": []}
    context_allowance = (len(chunks(episodes, cfg.understanding.character_chunk_episodes)) + 1) * cap
    moment_tokens = sum(estimate_tokens(_prompt_text(moments.messages(e, empty_header, empty_sheet, {"marks": []}), to_strict(moments.schema(e)))) for e in episodes)
    parts["moments"] = {"calls": len(episodes), "known_input_tokens": moment_tokens,
                        "dependency_allowance_tokens": len(episodes) * (context_allowance + cap),
                        "output_budget_tokens": len(episodes) * judging.output_cap(cfg, "moments", picker),
                        "provider": picker_provider, "model_key": picker}
    for part in ("answer_key", "cold_judge", "fidelity"):
        model = picker if part == "answer_key" else judge
        parts[part] = {"calls": 0, "known_input_tokens": 0, "dependency_allowance_tokens": 0,
                       "output_budget_tokens": 0, "provider": cfg.models[model].provider, "model_key": model}
    planned_by_ep = {}
    reservations = []
    for episode in episodes:
        count = min(cfg.judge.full_run.top_per_episode, cfg.builder.max_per_episode) if episode.ep < cfg.spoiler.late_series_start else 0
        repeated = min(count, cfg.judge.full_run.repeat_top_per_episode)
        cold_calls = count + repeated * (cfg.judge.full_run.repeat_runs - 1)
        planned_by_ep[f"E{episode.ep:02d}"] = {"judged_items_upper_bound": count, "repeated_items_upper_bound": repeated}
        if count:
            part = parts["answer_key"]
            # Empty dependency data are estimates, never fabricated model answers.
            ids = [f"P05-E{episode.ep:02d}-{n:03d}" for n in range(1, count + 1)]
            messages = judge_prompts.key_messages(episode, empty_header, empty_sheet, [])
            part["calls"] += 1
            part["known_input_tokens"] += estimate_tokens(_prompt_text(messages, to_strict(judge_prompts.key_schema(ids))))
            # Reserve context plus selected-ID list overhead.
            part["dependency_allowance_tokens"] += context_allowance + count * estimate_tokens(json.dumps([line.id for line in episode.lines]))
            part["output_budget_tokens"] += judging.output_cap(cfg, "answer_key", picker)
        request, schema, _ = judge_prompts.cold_request(episode.lines, list(judge_prompts.QUESTIONS))
        object_mode = cfg.models[judge].structured_output == "json_object"
        tokens = estimate_tokens(_prompt_text(json_messages(request, to_strict(schema)) if object_mode else request,
                                              {} if object_mode else to_strict(schema)))
        cold_cap = judging.output_cap(cfg, "cold_judge", judge)
        parts["cold_judge"]["calls"] += cold_calls
        parts["cold_judge"]["known_input_tokens"] += cold_calls * tokens
        parts["cold_judge"]["output_budget_tokens"] += cold_calls * cold_cap
        reservations.extend([tokens + cold_cap] * cold_calls)
        request, schema = judge_prompts.fidelity_request(dict.fromkeys(judge_prompts.KEY_FIELDS, ""), dict.fromkeys(judge_prompts.READER_FIELDS, ""))
        tokens = estimate_tokens(_prompt_text(json_messages(request, to_strict(schema)) if object_mode else request,
                                              {} if object_mode else to_strict(schema)))
        allowance = cfg.judge.fidelity_dependency_allowance_tokens
        fidelity_cap = judging.output_cap(cfg, "fidelity", judge)
        parts["fidelity"]["calls"] += count
        parts["fidelity"]["known_input_tokens"] += count * tokens
        parts["fidelity"]["dependency_allowance_tokens"] += count * allowance
        parts["fidelity"]["output_budget_tokens"] += count * fidelity_cap
        reservations.extend([tokens + allowance + fidelity_cap] * count)
    if judge_provider == "groq":
        # One uncached ping right before judging refreshes the daily-guard header (fail closed).
        ping_tokens = estimate_tokens(_prompt_text(json_messages(GUARD_PING_MESSAGES, to_strict(guard_ping_schema())), {}))
        ping_cap = int(judging.purpose_options(cfg, "ping").get("max_completion_tokens", 0) or 0)
        parts["guard_refresh_ping"] = {"calls": 1, "known_input_tokens": ping_tokens, "dependency_allowance_tokens": 0,
                                       "output_budget_tokens": ping_cap, "provider": judge_provider, "model_key": judge}
        reservations.insert(0, ping_tokens + ping_cap)
    parts["baseline"] = baseline.dry_run(cfg, episodes, allow_held_out=allow_held_out)
    for part in ("build", "rank", "snap/check"):
        parts[part] = {"calls": 0, "known_input_tokens": 0, "dependency_allowance_tokens": 0,
                       "output_budget_tokens": 0, "provider": "code", "model_key": None}
    providers = {}
    for row in parts.values():
        row["estimated_input_tokens"] = row["known_input_tokens"] + row["dependency_allowance_tokens"]
        price = cfg.pricing.get(row["model_key"])
        row["estimated_usd"] = (row["estimated_input_tokens"] * price.input_per_million_usd + row["output_budget_tokens"] * price.output_per_million_usd) / 1e6 if price else None if row["provider"] == "azure_foundry" else 0.0
        total = providers.setdefault(row["provider"], dict.fromkeys(("calls", "estimated_input_tokens", "output_budget_tokens", "estimated_usd"), 0))
        for key in total:
            total[key] = None if total[key] is None or row[key] is None else total[key] + row[key]
    calls = sum(p["calls"] for p in parts.values())
    groq_calls = providers.get("groq", {}).get("calls", 0)
    return {"dry_run": True, "episodes": [e.ep for e in episodes], "run": cfg.run_name, "order": list(ORDER),
            "parts": parts, "providers": providers, "planned_calls": calls, "max_calls_per_run": math.ceil(calls * 1.2),
            "planned_by_episode": planned_by_ep, "daily_guard": daily_check(cfg, groq_calls),
            "estimated_groq_time_s": pacing(cfg, reservations) if judge_provider == "groq" else 0,
            "estimated_judge_pacing_s": pacing(cfg, reservations), "judge_quota": model_quota(cfg, judge),
            "time_basis": "rolling request and input-plus-output reservations; excludes provider latency, retries and upstream Azure work",
            "estimate_basis": "candidate ceilings; full-episode cold-input upper bounds; dependency output caps; offline len/4 tokens; excludes latency/retries",
            **fingerprints(cfg, required=True)}


def snap_check(cfg, episodes):
    index = build_index(episodes)
    checked = baseline_checked = sensitivity_checked = 0
    for episode in episodes:
        candidates = finding.read_json(cfg.output_root / f"promos/candidates_E{episode.ep:02d}.json")
        for promo in candidates["candidates"]:
            judging.checked_item(promo, episode, cfg)
            checked += 1
        stored = finding.read_json(cfg.output_root / f"baseline/baseline_E{episode.ep:02d}.json")
        for key in ("kept", "sensitivity_kept"):
            for promo in stored[key]:
                result = baseline.check_snapped(promo["spans"], index, duration_check=key == "kept")
                if not result.ok:
                    raise UnderstandingError("final baseline checker invariant failed")
                baseline_checked += key == "kept"
                sensitivity_checked += key == "sensitivity_kept"
    result = {"tool_checked": checked, "baseline_checked": baseline_checked, "sensitivity_checked": sensitivity_checked}
    write_json(cfg.output_root / "baseline/snap_check.json", result)
    return result


def require_dev_acceptance(cfg):
    if cfg.run_name != "pilot" or cfg.models[cfg.active.judge].provider != "azure_foundry":
        return
    path = cfg.root / "outputs/runs/dev/ranked/promos_dev.json"
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))["summary"]
        if summary["items"] == 39 and summary["scored"] >= 38 and summary.get("judge_model_key") == cfg.active.judge:
            return
    except (OSError, ValueError, KeyError, TypeError):
        pass
    raise UnderstandingError("DEV acceptance requires at least 38/39 scored by the official judge; no live pilot")


def run(cfg, episodes, *, client=None, no_cache=False, allow_held_out=False):
    from .provider_protocol import require_foundry_ping
    require_foundry_ping(cfg)
    require_dev_acceptance(cfg)
    plan = dry_run(cfg, episodes, allow_held_out=allow_held_out)
    if cfg.models[cfg.active.judge].provider == "groq":
        daily_check(cfg, plan["providers"]["groq"]["calls"], refuse=True)
    marker = cfg.output_root / "run_manifest.json"
    if marker.exists() and json.loads(marker.read_text(encoding="utf-8")).get("status") in {"running", "complete", "failed"}:
        raise UnderstandingError("pipeline run name already used; choose a fresh run name")
    cfg = cfg.model_copy(deep=True)
    cfg.max_calls_per_run = plan["max_calls_per_run"]
    client = client or LLMClient(cfg)
    stages, results = {}, {}
    started = time.monotonic()
    manifest(cfg, [e.ep for e in episodes], status="running", plan=plan, stages=stages)
    write_json(cfg.output_root / "dry_run.json", plan)
    tasks = {
        "understand": lambda: understanding.run(cfg, episodes, client=client, no_cache=no_cache, allow_held_out=allow_held_out),
        "find": lambda: finding.run(cfg, episodes, client=client, no_cache=no_cache, allow_held_out=allow_held_out, reuse_reveals=True),
        "build": lambda: builder.run(cfg, episodes, allow_held_out=allow_held_out),
        "judge": lambda: judge_stage(cfg, episodes, client, no_cache=no_cache, allow_held_out=allow_held_out),
        "rank": lambda: ranking.run(cfg, episodes, allow_held_out=allow_held_out),
        "baseline": lambda: baseline.run(cfg, episodes, client=client, no_cache=no_cache, allow_held_out=allow_held_out),
        "snap/check": lambda: snap_check(cfg, episodes),
    }
    status = "failed"
    try:
        for name in ORDER:
            first = len(client.records)
            phase_start = time.monotonic()
            stages[name] = {"status": "running"}
            try:
                results[name] = tasks[name]()
                stages[name]["status"] = "complete"
                if results[name].get("status") in {"failed", "acceptance_failed", "RATE_LIMITED"} or results[name].get("failed_episodes"):
                    raise UnderstandingError("pipeline phase failed")
            except BaseException as exc:
                stages[name]["status"] = "RATE_LIMITED" if getattr(exc, "code", None) == "RATE_LIMITED" else "failed"
                status = stages[name]["status"]
                raise
            finally:
                stages[name].update(wall_time_s=time.monotonic() - phase_start, llm=summarize(client.records[first:], cfg))
                manifest(cfg, [e.ep for e in episodes], stages=stages)
        status = "complete"
        return {"status": status, "run": cfg.run_name, "stages": stages,
                "candidates_kept": results["build"]["kept"], "ranking": results["rank"],
                "retry_diagnostics": results["judge"]["retry_diagnostics"], "baseline": results["baseline"]}
    finally:
        manifest(cfg, [e.ep for e in episodes], status=status, stages=stages, llm=summarize(client.records, cfg),
                 wall_time_s=time.monotonic() - started,
                 returned_model_strings=sorted({r["model_string"] for r in client.records if r.get("model_string")}))


def cmd_run(cfg, args):
    try:
        eps = parse_eps(args.eps)
        finding.check_selection(eps, args.allow_held_out)
        episodes = understanding.load_requested(cfg, eps, args.allow_held_out)
        if args.dry_run:
            result = dry_run(cfg, episodes, allow_held_out=args.allow_held_out)
        else:
            from .provider_protocol import require_foundry_ping
            require_foundry_ping(cfg)
            require_dev_acceptance(cfg)
            # Fail before credentials or Azure spend when daily evidence is absent.
            plan = dry_run(cfg, episodes, allow_held_out=args.allow_held_out)
            if cfg.models[cfg.active.judge].provider == "groq":
                daily_check(cfg, plan["providers"]["groq"]["calls"], refuse=True)
            from .config import load_secrets
            load_secrets(cfg)
            result = run(cfg, episodes, no_cache=args.no_cache, allow_held_out=args.allow_held_out)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        if hasattr(exc, "summary"):
            print(json.dumps(exc.summary, sort_keys=True))
        print("run: failed; error=" + getattr(exc, "code", type(exc).__name__), file=sys.stderr)
        return 1
