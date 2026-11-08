"""DEV understanding pipeline and call/token preflight; no moment selection."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import characters, header, reveals
from .config import Config
from .intensity import profile
from .labelling import HELD_OUT, parse_eps
from .llm import LLMClient, _prompt_text, estimate_tokens, to_strict
from .models import Episode
from .parser import FILENAME_RE, find_episode_files, parse_file
from .policy import PolicyScanner
from .understanding_common import UnderstandingError, cost_usd, write_json

DEV_SPEC = "5-8,19-22"


class HeldOutRefused(UnderstandingError):
    code = "HELD_OUT_REFUSED"

    def __init__(self):
        super().__init__("refused: held-out episodes require --allow-held-out")


def check_selection(eps: list[int], allow_held_out: bool = False) -> None:
    if not eps:
        raise UnderstandingError("empty episode selection")
    if set(eps) & set(HELD_OUT) and not allow_held_out:
        raise HeldOutRefused()


def load_requested(cfg: Config, eps: list[int], allow_held_out: bool = False) -> list[Episode]:
    check_selection(eps, allow_held_out)
    if not cfg.data_dir.is_dir():
        raise UnderstandingError("data_dir not found")
    requested = set(eps)
    paths = {}
    for path in find_episode_files(cfg.data_dir):
        match = FILENAME_RE.match(path.name)
        if match and int(match.group(1)) in requested:
            number = int(match.group(1))
            if number in paths:
                raise UnderstandingError("duplicate requested source episode")
            paths[number] = path
    if requested != set(paths):
        raise UnderstandingError("requested source episode missing")
    episodes = [parse_file(paths[number]) for number in sorted(eps)]
    validate_inputs(episodes)
    return episodes


def validate_inputs(episodes: list[Episode]) -> None:
    ids = set()
    for episode in episodes:
        if not episode.lines:
            raise UnderstandingError("requested episode has no parsed lines")
        if not any(line.kind == "dialogue" and line.speaker for line in episode.lines):
            raise UnderstandingError("requested episode has no dialogue speaker labels")
        for line in episode.lines:
            if line.ep != episode.ep or line.id in ids:
                raise UnderstandingError("parsed line episode mismatch or duplicate ID")
            ids.add(line.id)


def dry_run(cfg: Config, episodes: list[Episode], allow_held_out: bool = False) -> dict:
    check_selection([e.ep for e in episodes], allow_held_out)
    validate_inputs(episodes)
    groups = characters.chunks(episodes, cfg.understanding.character_chunk_episodes)
    completion = int(cfg.models[cfg.active.picker].params.get("max_completion_tokens", 0))
    if completion <= 0:
        raise UnderstandingError("picker needs a positive completion token limit")

    def estimate(messages, schema):
        return estimate_tokens(_prompt_text(messages, to_strict(schema)))

    character_input = sum(estimate(characters.messages(group), characters.schema(group)) for group in groups)
    # Unknown AI results are not fabricated. Reserve predecessor completion budgets.
    empty_sheet = {"characters": []}
    empty_header = {field: "" for field in header.LIMITS}
    header_base = estimate(header.messages(episodes, empty_sheet), header.schema())
    reveals_base = sum(estimate(reveals.messages(e, empty_header, empty_sheet), reveals.schema(e)) for e in episodes)
    character_allowance = len(groups) * completion
    parts = {
        "characters": {"calls": len(groups), "known_input_tokens": character_input, "dependency_allowance_tokens": 0},
        "header": {"calls": 1, "known_input_tokens": header_base, "dependency_allowance_tokens": character_allowance},
        "reveals": {"calls": len(episodes), "known_input_tokens": reveals_base,
                    "dependency_allowance_tokens": len(episodes) * (character_allowance + completion)},
    }
    for part in parts.values():
        part["estimated_input_tokens"] = part["known_input_tokens"] + part["dependency_allowance_tokens"]
        part["estimated_output_tokens"] = part["calls"] * completion
        part["estimated_cost_usd"] = cost_usd(cfg, part["estimated_input_tokens"], part["estimated_output_tokens"])
    total_calls = sum(p["calls"] for p in parts.values())
    if total_calls > cfg.max_calls_per_run:
        raise UnderstandingError("planned calls exceed max_calls_per_run")
    input_tokens = sum(p["estimated_input_tokens"] for p in parts.values())
    output_tokens = sum(p["estimated_output_tokens"] for p in parts.values())
    return {"dry_run": True, "episodes": [e.ep for e in episodes], "parts": parts,
            "planned_calls": total_calls, "max_calls_per_run": cfg.max_calls_per_run,
            "estimated_input_tokens": input_tokens, "estimated_output_tokens": output_tokens,
            "estimated_cost_usd": cost_usd(cfg, input_tokens, output_tokens),
            "estimate_basis": "known inputs plus predecessor completion allowances; output caps; excludes retries",
            "pricing": cfg.pricing[cfg.active.picker].model_dump() if cfg.active.picker in cfg.pricing else None}


def call_summary(client: LLMClient, cfg: Config, start: int = 0) -> dict:
    records = client.records[start:]
    parts = {}
    for name in ("characters", "header", "reveals"):
        rows = [r for r in records if r.get("purpose", "").startswith("p02." + name)]
        completed = [r for r in rows if r.get("model_string") and r.get("error") is None]
        fresh = [r for r in rows if not r.get("cached") and isinstance(r.get("input_tokens"), int)]
        requests = {r["request_number"] for r in rows if r.get("request_number", 0) > 0}
        input_tokens = sum(r.get("input_tokens", 0) or 0 for r in fresh)
        output_tokens = sum(r.get("output_tokens", 0) or 0 for r in fresh)
        logical = {r["cache_key"] for r in rows if r.get("cache_key")}
        misses = {r["cache_key"] for r in rows if r.get("cache_key") and r.get("cached") is False}
        succeeded = {r["cache_key"] for r in completed}
        parts[name] = {
            "calls": len(logical), "failed_calls": len(logical - succeeded), "requests": len(requests),
            "cache_hits": sum(bool(r.get("cached")) for r in completed),
            "model_strings": sorted({r["model_string"] for r in rows if r.get("model_string")}),
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cost_estimate_usd": cost_usd(cfg, input_tokens, output_tokens),
            "retries": max(0, len(requests) - len(misses)),
            "http_failures": sum(r.get("event") == "http_attempt_failed" for r in rows),
            "response_failures": sum(r.get("error") in {"SCHEMA_ERROR", "EMPTY_OR_TRUNCATED"} for r in rows),
        }
    input_tokens = sum(p["input_tokens"] for p in parts.values())
    output_tokens = sum(p["output_tokens"] for p in parts.values())
    return {"parts": parts, "requests": sum(p["requests"] for p in parts.values()),
            "cache_hits": sum(p["cache_hits"] for p in parts.values()),
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cost_estimate_usd": cost_usd(cfg, input_tokens, output_tokens)}


def run(cfg: Config, episodes: list[Episode], *, client: LLMClient | None = None,
        no_cache: bool = False, allow_held_out: bool = False) -> dict:
    check_selection([e.ep for e in episodes], allow_held_out)
    preflight = dry_run(cfg, episodes, allow_held_out)
    out = cfg.output_root / "understanding"
    client = client or LLMClient(cfg, cache_dir=out / ".llm_cache")
    if hasattr(client, "begin_phase"):
        client.begin_phase()
    start = len(client.records)
    scanner = PolicyScanner()
    summary = {"episodes": [e.ep for e in episodes], "planned_calls": preflight["planned_calls"],
               "status": "running", "policy_hits": {}, "marks": {}, "trims_by_field": {}}
    try:
        for episode in episodes:
            write_json(out / f"intensity_E{episode.ep:02d}.json", profile(episode, cfg.intensity, scanner))
            flags = scanner.scan(episode.lines)
            write_json(out / f"policy_E{episode.ep:02d}.json", flags)
            counts = Counter(flag["category"] for flag in flags)
            summary["policy_hits"][f"E{episode.ep:02d}"] = {category: counts[category] for category in scanner.categories}
        chunks_data = []
        for number, group in enumerate(characters.chunks(episodes, cfg.understanding.character_chunk_episodes), 1):
            data = characters.build_chunk(group, cfg, client, number, no_cache)
            chunks_data.append(data)
            write_json(out / f"characters_chunk_{number:02d}.json", data)
        sheet = characters.merge(chunks_data, episodes)
        write_json(out / "characters.json", sheet)
        summary.update(coverage=sheet["coverage"], coverage_below_target=sheet["coverage_below_target"],
                       character_counts=sheet["counts"])
        summary["trims_by_field"]["characters"] = sheet["metadata"]["trims_by_field"]
        show_header = header.build(episodes, sheet, cfg, client, no_cache)
        write_json(out / "show_header.json", show_header)
        summary["trims_by_field"]["header"] = show_header["metadata"]["trims_by_field"]
        reveal_trims = Counter()
        for episode in episodes:
            data = reveals.build(episode, show_header, sheet, cfg, client, no_cache)
            write_json(out / f"reveals_E{episode.ep:02d}.json", data)
            summary["marks"][f"E{episode.ep:02d}"] = data["counts_by_type"]
            reveal_trims.update(data["metadata"]["trims_by_field"])
        summary["trims_by_field"]["reveals"] = dict(reveal_trims)
        summary["status"] = "complete"
    except Exception as exc:
        # Never serialize exception messages; providers may echo supplied content.
        summary.update(status="RATE_LIMITED" if getattr(exc, "code", None) == "RATE_LIMITED" else "failed", error_code=exc.code if hasattr(exc, "code") else type(exc).__name__)
        raise
    finally:
        summary["llm"] = call_summary(client, cfg, start)
        summary["pricing"] = cfg.pricing[cfg.active.picker].model_dump() if cfg.active.picker in cfg.pricing else None
        write_json(out / "run_summary.json", summary)
    return summary


def cmd_understand(cfg: Config, args) -> int:
    import json
    import sys

    from .config import load_secrets

    try:
        eps = parse_eps(args.eps)
        check_selection(eps, args.allow_held_out)
        episodes = load_requested(cfg, eps, args.allow_held_out)
        if args.dry_run:
            print(json.dumps(dry_run(cfg, episodes, args.allow_held_out), sort_keys=True))
            return 0
        # Credentials are loaded only by application code, only for a live request.
        load_secrets(cfg)
        summary = run(cfg, episodes, no_cache=args.no_cache, allow_held_out=args.allow_held_out)
        print(json.dumps(summary, sort_keys=True))
        return 0
    except Exception as exc:
        if isinstance(exc, UnderstandingError):
            print(f"understand: {exc}; error={exc.code}", file=sys.stderr)
        else:
            print("understand: failed; inspect count-only run_summary.json; error=" +
                  (exc.code if hasattr(exc, "code") else type(exc).__name__), file=sys.stderr)
        return 1
