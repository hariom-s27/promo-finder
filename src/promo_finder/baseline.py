"""Frozen single-prompt free-timestamp baseline; no gold scoring."""

from __future__ import annotations

import copy
import json
import math
import sys
import time
from types import SimpleNamespace
from collections import Counter

import yaml

from .checker import build_index, check_promo, snap_nearest_boundaries
from .config import PromoCfg
from .finding import check_selection, read_json
from .header import fields
from .labelling import parse_eps
from .llm import LLMClient, LLMError, _prompt_text, estimate_tokens, schema_errors, to_strict
from .understanding import load_requested
from .understanding_common import UnderstandingError, metadata, write_json


def load_spec(cfg):
    spec = yaml.safe_load((cfg.root / "config/baseline.yaml").read_text(encoding="utf-8"))
    purpose = cfg.purposes.get("baseline")
    if (spec["model_key"] != cfg.active.picker or spec["reasoning_effort"] != "low" or
            spec["top_k"] != 5 or spec["max_segments"] != 2 or not purpose or
            purpose.reasoning_effort != spec["reasoning_effort"] or
            purpose.max_completion_tokens != spec["max_completion_tokens"]):
        raise UnderstandingError("baseline settings differ from frozen config")
    if spec["order"] != {"within_episode": "model_output_order", "across_episodes": "round_robin",
                         "episodes": "ascending", "outer_loop": "within_episode_rank"}:
        raise UnderstandingError("unexpected baseline order")
    return spec


def timestamp(ms):
    minutes, remainder = divmod(round(ms / 100), 600)
    return f"{minutes:02d}:{remainder / 10:04.1f}"


def messages(episode, show_header, spec):
    rows = []
    for line in episode.lines:
        values = (f"{timestamp(line.start_ms)}–{timestamp(line.end_ms)}", line.kind,
                  line.speaker or "", line.emotion or "", line.text)
        rows.append(" | ".join(" ".join(value.split()).replace("|", "\\|") for value in values))
    return [{"role": "system", "content": spec["prompt"]},
            {"role": "user", "content": json.dumps({"show_header": fields(show_header)}, ensure_ascii=False) + "\n" + "\n".join(rows)}]


def response_errors(data, spec):
    errors = schema_errors(data, spec["schema"])
    if errors:
        return errors
    if len(data["promos"]) > spec["top_k"]:
        errors.append("$.promos: too many promos")
    for number, promo in enumerate(data["promos"]):
        if not 1 <= len(promo["segments"]) <= spec["max_segments"]:
            errors.append(f"$.promos[{number}].segments: expected one or two")
    return errors


def check_snapped(spans, index, *, duration_check=True):
    limits = PromoCfg(min_s=20, max_s=60, max_segments=2) if duration_check else SimpleNamespace(
        min_ms=0, max_ms=float("inf"), max_segments=2)
    return check_promo(spans, index, limits)


def snap_promos(data, episode, cfg):
    index = build_index([episode]) if episode is not None else {}
    invented = trims = 0
    snapped, kept, sensitivity, drops, sensitivity_drops = [], [], [], [], []
    for rank, raw in enumerate(data["promos"], 1):
        why_words = raw["why"].split()
        trims += len(why_words) > 12
        item = {"within_episode_rank": rank, "episode": episode.ep if episode else None,
                "why": " ".join(why_words[:12]), "spans": [], "segments": [], "boundary_moves_ms": []}
        if episode is None or not episode.lines:
            primary_errors = other_errors = ["UNKNOWN_EPISODE"]
        else:
            for segment in raw["segments"]:
                for value in (segment["start_s"], segment["end_s"]):
                    invented += value < 0 or value > episode.duration_ms / 1000
                bounds, start_move, end_move = snap_nearest_boundaries(
                    episode.ep, segment["start_s"] * 1000, segment["end_s"] * 1000, index)
                item["spans"].append(list(bounds))
                item["boundary_moves_ms"].append({"start": start_move, "end": end_move})
            checked = check_snapped(item["spans"], index)
            # The sensitivity disables ONLY the duration test.
            relaxed = check_snapped(item["spans"], index, duration_check=False)
            item["segments"] = [{"episode": seg.ep, "start_ms": seg.start_ms, "end_ms": seg.end_ms,
                                 "line_ids": seg.line_ids} for seg in checked.segments]
            item["duration_ms"] = checked.total_ms
            primary_errors, other_errors = checked.errors, relaxed.errors
        item["primary_errors"], item["sensitivity_errors"] = primary_errors, other_errors
        snapped.append(item)
        (drops if primary_errors else kept).append({"within_episode_rank": rank, "reasons": primary_errors} if primary_errors else copy.deepcopy(item))
        (sensitivity_drops if other_errors else sensitivity).append({"within_episode_rank": rank, "reasons": other_errors} if other_errors else copy.deepcopy(item))
    return {"raw": copy.deepcopy(data), "snapped": snapped, "kept": kept, "drops": drops,
            "sensitivity_kept": sensitivity, "sensitivity_drops": sensitivity_drops,
            "invented_timestamps": invented, "why_trims": trims}


def round_robin(episodes, key="kept"):
    rows = [row for ep in sorted(episodes) for row in episodes[ep].get(key, [])]
    return sorted(rows, key=lambda row: (row["within_episode_rank"], row["episode"]))


def summary(outputs):
    return {"episodes": {f"E{ep:02d}": {"kept": len(data["kept"]), "dropped": len(data["drops"]),
              "invented_timestamps": data["invented_timestamps"], "status": data.get("status", "ok")} for ep, data in outputs.items()},
            "invented_timestamps": sum(d["invented_timestamps"] for d in outputs.values()),
            "drops": sum(len(d["drops"]) for d in outputs.values()),
            "drops_by_reason": dict(Counter(reason for d in outputs.values() for drop in d["drops"] for reason in drop["reasons"])),
            "kept": sum(len(d["kept"]) for d in outputs.values()),
            "sensitivity_kept": sum(len(d["sensitivity_kept"]) for d in outputs.values()),
            "sensitivity_drops_by_reason": dict(Counter(reason for d in outputs.values() for drop in d["sensitivity_drops"] for reason in drop["reasons"])),
            "failed_episodes": sum(d.get("status") == "failed" for d in outputs.values())}


def dry_run(cfg, episodes, show_header=None, *, allow_held_out=False):
    check_selection([e.ep for e in episodes], allow_held_out)
    spec = load_spec(cfg)
    known = show_header is not None
    show_header = show_header if known else dict.fromkeys(("genre", "central_conflict", "main_relationships", "tone", "setting"), "")
    inputs = sum(estimate_tokens(_prompt_text(messages(e, show_header, spec), to_strict(spec["schema"]))) for e in episodes)
    allowance = 0 if known else len(episodes) * int(cfg.models[cfg.active.picker].params["max_completion_tokens"])
    outputs = len(episodes) * spec["max_completion_tokens"]
    price = cfg.pricing.get(spec["model_key"])
    return {"calls": len(episodes), "known_input_tokens": inputs, "dependency_allowance_tokens": allowance,
            "estimated_input_tokens": inputs + allowance, "output_budget_tokens": outputs,
            "provider": cfg.models[spec["model_key"]].provider, "model_key": spec["model_key"],
            "estimated_usd": ((inputs + allowance) * price.input_per_million_usd + outputs * price.output_per_million_usd) / 1e6 if price else 0.0}


def run(cfg, episodes, *, client=None, no_cache=False, allow_held_out=False):
    check_selection([e.ep for e in episodes], allow_held_out)
    spec = load_spec(cfg)
    show_header = read_json(cfg.output_root / "understanding/show_header.json")
    client = client or LLMClient(cfg, cache_dir=cfg.output_root / "baseline/.llm_cache")
    if hasattr(client, "begin_phase"):
        client.begin_phase()
    start = len(client.records)
    started = time.monotonic()
    outputs = {}
    try:
        for episode in episodes:
            try:
                result = client.call(spec["model_key"], messages(episode, show_header, spec), spec["schema"],
                    purpose=f"p07.baseline.E{episode.ep:02d}", no_cache=no_cache,
                    reasoning_effort=spec["reasoning_effort"], max_completion_tokens=spec["max_completion_tokens"],
                    cache_namespace="p07.baseline.v1", response_validator=lambda data: response_errors(data, spec))
                if response_errors(result.data, spec):
                    from .llm import SchemaError
                    raise SchemaError("baseline failed code revalidation")
                processed = snap_promos(result.data, episode, cfg)
                processed.update(status="ok", metadata=metadata(result))
            except LLMError as exc:
                from .llm import BudgetExceeded, RateLimited
                if isinstance(exc, (BudgetExceeded, RateLimited)):
                    raise
                processed = {"status": "failed", "error_code": exc.code, "raw": None, "snapped": [], "kept": [], "drops": [],
                             "sensitivity_kept": [], "sensitivity_drops": [], "invented_timestamps": 0, "why_trims": 0}
                failed = getattr(exc, "result", None)
                if failed is not None:
                    processed["raw"] = failed.raw_text
            outputs[episode.ep] = processed
            write_json(cfg.output_root / f"baseline/baseline_E{episode.ep:02d}.json", processed)
    finally:
        from .accounting import summarize
        totals = {**summary(outputs), "llm": summarize(client.records[start:], cfg), "wall_time_s": time.monotonic() - started,
                  "max_calls_per_run": cfg.max_calls_per_run,
                  "invented_timestamp_count_complete": all(d.get("status") != "failed" for d in outputs.values())}
        if getattr(client, "phase_rate_limited", False):
            totals.update(status="RATE_LIMITED", error_code="RATE_LIMITED", invented_timestamp_count_complete=False)
        write_json(cfg.output_root / "baseline/baseline_summary.json", totals)
        write_json(cfg.output_root / "baseline/baseline_order.json", {"promos": round_robin(outputs),
                   "sensitivity_promos": round_robin(outputs, "sensitivity_kept")})
    return totals


def cmd_baseline(cfg, args):
    try:
        eps = parse_eps(args.eps)
        check_selection(eps, args.allow_held_out)
        episodes = load_requested(cfg, eps, args.allow_held_out)
        if args.dry_run:
            result = {"dry_run": True, **dry_run(cfg, episodes, allow_held_out=args.allow_held_out)}
        else:
            plan = dry_run(cfg, episodes, allow_held_out=args.allow_held_out)
            cfg = cfg.model_copy(deep=True)
            cfg.max_calls_per_run = math.ceil(plan["calls"] * 1.2)
            from .config import load_secrets
            load_secrets(cfg)
            result = run(cfg, episodes, no_cache=args.no_cache, allow_held_out=args.allow_held_out)
        print(json.dumps(result, sort_keys=True))
        return int(bool(result.get("failed_episodes")))
    except Exception as exc:
        print("baseline: failed; error=" + getattr(exc, "code", type(exc).__name__), file=sys.stderr)
        return 1
