"""DEV cold judging, answer keys, reliability and count-only accounting."""

from __future__ import annotations

import copy
import json
import math
import re
import sys
from collections import Counter

import yaml

from . import judge_prompts as prompts
from .checker import build_index, check_promo
from .config import Config, model_quota
from .finding import HeldOutRefused, check_selection, context, read_json
from .labelling import parse_eps
from .llm import BudgetExceeded, LLMClient, LLMError, RateLimited, RateLimiter, SchemaError, _prompt_text, estimate_tokens, schema_errors, to_strict
from .understanding import load_requested
from .understanding_common import UnderstandingError, metadata, trim, write_json


class FamilyRefused(UnderstandingError):
    code = "MODEL_FAMILY_REFUSED"


def check_family(cfg):
    picker = cfg.models[cfg.active.picker].family.strip().lower()
    judge = cfg.models[cfg.active.judge].family.strip().lower()
    if not picker or not judge or picker == judge or "tbd" in (picker, judge):
        raise FamilyRefused("judge must have a distinct known family")


def human_rows(cfg):
    data = yaml.safe_load((cfg.root / "config/p03_human_majorities.yaml").read_text(encoding="utf-8"))["promos"]
    if len(data) != 6 or any(set(row) != {"Q1", "Q2", "Q3"} or
                           any(type(value) is not bool for value in row.values()) for row in data.values()):
        raise UnderstandingError("invalid reference feedback")
    return data


def checked_item(promo, episode, cfg, reference=False):
    index = build_index([episode])
    spans = [(s["first_line_id"], s["last_line_id"]) for s in promo["segments"]]
    checked = check_promo(spans, index, cfg)
    if not checked.ok or any(s.ep != episode.ep for s in checked.segments):
        raise UnderstandingError("candidate checker failure")
    ids = [key for seg in checked.segments for key in seg.line_ids]
    if ids != promo["line_ids"] or promo["episode"] != episode.ep:
        raise UnderstandingError("candidate line mismatch")
    for stored, actual in zip(promo["segments"], checked.segments):
        if (stored["episode"], stored["start_ms"], stored["end_ms"]) != (actual.ep, actual.start_ms, actual.end_ms):
            raise UnderstandingError("candidate timestamp mismatch")
    if not isinstance(promo.get("pre_score"), (float, int)) or not math.isfinite(promo["pre_score"]):
        raise UnderstandingError("invalid pre_score")
    return {**copy.deepcopy(promo), "reference": reference}


def prepare(cfg, episodes, *, full_run=False, allow_held_out=False):
    check_selection([e.ep for e in episodes], allow_held_out)
    check_family(cfg)
    human = {} if full_run else human_rows(cfg)
    by_ep = {}
    for episode in episodes:
        current = read_json(cfg.output_root / f"promos/candidates_E{episode.ep:02d}.json")
        if current.get("episode") != episode.ep:
            raise UnderstandingError("candidate episode mismatch")
        items = [checked_item(p, episode, cfg) for p in current["candidates"]]
        reference_ids = [key for key in human if key.startswith(f"P03-E{episode.ep:02d}-")]
        if reference_ids:
            archived = read_json(cfg.output_root / f"promos/archive_p03/candidates_E{episode.ep:02d}.json")
            found = {p["promo_id"]: p for p in archived["candidates"] if p["promo_id"] in reference_ids}
            if set(found) != set(reference_ids):
                raise UnderstandingError("reference candidates missing")
            items.extend(checked_item(found[key], episode, cfg, True) for key in reference_ids)
        if len({p["promo_id"] for p in items}) != len(items):
            raise UnderstandingError("duplicate promo IDs")
        if full_run:
            items = sorted(items, key=lambda p: (-p["pre_score"], p["promo_id"]))[:cfg.judge.full_run.top_per_episode]
        by_ep[episode.ep] = items
    return by_ep


def run_counts(items, cfg, *, full_run=False):
    current = sorted((p for p in items if not p["reference"]), key=lambda p: (-p["pre_score"], p["promo_id"]))
    plan = cfg.judge.full_run if full_run else cfg.judge
    repeated = {p["promo_id"] for p in current[:plan.repeat_top_per_episode]}
    return {p["promo_id"]: plan.repeat_runs if p["reference"] or p["promo_id"] in repeated else 1 for p in items}


def purpose_options(cfg, name):
    purpose = cfg.purposes.get(name)
    return {key: value for key, value in (purpose.model_dump() if purpose else {}).items() if value is not None}


def output_cap(cfg, name, model):
    return int(purpose_options(cfg, name).get("max_completion_tokens", cfg.models[model].params.get("max_completion_tokens", 0)))


def answer_key_cache_status(cfg, episodes, prepared):
    from .llm import cache_key
    header, sheet = context(cfg)
    model = cfg.models[cfg.active.picker]
    params = {**model.params, **purpose_options(cfg, "answer_key"), "_namespace": "p05.answer_key.v1"}
    if model.family.lower() == "openai":
        params.pop("temperature", None)
    if model.structured_output != "strict":
        params["_structured_output"] = model.structured_output
    hits = planned = 0
    for episode in episodes:
        items = prepared[episode.ep]
        if not items:
            continue
        planned += 1
        ids = list(run_counts(items, cfg))
        schema = to_strict(prompts.key_schema(ids))
        key = cache_key(model.provider, model.model, params, prompts.key_messages(episode, header, sheet, items), schema)
        path = cfg.output_root / "judge/.llm_cache" / (key + ".json")
        try:
            hit = json.loads(path.read_text(encoding="utf-8"))
            good = not schema_errors(hit["data"], schema) and not coverage_errors(hit["data"], ids)
            hits += good
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return {"planned": planned, "valid_cache_hits": hits, "missing_or_invalid": planned - hits,
            "expected_live_azure_usd": 0.0 if hits == planned else None}


def dry_run(cfg, episodes, prepared=None, *, full_run=False, allow_held_out=False):
    check_selection([e.ep for e in episodes], allow_held_out)
    check_family(cfg)
    prepared = prepared if prepared is not None else prepare(cfg, episodes, full_run=full_run, allow_held_out=allow_held_out)
    header, sheet = context(cfg)
    parts = {name: {"calls": 0, "known_input_tokens": 0, "dependency_allowance_tokens": 0,
                    "output_budget_tokens": 0, "provider": cfg.models[model].provider,
                    "model_key": model} for name, model in (("answer_key", cfg.active.picker),
                        ("cold_judge", cfg.active.judge), ("fidelity", cfg.active.judge))}
    scheduled = []
    repeated = current = references = 0
    for episode in episodes:
        items = prepared[episode.ep]
        counts = run_counts(items, cfg, full_run=full_run)
        current += sum(not p["reference"] for p in items)
        references += sum(p["reference"] for p in items)
        repeated += sum(n > 1 for n in counts.values())
        if items:
            messages, schema = prompts.key_messages(episode, header, sheet, items), prompts.key_schema(list(counts))
            part = parts["answer_key"]
            part["calls"] += 1
            part["known_input_tokens"] += estimate_tokens(_prompt_text(messages, to_strict(schema)))
            part["output_budget_tokens"] += output_cap(cfg, "answer_key", cfg.active.picker)
        index = build_index([episode])
        for item in items:
            used = set()
            for run in range(counts[item["promo_id"]]):
                seed, order = prompts.shuffle(cfg.judge.shuffle_seed, item["promo_id"], run, used)
                used.add(tuple(order))
                messages, schema, _ = prompts.cold_request([index[key] for key in item["line_ids"]], order)
                from .llm import json_messages
                object_mode = cfg.models[cfg.active.judge].structured_output == "json_object"
                tokens = estimate_tokens(_prompt_text(json_messages(messages, to_strict(schema)) if object_mode else messages,
                                                      {} if object_mode else to_strict(schema)))
                cap = output_cap(cfg, "cold_judge", cfg.active.judge)
                part = parts["cold_judge"]
                part["calls"] += 1
                part["known_input_tokens"] += tokens
                part["output_budget_tokens"] += cap
                scheduled.append(tokens + cap)
            # Estimate unknown short answer content with an explicit allowance, not invented answers.
            empty_key = {key: "" for key in prompts.KEY_FIELDS}
            empty_reader = {key: "" for key in prompts.READER_FIELDS}
            messages, schema = prompts.fidelity_request(empty_key, empty_reader)
            from .llm import json_messages
            object_mode = cfg.models[cfg.active.judge].structured_output == "json_object"
            tokens = estimate_tokens(_prompt_text(json_messages(messages, to_strict(schema)) if object_mode else messages,
                                                  {} if object_mode else to_strict(schema)))
            allowance = cfg.judge.fidelity_dependency_allowance_tokens
            cap = output_cap(cfg, "fidelity", cfg.active.judge)
            part = parts["fidelity"]
            part["calls"] += 1
            part["known_input_tokens"] += tokens
            part["dependency_allowance_tokens"] += allowance
            part["output_budget_tokens"] += cap
            scheduled.append(tokens + allowance + cap)
    key_cache = answer_key_cache_status(cfg, episodes, prepared)
    parts["answer_key"]["expected_cache_hits"] = key_cache["valid_cache_hits"]
    providers = {}
    for name, part in parts.items():
        part["estimated_input_tokens"] = part["known_input_tokens"] + part["dependency_allowance_tokens"]
        price = cfg.pricing.get(part["model_key"])
        part["estimated_usd"] = ((part["estimated_input_tokens"] * price.input_per_million_usd +
                                  part["output_budget_tokens"] * price.output_per_million_usd) / 1e6) if price else None if part["provider"] == "azure_foundry" else 0.0
        cached = name == "answer_key" and key_cache["valid_cache_hits"] == key_cache["planned"]
        part["estimated_live_usd"] = 0.0 if cached else part["estimated_usd"]
        part["estimated_live_input_tokens"] = 0 if cached else part["estimated_input_tokens"]
        part["estimated_live_output_budget_tokens"] = 0 if cached else part["output_budget_tokens"]
        provider = providers.setdefault(part["provider"], {"calls": 0, "estimated_input_tokens": 0, "output_budget_tokens": 0, "estimated_usd": 0.0,
                    "estimated_live_usd": 0.0, "estimated_live_input_tokens": 0, "estimated_live_output_budget_tokens": 0})
        for key in provider:
            provider[key] = None if provider[key] is None or part[key] is None else provider[key] + part[key]
    quota = model_quota(cfg, cfg.active.judge)
    now = [0.0]
    limiter = RateLimiter(quota["effective_rpm"], quota["effective_tpm"], clock=lambda: now[0],
                          sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
                          min_interval_s=cfg.rate_limit.min_interval_s)
    for reservation in scheduled:
        if quota["effective_tpm"] and reservation > quota["effective_tpm"]:
            raise UnderstandingError("planned request exceeds judge TPM")
        limiter.acquire(reservation)
    calls = sum(part["calls"] for part in parts.values())
    return {"dry_run": True, "episodes": [e.ep for e in episodes], "current_items": current,
            "reference_items": references, "repeated_items": repeated, "parts": parts, "providers": providers,
            "planned_calls": calls, "recommended_budget": math.ceil(calls * 1.2),
            "max_calls_per_run": cfg.max_calls_per_run, "budget_covers_plan": calls <= cfg.max_calls_per_run,
            "estimated_judge_pacing_s": now[0], "pacing_basis": "input plus completion reservations; excludes latency and retries",
            "judge_quota": quota,
            "token_basis": "offline len/4 estimate (or already-loaded tokenizer) plus configured fidelity dependency allowance; excludes retries",
            "no_items_episodes": [ep for ep, items in prepared.items() if not items],
            "pricing": {name: value.model_dump() for name, value in cfg.pricing.items()},
            "full_run": full_run,
            "answer_key_cache": key_cache,
            "cache_basis": "logical schedule; live calls may hit cache; each item/run has a distinct namespace"}


def coverage_errors(data, ids):
    counts = Counter(row["promo_id"] for row in data["answers"])
    return [] if counts == Counter(ids) else ["$: promo coverage mismatch"]


def short_fields(data, fields):
    counts = Counter({field: 0 for field in fields})
    data = copy.deepcopy(data)
    for field in fields:
        data[field] = trim(data[field], 15, field, counts)
    return data, dict(counts)


def aggregate(runs, expected_runs=1):
    good = [run for run in runs if run["status"] == "ok"]
    result = {"successful_runs": len(good), "failed_runs": sum(run["status"] == "failed" for run in runs),
              "answers": {}, "yes_shares": {}, "per_question_disagreement": {q: None for q in prompts.QUESTIONS},
              "flip_rate": None, "hook_rating_mean": None, "cliff_rating_mean": None}
    if not good:
        return result
    for q in prompts.QUESTIONS:
        yes = sum(run["answers"][q]["answer"] == "yes" for run in good)
        result["yes_shares"][q] = yes / len(good)
        result["answers"][q] = "yes" if yes * 2 > len(good) else "no" if yes * 2 < len(good) else None
        if expected_runs > 1 and len(good) > 1:
            result["per_question_disagreement"][q] = int(0 < yes < len(good))
    if expected_runs > 1 and len(good) > 1:
        result["flip_rate"] = sum(result["per_question_disagreement"].values()) / len(prompts.QUESTIONS)
    for name in ("hook", "cliff"):
        result[name + "_rating_mean"] = sum(int(run["answers"][name + "_rating"]) for run in good) / len(good)
    return result


def reliability(items):
    return {q: {"flipped_items": sum(values), "measured_items": len(values),
                 "flip_rate": sum(values) / len(values) if values else None}
            for q in prompts.QUESTIONS for values in [[item["aggregate"]["per_question_disagreement"][q]
               for item in items if item["aggregate"]["per_question_disagreement"][q] is not None]]}


def retry_diagnostics(items):
    """Descriptive addition only; official aggregates are never changed."""
    clean = []
    final_samples = retried_samples = 0
    for item in items:
        good = [r for r in item["runs"] if r["status"] == "ok"]
        final_samples += len(good)
        retried_samples += sum(r.get("metadata", {}).get("validation_retry_used", False) and
                               r.get("metadata", {}).get("final_temperature") == .3 for r in good)
        excluded = [r for r in item["runs"] if not r.get("metadata", {}).get("validation_retry_used", False)]
        clean.append({"aggregate": aggregate(excluded, expected_runs=len(item["runs"]))})
    reliability_without = reliability(clean)
    reliability_with = reliability([{"aggregate": item.get("aggregate") or aggregate(item["runs"], len(item["runs"]))} for item in items])
    return {q: {"successful_final_samples": final_samples, "final_samples_from_0_3_retry": retried_samples,
                "retried_sample_share": retried_samples / final_samples if final_samples else None,
                "including_retried_samples": reliability_with[q],
                "excluding_retried_samples": reliability_without[q]} for q in prompts.QUESTIONS}


def agreement(items, human):
    rows = []
    for item in items:
        key = item["promo_id"]
        if key not in human:
            continue
        agg = item["aggregate"]
        judged = {"Q1": agg["hook_rating_mean"] >= 3 if agg["hook_rating_mean"] is not None else None,
                  "Q2": None if agg["answers"].get("standalone") is None else agg["answers"]["standalone"] == "yes",
                  "Q3": None if agg["answers"].get("ends_unresolved") is None else agg["answers"]["ends_unresolved"] == "yes"}
        rows.append({"promo_id": key, "human": human[key], "judge": judged,
                     "agreement": {q: judged[q] == human[key][q] if judged[q] is not None else None for q in judged}})
    return {"descriptive_only": True, "expected_n": len(human), "per_promo": rows,
            "questions": {q: {"agree": sum(row["agreement"][q] is True for row in rows),
                                "assessed": sum(row["agreement"][q] is not None for row in rows),
                                "expected": len(human)} for q in ("Q1", "Q2", "Q3")}}


def call_accounting(records, cfg):
    from .accounting import summarize
    return summarize(records, cfg)


def failed_metadata(client, purpose):
    rows = [r for r in client.records if r.get("purpose") == purpose]
    last = next((r for r in reversed(rows) if r.get("model_string")), rows[-1] if rows else {})
    result = {key: last.get(key) for key in ("model_string", "cache_key", "response_mode", "input_tokens", "output_tokens")}
    failure = next((r for r in reversed(rows) if r.get("event") == "http_attempt_failed"), {})
    result.update({key: failure[key] for key in ("http_status_code", "provider_error_code", "provider_innererror_code",
                   "content_filter_code", "content_filter_categories", "content_filter_labels") if key in failure})
    return result


def run(cfg, episodes, client=None, no_cache=False, *, full_run=False, allow_held_out=False):
    prepared = prepare(cfg, episodes, full_run=full_run, allow_held_out=allow_held_out)
    preflight = dry_run(cfg, episodes, prepared, full_run=full_run, allow_held_out=allow_held_out)
    if not preflight["budget_covers_plan"]:
        raise UnderstandingError("planned calls exceed max_calls_per_run")
    from .provider_protocol import require_foundry_ping
    require_foundry_ping(cfg)
    if cfg.models[cfg.active.judge].provider == "azure_foundry":
        from .run_context import fingerprints
        fingerprints(cfg, required=True)
    dev_cached_keys = cfg.run_name == "dev" and cfg.models[cfg.active.judge].provider == "azure_foundry"
    if dev_cached_keys and preflight["answer_key_cache"]["missing_or_invalid"]:
        raise UnderstandingError("DEV answer-key cache incomplete; refusing unexpected Azure requests")
    if cfg.run_name == "dev" and cfg.models[cfg.active.judge].provider == "azure_foundry":
        from .judge_arms import archive_groq
        archive_groq(cfg)
    if cfg.models[cfg.active.judge].provider == "groq":
        from .budget import check
        preflight["daily_guard"] = check(cfg, sum(preflight["parts"][p]["calls"] for p in ("cold_judge", "fidelity")), refuse=True)
    client = client or LLMClient(cfg, cache_dir=cfg.output_root / "judge/.llm_cache")
    if hasattr(client, "begin_phase"):
        client.begin_phase()
    start = len(client.records)
    header, sheet = context(cfg)
    all_items = []
    summary = {"status": "running", "preflight": preflight, "failed_runs_by_part": {"answer_key": 0, "cold_judge": 0, "fidelity": 0}}
    try:
        for episode in episodes:
            items = prepared[episode.ep]
            ids = [item["promo_id"] for item in items]
            keys, missing = {}, list(ids)
            key_output = {"episode": episode.ep, "status": "no items" if not items else "ok", "answers": [], "missing": []}
            if items:
                schema = prompts.key_schema(ids)
                try:
                    result = client.call(cfg.active.picker, prompts.key_messages(episode, header, sheet, items), schema,
                        purpose=f"p05.answer_key.E{episode.ep:02d}", no_cache=False if dev_cached_keys else no_cache,
                        **({"cache_only": True} if dev_cached_keys else {}),
                        cache_namespace="p05.answer_key.v1", response_validator=lambda data: coverage_errors(data, ids),
                        **purpose_options(cfg, "answer_key"))
                except SchemaError as exc:
                    result = getattr(exc, "result", None)
                    key_output["status"] = "failed"
                    summary["failed_runs_by_part"]["answer_key"] += 1
                if result is not None:
                    key_output["metadata"] = metadata(result, response_mode=result.response_mode)
                    # Only individually schema-valid, unique rows can survive a coverage failure.
                    raw = result.data.get("answers", []) if isinstance(result.data, dict) else []
                    counts = Counter(row.get("promo_id") for row in raw if isinstance(row, dict))
                    for row in raw:
                        if schema_errors(row, schema["properties"]["answers"]["items"]) or counts[row["promo_id"]] != 1:
                            continue
                        cleaned, trims = short_fields(row, prompts.KEY_FIELDS)
                        keys[row["promo_id"]] = cleaned
                        key_output["answers"].append({**cleaned, "reference": next(p["reference"] for p in items if p["promo_id"] == row["promo_id"]), "trims_by_field": trims})
                missing = sorted(set(ids) - set(keys))
                key_output["missing"] = missing
            write_json(cfg.output_root / f"judge/answer_key_E{episode.ep:02d}.json", key_output)
            counts = run_counts(items, cfg, full_run=full_run)
            index = build_index([episode])
            judged = []
            for item in items:
                promo_id = item["promo_id"]
                record = {"promo_id": promo_id, "reference": item["reference"], "candidate": item, "runs": [],
                          "answer_key": keys.get(promo_id), "answer_key_metadata": key_output.get("metadata"),
                          "fidelity": {"status": "skipped", "cold": False, "reason": "missing dependency"}}
                used = set()
                for number in range(counts[promo_id]):
                    seed, order = prompts.shuffle(cfg.judge.shuffle_seed, promo_id, number, used)
                    used.add(tuple(order))
                    messages, schema, mapping = prompts.cold_request([index[key] for key in item["line_ids"]], order)
                    serialized = json.dumps([messages, schema])
                    if re.search(r"E\d\d-L", serialized):
                        raise UnderstandingError("cold request contains real identifiers")
                    row = {"run": number + 1, "seed": seed, "question_order": order, "cold": True, "local_to_real": mapping}
                    try:
                        result = client.call(cfg.active.judge, messages, schema,
                            purpose=f"p05.cold_judge.{promo_id}.run{number + 1}", no_cache=no_cache,
                            temperature=cfg.judge.temperature, cache_namespace=f"p05.cold.v1:{promo_id}:{number}:{seed}",
                            retry_temperature=cfg.judge.retry_temperature,
                            **purpose_options(cfg, "cold_judge"))
                        data, trims = short_fields(result.data, prompts.READER_FIELDS)
                        for q in prompts.QUESTIONS:
                            data[q]["evidence"] = mapping[data[q]["evidence"]]
                        row.update(status="ok", answers=data, metadata=metadata(result, Counter(trims), response_mode=result.response_mode))
                    except (BudgetExceeded, RateLimited):
                        record["runs"].append({**row, "status": "failed", "error_code": "RATE_LIMITED" if getattr(client, "phase_rate_limited", False) else "BUDGET_EXCEEDED"})
                        judged.append(record)
                        write_json(cfg.output_root / f"judge/judge_E{episode.ep:02d}.json", {"episode": episode.ep, "items": judged, "partial": True})
                        raise
                    except LLMError as exc:
                        row.update(status="failed", error_code=exc.code,
                                   metadata=failed_metadata(client, f"p05.cold_judge.{promo_id}.run{number + 1}"))
                        summary["failed_runs_by_part"]["cold_judge"] += 1
                    record["runs"].append(row)
                first = record["runs"][0]
                if promo_id in keys and first["status"] == "ok":
                    messages, schema = prompts.fidelity_request(keys[promo_id], first["answers"])
                    try:
                        result = client.call(cfg.active.judge, messages, schema, purpose=f"p05.fidelity.{promo_id}",
                            no_cache=no_cache, temperature=cfg.judge.temperature, cache_namespace=f"p05.fidelity.v1:{promo_id}",
                            retry_temperature=cfg.judge.retry_temperature,
                            **purpose_options(cfg, "fidelity"))
                        record["fidelity"] = {"status": "ok", "cold": False, "matches": result.data,
                                                "metadata": metadata(result, response_mode=result.response_mode)}
                    except (BudgetExceeded, RateLimited):
                        judged.append(record)
                        write_json(cfg.output_root / f"judge/judge_E{episode.ep:02d}.json", {"episode": episode.ep, "items": judged, "partial": True})
                        raise
                    except LLMError as exc:
                        record["fidelity"] = {"status": "failed", "cold": False, "error_code": exc.code,
                                              "metadata": failed_metadata(client, f"p05.fidelity.{promo_id}")}
                        summary["failed_runs_by_part"]["fidelity"] += 1
                record["aggregate"] = aggregate(record["runs"], counts[promo_id])
                judged.append(record)
                all_items.append(record)
            write_json(cfg.output_root / f"judge/judge_E{episode.ep:02d}.json", {"episode": episode.ep, "items": judged,
                       "model_key": cfg.active.judge, "provider": cfg.models[cfg.active.judge].provider,
                       "deployment": cfg.models[cfg.active.judge].model,
                       "full_run_selection": full_run, "selected_promo_ids": [p["promo_id"] for p in items if not p["reference"]]})
        summary.update(status="complete", reliability=reliability(all_items),
                       human_agreement=agreement(all_items, {} if full_run else human_rows(cfg)),
                       retry_diagnostics=retry_diagnostics(all_items),
                       current_items=sum(not p["reference"] for p in all_items), reference_items=sum(p["reference"] for p in all_items))
    except Exception as exc:
        summary.update(status="RATE_LIMITED" if isinstance(exc, RateLimited) else "failed", error_code=getattr(exc, "code", type(exc).__name__))
        raise
    finally:
        summary["llm"] = call_accounting(client.records[start:], cfg)
        write_json(cfg.output_root / "judge/judge_summary.json", summary)
    return summary


def cmd_judge(cfg, args):
    try:
        eps = parse_eps(args.eps)
        check_selection(eps, args.allow_held_out)
        check_family(cfg)
        episodes = load_requested(cfg, eps, args.allow_held_out)
        plan = dry_run(cfg, episodes, allow_held_out=args.allow_held_out)
        cfg = cfg.model_copy(deep=True)
        cfg.max_calls_per_run = plan["recommended_budget"]
        plan["max_calls_per_run"] = cfg.max_calls_per_run
        plan["budget_covers_plan"] = True
        if cfg.models[cfg.active.judge].provider == "groq":
            from .budget import check
            plan["daily_guard"] = check(cfg, sum(plan["parts"][p]["calls"] for p in ("cold_judge", "fidelity")), refuse=not args.dry_run)
        from .understanding import DEV_SPEC
        if (not args.dry_run and not args.no_cache and eps == parse_eps(DEV_SPEC) and cfg.run_name == "dev" and
                cfg.models[cfg.active.picker].provider == "azure" and plan["answer_key_cache"]["missing_or_invalid"]):
            raise UnderstandingError("DEV answer-key cache incomplete; refusing unexpected Azure requests")
        if args.dry_run:
            summary = plan
        else:
            from .provider_protocol import require_foundry_ping
            require_foundry_ping(cfg)
            from .config import load_secrets
            load_secrets(cfg)
            summary = run(cfg, episodes, no_cache=args.no_cache, allow_held_out=args.allow_held_out)
        print(json.dumps(summary, sort_keys=True))
        return int(summary.get("status") == "failed" or summary.get("budget_covers_plan") is False)
    except Exception as exc:
        if hasattr(exc, "summary"):
            print(json.dumps(exc.summary, sort_keys=True))
        print("judge: failed; error=" + getattr(exc, "code", type(exc).__name__), file=sys.stderr)
        return 1
