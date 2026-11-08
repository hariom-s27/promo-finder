"""Shared count-only accounting; rejected response usage is still charged."""

from __future__ import annotations

from collections import Counter


def part_name(purpose):
    pieces = purpose.split(".")
    return pieces[1] if pieces[0] in {"p02", "p03", "p05", "p07"} and len(pieces) > 1 else pieces[0]


def summarize(records, cfg):
    parts, providers = {}, {}
    groups = {(part_name(r["purpose"]), r["provider"]) for r in records if r.get("purpose") and r.get("provider")}
    for part, provider in sorted(groups):
        rows = [r for r in records if part_name(r.get("purpose", "")) == part and r.get("provider") == provider]
        charged = [r for r in rows if not r.get("cached") and not r.get("dry_run") and isinstance(r.get("input_tokens"), int)]
        inputs = sum(r["input_tokens"] for r in charged)
        outputs = sum(r.get("output_tokens", 0) or 0 for r in charged)
        price = next((cfg.pricing[r["model_key"]] for r in rows if r.get("model_key") in cfg.pricing), None)
        unknown_price = provider == "azure_foundry" and any(
            r.get("model_key") and r["model_key"] not in cfg.pricing for r in rows
            if not r.get("cached") and not r.get("dry_run") and
            (r.get("event") == "http_attempt_started" or isinstance(r.get("input_tokens"), int)))
        errors = Counter(r["error"] for r in rows if r.get("event") == "http_attempt_failed")
        calls = {(r.get("logical_call_id", r.get("purpose")), r["cache_key"]) for r in rows if r.get("cache_key")}
        row = {"calls": len(calls), "http_requests": sum(r.get("event") == "http_attempt_started" for r in rows),
               "http_errors": dict(sorted(errors.items())), "http_429s": errors["HTTP_429"],
               "http_503s": errors["HTTP_503"], "http_400s": errors["HTTP_400"],
               "cache_hits": sum(bool(r.get("cached")) for r in rows), "input_tokens": inputs, "output_tokens": outputs,
               "usd": None if unknown_price else (inputs * price.input_per_million_usd + outputs * price.output_per_million_usd) / 1e6 if price else 0.0,
               "pricing_basis": price.description if price else "unknown" if unknown_price else "no configured charge; unavailable error usage excluded",
               "reasoning_tokens": sum(r.get("reasoning_tokens", 0) or 0 for r in charged),
               "unknown_usage_http_errors": sum(errors.values()),
               "model_strings": sorted({r["model_string"] for r in rows if r.get("model_string")}),
               "json_modes": sorted({r["response_mode"] for r in rows if r.get("response_mode")}),
               "schema_failures": sum(r.get("error") == "SCHEMA_ERROR" for r in rows),
               "response_retries": sum(r.get("event") == "response_retry" for r in rows),
               "transport_retries": sum(r.get("event") == "transport_retry" for r in rows),
               "request_elapsed_s": sum(r.get("latency_ms", 0) for r in rows) / 1000}
        parts[part + ":" + provider] = row
        total = providers.setdefault(provider, {k: 0 for k in ("calls", "http_requests", "http_429s", "http_503s", "http_400s", "cache_hits", "input_tokens", "output_tokens", "usd", "schema_failures", "response_retries", "transport_retries", "request_elapsed_s", "unknown_usage_http_errors", "reasoning_tokens")})
        for key in total:
            total[key] = None if total[key] is None or row[key] is None else total[key] + row[key]
    return {"parts": parts, "providers": providers}
