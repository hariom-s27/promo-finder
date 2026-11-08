"""DEV find orchestration, offline preflight and count-only accounting."""

from __future__ import annotations

import json
import shutil
import sys

from . import moments, reveals
from .config import Config
from .labelling import HELD_OUT, parse_eps
from .llm import LLMClient, _prompt_text, estimate_tokens, to_strict
from .models import Episode
from .understanding import check_selection as check_understanding_selection
from .understanding import load_requested, validate_inputs
from .understanding_common import UnderstandingError, cost_usd, write_json


class HeldOutRefused(UnderstandingError):
    code = "HELD_OUT_REFUSED"

    def __init__(self):
        super().__init__("refused: held-out episodes require --allow-held-out")


def check_selection(eps: list[int], allow_held_out: bool = False) -> None:
    if set(eps) & set(HELD_OUT) and not allow_held_out:
        raise HeldOutRefused()
    check_understanding_selection(eps, allow_held_out)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise UnderstandingError("required artifact missing or invalid") from None


def context(cfg: Config) -> tuple[dict, dict]:
    out = cfg.root / "outputs/understanding"
    header, sheet = read_json(out / "show_header.json"), read_json(out / "characters.json")
    # Exercise both serializers before any secrets or physical requests.
    from .characters import roles
    from .header import fields
    fields(header)
    roles(sheet)
    return header, sheet


def dry_run(cfg: Config, episodes: list[Episode], allow_held_out: bool = False) -> dict:
    check_selection([episode.ep for episode in episodes], allow_held_out)
    validate_inputs(episodes)
    header, sheet = context(cfg)
    completion = int(cfg.models[cfg.active.picker].params.get("max_completion_tokens", 0))
    if completion <= 0:
        raise UnderstandingError("picker needs a positive completion token limit")
    if cfg.active.picker not in cfg.pricing:
        raise UnderstandingError("picker pricing is required for preflight")
    def estimate(messages, schema):
        return estimate_tokens(_prompt_text(messages, to_strict(schema)))
    parts = {
        "reveals": {"calls": len(episodes), "known_input_tokens": sum(
            estimate(reveals.messages(e, header, sheet), reveals.schema(e)) for e in episodes),
            "dependency_allowance_tokens": 0},
        "moments": {"calls": len(episodes), "known_input_tokens": sum(
            estimate(moments.messages(e, header, sheet, {"marks": []}), moments.schema(e)) for e in episodes),
            "dependency_allowance_tokens": len(episodes) * completion},
    }
    for part in parts.values():
        part["estimated_input_tokens"] = part["known_input_tokens"] + part["dependency_allowance_tokens"]
        part["output_budget_tokens"] = part["calls"] * completion
        part["estimated_cost_usd"] = cost_usd(cfg, part["estimated_input_tokens"], part["output_budget_tokens"])
    calls = sum(p["calls"] for p in parts.values())
    if calls > cfg.max_calls_per_run:
        raise UnderstandingError("planned calls exceed max_calls_per_run")
    inputs = sum(p["estimated_input_tokens"] for p in parts.values())
    outputs = sum(p["output_budget_tokens"] for p in parts.values())
    return {"dry_run": True, "episodes": [e.ep for e in episodes], "parts": parts,
            "planned_calls": calls, "max_calls_per_run": cfg.max_calls_per_run,
            "estimated_input_tokens": inputs, "output_budget_tokens": outputs,
            "estimated_cost_usd": cost_usd(cfg, inputs, outputs),
            "estimate_basis": "known inputs plus reveal completion allowance for hints; output caps; excludes retries",
            "pricing": cfg.pricing[cfg.active.picker].model_dump()}


def call_summary(client: LLMClient, cfg: Config, start: int = 0) -> dict:
    parts = {}
    for name in ("reveals", "moments"):
        rows = [r for r in client.records[start:] if r.get("purpose", "").startswith(f"p03.{name}.")]
        keys = {r["cache_key"] for r in rows if r.get("cache_key")}
        success = [r for r in rows if r.get("model_string") and r.get("error") is None]
        charged = [r for r in rows if not r.get("cached") and isinstance(r.get("input_tokens"), int)]
        inputs = sum(r.get("input_tokens", 0) or 0 for r in charged)
        outputs = sum(r.get("output_tokens", 0) or 0 for r in charged)
        requests = {r["request_number"] for r in rows if r.get("request_number", 0) > 0}
        parts[name] = {
            "calls": len(keys), "http_requests": len(requests),
            "http_429s": sum(r.get("event") == "http_attempt_failed" and r.get("error") == "HTTP_429" for r in rows),
            "cache_hits": sum(bool(r.get("cached")) for r in success),
            "model_strings": sorted({r["model_string"] for r in rows if r.get("model_string")}),
            "input_tokens": inputs, "output_tokens": outputs, "usd": cost_usd(cfg, inputs, outputs),
            "failures": len(keys - {r["cache_key"] for r in success}),
            "response_failures": sum(r.get("error") in {"SCHEMA_ERROR", "EMPTY_OR_TRUNCATED"} for r in rows),
            "http_failures": sum(r.get("event") == "http_attempt_failed" for r in rows),
            "transport_retries": sum(r.get("event") == "transport_retry" for r in rows),
        }
    return {"parts": parts, **{key: sum(part[key] for part in parts.values()) for key in (
        "calls", "http_requests", "http_429s", "cache_hits", "input_tokens", "output_tokens", "failures")},
        "usd": sum(part["usd"] or 0 for part in parts.values())}


def archive_p02(cfg: Config) -> dict:
    out = cfg.root / "outputs/understanding"
    archive = out / "archive_p02"
    archive.mkdir(parents=True, exist_ok=True)
    for path in sorted(out.glob("reveals_E*.json")):
        destination = archive / path.name
        if not destination.exists():
            # Never mistake an already-produced v2 result for the P02 original.
            if read_json(path).get("metadata", {}).get("version") == 2:
                raise UnderstandingError("P02 archive missing for existing v2 artifact")
            shutil.copy2(path, destination)
    counts = {}
    for path in sorted(archive.glob("reveals_E*.json")):
        marks = read_json(path)["marks"]
        counts[path.stem.removeprefix("reveals_")] = {
            kind: sum(mark["type"] == kind for mark in marks) for kind in ("reveal", "resolution")}
    return counts


def acceptance(marks: dict) -> dict:
    if not {"E05", "E19"} <= marks.keys():
        return {"status": "not_assessed", "minimum_marks": 3}
    total = sum(sum(marks[key].values()) for key in ("E05", "E19"))
    return {"status": "passed" if total >= 3 else "failed", "minimum_marks": 3,
            "total_marks": total, "hariom": {"E05": {"reveal": 0, "resolution": 2},
                                            "E19": {"reveal": 3, "resolution": 1}}}


def run(cfg: Config, episodes: list[Episode], *, client: LLMClient | None = None,
        no_cache: bool = False, allow_held_out: bool = False) -> dict:
    preflight = dry_run(cfg, episodes, allow_held_out)
    header, sheet = context(cfg)
    client = client or LLMClient(cfg, cache_dir=cfg.root / "outputs/understanding/.llm_cache")
    start = len(client.records)
    summary = {"status": "running", "episodes": [e.ep for e in episodes],
               "planned_calls": preflight["planned_calls"], "reveals_v2": {}, "moments": {}}
    try:
        summary["p02_marks"] = archive_p02(cfg)
        marks_by_ep = {}
        for episode in episodes:
            data = reveals.build(episode, header, sheet, cfg, client, no_cache, purpose_prefix="p03")
            write_json(cfg.root / f"outputs/understanding/reveals_E{episode.ep:02d}.json", data)
            marks_by_ep[episode.ep] = data
            summary["reveals_v2"][f"E{episode.ep:02d}"] = data["counts_by_type"]
        for episode in episodes:
            data = moments.build(episode, header, sheet, marks_by_ep[episode.ep], cfg, client, no_cache)
            write_json(cfg.root / f"outputs/moments/moments_E{episode.ep:02d}.json", data)
            summary["moments"][f"E{episode.ep:02d}"] = {"counts": data["counts"], "flags": data["flags"],
                "trims_by_field": data["metadata"]["trims_by_field"]}
        summary["acceptance"] = acceptance(summary["reveals_v2"])
        summary["status"] = "acceptance_failed" if summary["acceptance"]["status"] == "failed" else "complete"
    except Exception as exc:
        summary.update(status="failed", error_code=getattr(exc, "code", type(exc).__name__))
        raise
    finally:
        summary["llm"] = call_summary(client, cfg, start)
        summary["pricing"] = cfg.pricing[cfg.active.picker].model_dump()
        write_json(cfg.root / "outputs/moments/find_summary.json", summary)
    return summary


def cmd_find(cfg: Config, args) -> int:
    try:
        eps = parse_eps(args.eps)
        check_selection(eps, args.allow_held_out)
        episodes = load_requested(cfg, eps, args.allow_held_out)
        preflight = dry_run(cfg, episodes, args.allow_held_out)
        if args.dry_run:
            print(json.dumps(preflight, sort_keys=True))
            return 0
        from .config import load_secrets
        load_secrets(cfg)
        summary = run(cfg, episodes, no_cache=args.no_cache, allow_held_out=args.allow_held_out)
        print(json.dumps(summary, sort_keys=True))
        return int(summary["status"] != "complete")
    except HeldOutRefused as exc:
        print(f"find: {exc}; error={exc.code}", file=sys.stderr)
        return 1
    except Exception as exc:
        print("find: failed; error=" + getattr(exc, "code", type(exc).__name__), file=sys.stderr)
        return 1
