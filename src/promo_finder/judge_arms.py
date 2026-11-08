"""Copy-only judge-arm preservation and count-only comparison of existing evidence."""

from __future__ import annotations

import hashlib
import copy
import json
import shutil
from pathlib import Path

from .run_context import digest
from .understanding_common import UnderstandingError, write_json


def inventory_sha256(entries):
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def archive_groq(cfg):
    """Freeze both old arms before the new judge can replace any DEV artifact."""
    target = cfg.root / "outputs/runs/dev/arms/groq"
    marker = target / "archive_manifest.json"
    if marker.is_file():
        saved = json.loads(marker.read_text(encoding="utf-8"))
        for rel, sha in saved["files_sha256"].items():
            if digest(target / rel) != sha:
                raise UnderstandingError("Groq archive hash mismatch")
        actual = {p.relative_to(target).as_posix() for p in target.rglob("*")
                  if p.is_file() and p != marker}
        if actual != set(saved["files_sha256"]) or inventory_sha256(saved["files_sha256"]) != saved["inventory_sha256"]:
            raise UnderstandingError("Groq archive file count or inventory mismatch")
        return {k: saved[k] for k in ("file_count", "file_count_by_arm", "inventory_sha256", "copy_not_move")}
    sources = []
    for arm, base in (("p05", cfg.root / "outputs"), ("p07", cfg.root / "outputs/runs/dev")):
        for stage in ("judge", "ranked", "logs"):
            source = base / stage
            if source.is_dir():
                for path in sorted(source.rglob("*")):
                    if path.is_symlink():
                        raise UnderstandingError("Groq archive refuses symbolic links")
                    if path.is_file():
                        path.resolve().relative_to(source.resolve())
                        sources.append((path, Path(arm) / stage / path.relative_to(source)))
        for name in ("run_manifest.json", "migration_manifest.json"):
            if (base / name).is_file():
                sources.append((base / name, Path(arm) / name))
    hashes = {rel.as_posix(): digest(source) for source, rel in sources}
    # Preflight every destination before writing; resume an identical partial copy safely.
    for source, rel in sources:
        destination = target / rel
        if destination.exists() and digest(destination) != hashes[rel.as_posix()]:
            raise UnderstandingError("Groq archive destination conflict")
    for source, rel in sources:
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(source, destination)
        if digest(source) != hashes[rel.as_posix()] or digest(destination) != hashes[rel.as_posix()]:
            raise UnderstandingError("Groq archive copy verification failed")
    counts = {arm: sum(rel.startswith(arm + "/") for rel in hashes) for arm in ("p05", "p07")}
    saved = {"copy_not_move": True, "file_count": len(hashes), "file_count_by_arm": counts,
             "inventory_sha256": inventory_sha256(hashes), "files_sha256": hashes}
    write_json(marker, saved)
    return archive_groq(cfg)


def cached_p07_items(cfg, candidates, log_rows):
    """Recover flushed caches even when the failed episode never wrote its output."""
    from . import judge_prompts as prompts
    from .judging import aggregate, short_fields
    from .llm import schema_errors, to_strict
    from .understanding import load_requested
    if not candidates or not log_rows:
        return {}
    root = cfg.root / "outputs/runs/dev/arms/groq/p07/judge"
    episodes = load_requested(cfg, sorted({item["candidate"]["episode"] for item in candidates.values()}))
    index = {line.id: line for episode in episodes for line in episode.lines}
    available = {r["purpose"]: r for r in log_rows if r.get("cache_key") and
                 r.get("model_key") == "groq_qwen" and not r.get("error") and
                 r.get("response_mode") == "json_object" and not r.get("cached") and
                 type(r.get("input_tokens")) is int}

    def cache(purpose, schema):
        row = available.get(purpose)
        if not row:
            return None
        try:
            value = json.loads((root / ".llm_cache" / (row["cache_key"] + ".json")).read_text(encoding="utf-8"))
            if value.get("model_string") == cfg.models["groq_qwen"].model and not schema_errors(value["data"], to_strict(schema)):
                return value
        except (OSError, KeyError, TypeError, ValueError):
            pass
        return None

    recovered = {}
    for key, current in candidates.items():
        candidate = current["candidate"]
        runs, used = [], set()
        expected = len(current["runs"])
        for number in range(expected):
            seed, order = prompts.shuffle(cfg.judge.shuffle_seed, key, number, used)
            used.add(tuple(order))
            _, schema, mapping = prompts.cold_request([index[line_id] for line_id in candidate["line_ids"]], order)
            hit = cache(f"p05.cold_judge.{key}.run{number+1}", schema)
            if not hit:
                runs.append({"status": "failed", "run": number + 1})
                continue
            data, _ = short_fields(copy.deepcopy(hit["data"]), prompts.READER_FIELDS)
            for q in prompts.QUESTIONS:
                data[q]["evidence"] = mapping[data[q]["evidence"]]
            runs.append({"status": "ok", "run": number + 1, "seed": seed, "question_order": order,
                         "answers": data, "metadata": {k: hit.get(k) for k in ("model_string", "response_mode", "validation_retry_used", "final_temperature")}})
        if not any(run["status"] == "ok" for run in runs):
            continue
        answer_key = None
        try:
            document = json.loads((root / f"answer_key_E{candidate['episode']:02d}.json").read_text(encoding="utf-8"))
            row = next(r for r in document["answers"] if r["promo_id"] == key)
            answer_key = {k: v for k, v in row.items() if k not in {"reference", "trims_by_field"}}
        except (OSError, ValueError, KeyError, StopIteration):
            pass
        item = {"promo_id": key, "reference": current["reference"], "candidate": candidate,
                "runs": runs, "aggregate": aggregate(runs, expected), "answer_key": answer_key,
                "fidelity": {"status": "skipped"}}
        if answer_key and runs[0]["status"] == "ok":
            _, schema = prompts.fidelity_request(answer_key, runs[0]["answers"])
            hit = cache(f"p05.fidelity.{key}", schema)
            if hit:
                item["fidelity"] = {"status": "ok", "matches": hit["data"]}
        recovered[key] = item
    return recovered


def compare_arms(cfg):
    """Compare latest complete P07 item evidence, otherwise P05; expose all denominators."""
    from .judge_prompts import QUESTIONS
    from .ranking import components, kendall_tau_b, load_formula
    root = cfg.root / "outputs/runs/dev/arms/groq"
    archive_groq(cfg)
    old, options = {}, {}
    log_path = root / "p07/logs/llm_calls.jsonl"
    log_rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()] if log_path.is_file() else []
    fresh_keys = {r.get("cache_key") for r in log_rows if r.get("model_key") == "groq_qwen" and r.get("response_mode") == "json_object"}
    # Whole item records are selected; runs from separate attempts are never pooled.
    for arm in ("p05", "p07"):
        for path in sorted((root / arm / "judge").glob("judge_E*.json")):
            for item in json.loads(path.read_text(encoding="utf-8"))["items"]:
                key = item["promo_id"]
                if item.get("aggregate", {}).get("successful_runs", 0):
                    if arm == "p07" and log_rows and not any(r.get("metadata", {}).get("cache_key") in fresh_keys for r in item.get("runs", [])):
                        continue  # copied P05 outputs are not new P07 evidence
                    old[key] = (item, arm)
                    options.setdefault(key, []).append((item, arm))
    new = {}
    for path in sorted((cfg.output_root / "judge").glob("judge_E*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if cfg.models[cfg.active.judge].provider == "azure_foundry" and document.get("model_key") != cfg.active.judge:
            raise UnderstandingError("official Azure judge outputs required before judge-swap comparison")
        for item in document["items"]:
            new[item["promo_id"]] = item
    for key, item in cached_p07_items(cfg, new, log_rows).items():
        old[key] = (item, "p07_cache")
        options.setdefault(key, []).append((item, "p07_cache"))
    common = [key for key in sorted(set(old) & set(new))
              if old[key][0].get("candidate") == new[key].get("candidate")]
    questions = {}
    for q in QUESTIONS:
        pairs = [(old[key][0]["aggregate"]["answers"].get(q), new[key]["aggregate"]["answers"].get(q)) for key in common]
        valid = [(a, b) for a, b in pairs if a in {"yes", "no"} and b in {"yes", "no"}]
        agree = sum(a == b for a, b in valid)
        questions[q] = {"agree": agree, "assessed": len(valid), "agreement": agree / len(valid) if valid else None}
    formula, _ = load_formula(cfg)
    xs, ys, scored_ids, score_sources = [], [], [], {}
    for key in common:
        if new[key].get("reference"):
            continue
        scored_old = [(components(item["candidate"], item, formula), arm) for item, arm in options[key]
                      if item.get("candidate") == new[key].get("candidate")]
        valid_old = [(values, arm) for values, arm in scored_old if values is not None]
        a, source = valid_old[-1] if valid_old else (None, None)
        b = components(new[key]["candidate"], new[key], formula)
        if a is not None and b is not None:
            xs.append(a["S"])
            ys.append(b["S"])
            scored_ids.append(key)
            score_sources[key] = source
    result = {"comparison": "Groq-Qwen vs Azure-Llama", "common_items": len(common),
              "groq_source_by_item": {key: old[key][1] for key in common}, "questions": questions,
              "kendall_S": kendall_tau_b(xs, ys), "common_scored_current_ids": scored_ids,
              "groq_score_source_by_item": score_sources,
              "basis": "same candidate identity; questions use latest available P07 aggregate/cache, otherwise P05; S uses latest complete evidence; no cross-attempt pooling"}
    write_json(cfg.output_root / "judge/judge_swap_agreement.json", result)
    return result
