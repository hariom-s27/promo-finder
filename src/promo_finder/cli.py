"""Command line for parsing, labelling, checking and the optional model ping.

Prints counts only, never script text, names or keys.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import Config, ConfigError, load_config, load_secrets, secret_values

PING_MESSAGES = [{"role": "user", "content": 'Reply with JSON {"ok": true}.'}]
PING_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}},
               "required": ["ok"], "additionalProperties": False}
GROQ_WATCH = ("qwen/qwen3.8-27b", "openai/gpt-oss-120b")


def cmd_parse(cfg: Config, args) -> int:
    from .parser import parse_dir
    from .validate import build_parse_report

    data_dir = Path(args.data_dir) if args.data_dir else cfg.data_dir
    if not data_dir.is_dir():
        print("data_dir not found (set data_dir in config.yaml or KUKU_DATA_DIR)", file=sys.stderr)
        return 2
    episodes, file_warnings = parse_dir(data_dir)
    report = build_parse_report(episodes, file_warnings)
    out = cfg.root / "outputs"
    parsed = out / "parsed"
    parsed.mkdir(parents=True, exist_ok=True)
    for e in episodes:
        (parsed / f"E{e.ep:02d}.json").write_text(e.model_dump_json(indent=1), encoding="utf-8")
    (out / "parse_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    t = report["totals"]
    print(f"episodes={t['episodes']} scenes={t['scenes']} lines={t['lines']} "
          f"total_duration_ms={t['total_duration_ms']} distinct_speakers={t['distinct_speakers']}")
    print("lines_by_kind: " + json.dumps(t["lines_by_kind"]))
    print("warnings_by_code: " + json.dumps(t["warnings_by_code"]))
    print("file_warnings_by_code: " + json.dumps(t["file_warnings_by_code"]))
    print("validator: " + json.dumps(t["validator"]))
    print("wrote outputs/parsed/E##.json and outputs/parse_report.json")
    return 0


def _load_episodes(cfg: Config, args):
    from .parser import parse_dir

    data_dir = Path(args.data_dir) if args.data_dir else cfg.data_dir
    if not data_dir.is_dir():
        print("data_dir not found (set data_dir in config.yaml or KUKU_DATA_DIR)", file=sys.stderr)
        return None
    episodes, _ = parse_dir(data_dir)
    return episodes


def _split_of(args):
    from .labelling import SPLITS

    return SPLITS[getattr(args, "split", None) or "held-out"]


def cmd_list_lines(cfg: Config, args) -> int:
    from .labelling import HELD_OUT_SPEC, SPLITS, parse_eps, write_labelling

    sealed = {name: s for name, s in SPLITS.items() if name != "held-out"}   # fresh blocks A and B
    chosen = getattr(args, "split", None)
    split = sealed.get(chosen)
    try:
        eps = parse_eps(args.eps or (split.spec if split else HELD_OUT_SPEC))
    except ValueError as e:
        print(f"--eps: {e}", file=sys.stderr)
        return 2
    if split and set(eps) - set(split.episodes):
        print(f"--eps: the {split.name} split covers episodes {split.spec} only", file=sys.stderr)
        return 2
    if split is None:
        touched = [s for s in sealed.values() if set(eps) & set(s.episodes)]
        if touched:
            if len(touched) > 1 or set(eps) - set(touched[0].episodes):
                print("--eps: sealed fresh episodes (" + ", ".join(s.spec for s in touched)
                      + ") cannot be mixed with others; use --split", file=sys.stderr)
                return 2
            split = touched[0]  # --eps alone inside one fresh split is routed to that split's folder
    episodes = _load_episodes(cfg, args)
    if episodes is None:
        return 2
    out_dir = cfg.root / "outputs" / "labelling" / (split.subdir if split else "")
    written, missing = write_labelling(episodes, eps, out_dir)
    for p, rows, scenes in written:
        print(f"{p.relative_to(cfg.root).as_posix()} rows={rows} scenes={scenes}")
    print(f"written: {len(written)} files")
    if missing:
        print("not found: " + ",".join(str(n) for n in missing), file=sys.stderr)
    return 0


def cmd_check_gold(cfg: Config, args) -> int:
    from .checker import build_index
    from .gold import check_sheet, format_report, read_sheet

    path = Path(args.csv)
    if not path.is_file():
        print(f"file not found: {path}", file=sys.stderr)
        return 2
    header, rows, file_warnings = read_sheet(path)
    episodes = _load_episodes(cfg, args)
    if episodes is None:
        return 2
    index = build_index(episodes)
    speakers = {ln.speaker for e in episodes for ln in e.lines if ln.speaker}
    split = _split_of(args)
    rep = check_sheet(header, rows, index, speakers, cfg, split)
    for line in format_report(rep, file_warnings, split):
        print(line)
    return 0 if rep.ok else 1


def cmd_make_workbook(cfg: Config, args) -> int:
    from openpyxl.utils.exceptions import IllegalCharacterError

    from .workbook import WorkbookError, template_header, write_workbook

    split = _split_of(args)
    out = cfg.root / Path(args.out or split.default_workbook)
    if out.exists() and not args.force:
        print("refused: workbook already exists; use --force only to replace it deliberately", file=sys.stderr)
        return 1
    episodes = _load_episodes(cfg, args)
    if episodes is None:
        return 2
    try:
        eps, rows, scenes = write_workbook(episodes, out, template_header(cfg.root), args.force, split)
    except FileExistsError:
        print("refused: workbook already exists; use --force only to replace it deliberately", file=sys.stderr)
        return 1
    except WorkbookError as e:
        print(f"make-workbook: {e}", file=sys.stderr)
        return 1
    except (OSError, ValueError, IllegalCharacterError):
        print("make-workbook: unable to write workbook; check output access and source format", file=sys.stderr)
        return 1
    try:
        shown = out.relative_to(cfg.root).as_posix()
    except ValueError:
        shown = str(out)
    print(f"{shown} episode_sheets={eps} line_rows={rows} scene_rows={scenes}")
    return 0


def cmd_export_gold(cfg: Config, args) -> int:
    from zipfile import BadZipFile

    from .workbook import WorkbookError, export_labels, template_header

    split = _split_of(args)
    xlsx = cfg.root / Path(args.xlsx or split.default_workbook)
    out = cfg.root / Path(args.out or split.default_gold)
    try:
        export_labels(xlsx, out, template_header(cfg.root), cfg.root / "eval" / "HASHES.md")
    except WorkbookError as e:
        print(f"export-gold: {e}", file=sys.stderr)
        return 1
    except (OSError, BadZipFile, KeyError, ValueError):
        print("export-gold: unable to read workbook or write CSV; check paths and file access", file=sys.stderr)
        return 1
    return cmd_check_gold(cfg, argparse.Namespace(csv=str(out), data_dir=args.data_dir, split=split.name))


def _scrub(cfg: Config, text: str) -> str:
    for v in secret_values(cfg):
        text = text.replace(v, "***")
    return text


def cmd_ping(cfg: Config, args) -> int:
    from .llm import LLMClient, LLMError, estimate_tokens, _prompt_text, to_strict

    if getattr(args, "models", None):
        return cmd_targeted_ping(cfg, args)
    if not args.dry_run:
        load_secrets(cfg)
    client = LLMClient(cfg, dry_run=args.dry_run)
    results = []
    for key, m in cfg.models.items():
        row = {"model_key": key, "provider": m.provider, "model": m.model}
        if m.is_tbd:
            row["status"] = "skipped (TBD)"
            print(f"{key:18s} skipped (TBD)")
            results.append(row)
            continue
        p = cfg.providers[m.provider]
        missing = [] if args.dry_run else [n for n in p.env_names() if not os.environ.get(n)]
        if missing:
            row["status"] = "skipped (no key)"
            print(f"{key:18s} skipped (no key: {', '.join(missing)})")
            results.append(row)
            continue
        if args.dry_run:
            est = estimate_tokens(_prompt_text(PING_MESSAGES, to_strict(PING_SCHEMA)))
            row.update(status="planned", est_input_tokens=est,
                       max_completion_tokens=m.params.get("max_completion_tokens"))
            where = "azure v1 (fallback: AzureOpenAI api_version=" + str(p.fallback_api_version) + ")" if p.is_azure else p.base_url
            print(f"{key:18s} PLANNED 1 call  provider={m.provider} model={m.model} via {where} "
                  f"params={json.dumps(m.params)} est_input_tokens~{est}")
            results.append(row)
            continue
        try:
            r = client.call(key, PING_MESSAGES, PING_SCHEMA, purpose="ping", no_cache=args.no_cache)
            row.update(status="ok" if r.data == {"ok": True} else "ok (unexpected value)",
                       model_string=r.model_string, input_tokens=r.usage.input_tokens,
                       output_tokens=r.usage.output_tokens, latency_ms=r.latency_ms,
                       cached=r.cached, api_path=r.api_path)
        except LLMError as e:
            row.update(status="error", error_code=e.code, error=_scrub(cfg, str(e))[:300])
        results.append(row)
        print(f"{key:18s} " + json.dumps({k: v for k, v in row.items() if k != 'model_key'}))

    groq = cfg.providers.get("groq")
    groq_info: dict = {}
    if groq and os.environ.get(groq.key_env):
        if args.dry_run:
            print(f"groq /models     PLANNED free GET {groq.base_url}/models")
        else:
            try:
                import openai

                c = openai.OpenAI(base_url=groq.base_url, api_key=os.environ[groq.key_env], max_retries=1, timeout=30)
                ids = sorted(x.id for x in c.models.list())
                groq_info = {"ids": ids, **{w: (w in ids) for w in GROQ_WATCH}}
                print(f"groq /models ({len(ids)}): " + ", ".join(ids))
                for w in GROQ_WATCH:
                    print(f"  {w}: {'PRESENT' if w in ids else 'MISSING'}")
            except Exception as e:
                groq_info = {"error": _scrub(cfg, f"{type(e).__name__}: {e}")[:300]}
                print("groq /models error: " + groq_info["error"])
    else:
        print("groq /models     skipped (no key)")

    if not args.dry_run:
        out = cfg.output_root
        out.mkdir(parents=True, exist_ok=True)
        (out / "ping_results.json").write_text(json.dumps({"models": results, "groq_models": groq_info,
                                                           "calls_made": client.calls_made}, indent=2), encoding="utf-8")
        print(f"real requests made: {client.calls_made}; wrote outputs/ping_results.json")
    return 0


def targeted_ping_budget(cfg, keys):
    import math
    # Foundry can negotiate two unsupported parameters and validate one retry;
    # five slots also allow the consecutive-429 stop to report its real cause.
    return sum(5 if cfg.models[key].provider == "azure_foundry" else math.ceil(1.2) for key in keys) if any(
        cfg.models[key].provider == "azure_foundry" for key in keys) else math.ceil(len(keys) * 1.2)


def cmd_targeted_ping(cfg: Config, args) -> int:
    import math
    from .judging import call_accounting, purpose_options
    from .llm import LLMClient, LLMError, MissingKey
    from .understanding_common import metadata, write_json

    keys = [key.strip() for key in args.models.split(",")]
    if (not keys or len(keys) != len(set(keys)) or
            any(key not in {"groq_qwen", "featherless_llama", "azure_llama"} or key not in cfg.usable_models() for key in keys)):
        print("ping: invalid target selection", file=sys.stderr)
        return 1
    if args.dry_run:
        from .llm import estimate_tokens, _prompt_text, json_messages, to_strict
        requests = {}
        for key in keys:
            foundry = cfg.models[key].provider == "azure_foundry"
            options = purpose_options(cfg, "cold_judge" if foundry else "ping")
            requests[key] = {"initial_response_format": {"type": "json_object"} if foundry else None,
                             "temperature": cfg.judge.temperature if foundry else None,
                             "max_output_tokens": options.get("max_completion_tokens"),
                             "estimated_input_tokens": estimate_tokens(_prompt_text(json_messages(
                                 [{"role": "user", "content": "Return only JSON with ok set to true."}], to_strict(PING_SCHEMA)), {}))}
        print(json.dumps({"planned_ping_models": keys, "calls": len(keys), "max_calls_per_run": targeted_ping_budget(cfg, keys), "requests": requests}))
        return 0
    cfg = cfg.model_copy(deep=True)
    cfg.max_calls_per_run = targeted_ping_budget(cfg, keys)
    if any(cfg.models[key].provider == "azure_foundry" for key in keys):
        from .run_context import fingerprints
        fingerprints(cfg, required=True)
        if cfg.run_name == "dev":
            from .judge_arms import archive_groq
            archive_groq(cfg)
    load_secrets(cfg)
    client = LLMClient(cfg, cache_dir=cfg.output_root / "judge/.llm_cache")
    rows = []
    status = 0
    for key in keys:
        model = cfg.models[key]
        foundry = model.provider == "azure_foundry"
        purpose = f"p07.ping.{key}" if foundry else f"p05.ping.{key}"
        row = {"model_key": key, "provider": model.provider, "deployment": model.model,
               "credential_set": "azure_openai" if model.provider == "azure" else model.provider,
               "credential_variable_names": cfg.providers[model.provider].env_names()}
        options = purpose_options(cfg, "cold_judge" if foundry else "ping")
        if foundry:
            options.update(temperature=cfg.judge.temperature, retry_temperature=cfg.judge.retry_temperature)
        try:
            result = client.call(key, [{"role": "user", "content": "Return only JSON with ok set to true."}],
                PING_SCHEMA, purpose=purpose, no_cache=True if foundry else args.no_cache,
                response_validator=lambda data: [] if data["ok"] is True else ["$.ok: expected true"],
                **options)
            row.update(status="ok", **metadata(result, response_mode=result.response_mode))
            if foundry:
                row["protocol"] = client.protocol(key)
        except LLMError as exc:
            row.update(status="failed", error_code=exc.code, exact_error_code=exc.code)
            if isinstance(exc, MissingKey):
                row["missing_variable_name"] = exc.variable_name
            failed = [r["error"] for r in client.records if r.get("purpose") == purpose and
                      r.get("event") == "http_attempt_failed"]
            row["http_errors"] = {code: failed.count(code) for code in sorted(set(failed))}
            attempts = [r for r in client.records if r.get("purpose") == purpose and r.get("event") == "http_attempt_failed"]
            if attempts:
                row.update({name: attempts[-1].get(name) for name in ("http_status_code", "provider_error_code", "endpoint_form")})
                row["exact_error_code"] = attempts[-1]["error"]
            elif client.records:
                row["exact_error_code"] = client.records[-1].get("error") or exc.code
            status = 1
        rows.append(row)
        write_json(cfg.output_root / f"judge/ping_{key}.json", row)
        write_json(cfg.output_root / "judge/pings.json", {"models": rows,
            "max_calls_per_run": cfg.max_calls_per_run,
            "failed_runs": sum(row["status"] == "failed" for row in rows), "llm": call_accounting(client.records, cfg)})
        print(row["missing_variable_name"] if row.get("missing_variable_name") else json.dumps(row, sort_keys=True))
        if status and (args.fail_fast or key in {"groq_qwen", cfg.active.judge}):
            break
    return status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="promo_finder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse", help="parse every episode in data_dir")
    p.add_argument("--data-dir", help="override data_dir")
    q = sub.add_parser("ping", help="one tiny call per configured model")
    q.add_argument("--no-cache", action="store_true", help="bypass the LLM cache")
    q.add_argument("--dry-run", action="store_true", help="estimate tokens, make no calls")
    q.add_argument("--models", help="targeted pings: azure_llama,groq_qwen,featherless_llama")
    q.add_argument("--fail-fast", action="store_true", help="stop after a failed targeted ping")
    from .labelling import HELD_OUT_SPEC

    split_help = ("label split (default held-out); fresh = episodes 31-34 and fresh_b = the block B episodes, "
                  "files under outputs/labelling/fresh/ and fresh_b/")
    ll = sub.add_parser("list-lines", help="write outputs/labelling/E##_lines.md (labelling aid)")
    ll.add_argument("--eps", default=None, help=f"episode list/ranges (default {HELD_OUT_SPEC}; 31-34 with --split fresh)")
    ll.add_argument("--split", choices=("held-out", "fresh", "fresh_b"), default=None, help=split_help)
    ll.add_argument("--data-dir", help="override data_dir")
    cg = sub.add_parser("check-gold", help="validate a gold label sheet (eval/gold_rubric.md)")
    cg.add_argument("csv", help="path to the gold CSV")
    cg.add_argument("--split", choices=("held-out", "fresh", "fresh_b"), default=None, help=split_help)
    cg.add_argument("--data-dir", help="override data_dir")
    mw = sub.add_parser("make-workbook", help="create an Excel workbook for held-out (or fresh) labelling")
    mw.add_argument("--out", default=None, help="default per split")
    mw.add_argument("--split", choices=("held-out", "fresh", "fresh_b"), default=None, help=split_help)
    mw.add_argument("--data-dir", help="override data_dir")
    mw.add_argument("--force", action="store_true", help="deliberately replace an existing workbook")
    eg = sub.add_parser("export-gold", help="export LABELS columns A-M and run check-gold")
    eg.add_argument("--xlsx", default=None, help="default per split")
    eg.add_argument("--out", default=None, help="default per split (eval/gold.csv or eval/gold_fresh.csv)")
    eg.add_argument("--split", choices=("held-out", "fresh", "fresh_b"), default=None, help=split_help)
    eg.add_argument("--data-dir", help="override data_dir")
    from .understanding import DEV_SPEC, cmd_understand

    understand = sub.add_parser("understand", help="build understanding for requested episodes (DEV by default)")
    understand.add_argument("--eps", default=DEV_SPEC)
    understand.add_argument("--dry-run", action="store_true", help="estimate calls/tokens/cost without AI calls")
    understand.add_argument("--allow-held-out", action="store_true", help="explicitly override the held-out seal")
    understand.add_argument("--no-cache", action="store_true", help="bypass the LLM cache")
    from .finding import cmd_find
    from .builder import cmd_build

    find = sub.add_parser("find", help="find reveal and moment pointers (DEV by default)")
    find.add_argument("--eps", default=DEV_SPEC)
    find.add_argument("--dry-run", action="store_true", help="estimate without secrets or calls")
    find.add_argument("--no-cache", action="store_true", help="bypass the LLM cache")
    find.add_argument("--allow-held-out", action="store_true", help="explicitly override the held-out seal")
    build = sub.add_parser("build", help="build validated promos without AI calls")
    build.add_argument("--eps", default=DEV_SPEC)
    build.add_argument("--allow-held-out", action="store_true", help="explicitly override the held-out seal")
    from .judging import cmd_judge
    from .ranking import cmd_rank
    judge = sub.add_parser("judge", help="answer keys, cold judging and DEV reference check")
    judge.add_argument("--eps", default=DEV_SPEC)
    judge.add_argument("--dry-run", action="store_true", help="count-only preflight without secrets or requests")
    judge.add_argument("--no-cache", action="store_true")
    judge.add_argument("--allow-held-out", action="store_true")
    rank = sub.add_parser("rank", help="rank previously judged candidates without AI calls")
    rank.add_argument("--eps", default=DEV_SPEC)
    rank.add_argument("--allow-held-out", action="store_true")
    from .baseline import cmd_baseline
    from .pipeline import cmd_run
    baseline = sub.add_parser("baseline", help="frozen free-timestamp baseline")
    pipeline = sub.add_parser("run", help="run the complete pipeline in one run folder")
    for command in (baseline, pipeline):
        command.add_argument("--eps", required=True)
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--no-cache", action="store_true")
        command.add_argument("--allow-held-out", action="store_true")
    for command in (q, understand, find, build, judge, rank, baseline, pipeline):
        command.add_argument("--run", default="dev", help="output run name (default dev)")
    for command in (build, rank, pipeline):
        command.add_argument("--config-overlay", default=None,
                             help="whitelisted overlay file (e.g. config/v2.yaml); only builder switches can change")
    args = ap.parse_args(argv)
    try:
        overlay = getattr(args, "config_overlay", None)
        cfg = load_config(overlay=overlay) if overlay else load_config()
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    cmds = {"parse": cmd_parse, "ping": cmd_ping, "list-lines": cmd_list_lines, "check-gold": cmd_check_gold,
            "make-workbook": cmd_make_workbook, "export-gold": cmd_export_gold, "understand": cmd_understand,
            "find": cmd_find, "build": cmd_build, "judge": cmd_judge, "rank": cmd_rank,
            "baseline": cmd_baseline, "run": cmd_run}
    if hasattr(args, "run"):
        from .run_context import for_run
        try:
            cfg = for_run(cfg, args.run)
            if args.cmd != "ping":
                from .finding import check_selection
                from .labelling import parse_eps
                check_selection(parse_eps(args.eps), args.allow_held_out)
        except Exception as exc:
            if getattr(exc, "code", None) == "HELD_OUT_REFUSED":
                print(f"{args.cmd}: refused: held-out episodes require --allow-held-out; error=HELD_OUT_REFUSED", file=sys.stderr)
            else:
                print(f"{args.cmd}: refused; error=" + getattr(exc, "code", type(exc).__name__), file=sys.stderr)
            return 1
    if args.cmd in {"understand", "find", "build", "judge", "rank", "baseline", "ping"} and not getattr(args, "dry_run", False):
        return recorded_command(cfg, args, cmds[args.cmd])
    return cmds[args.cmd](cfg, args)


def recorded_command(cfg, args, command):
    """Record standalone stage accounting without exposing generated content."""
    import time
    from .accounting import summarize
    from .labelling import parse_eps
    from .run_context import manifest
    log = cfg.output_root / "logs/llm_calls.jsonl"
    offset = log.stat().st_size if log.exists() else 0
    started = time.monotonic()
    eps = parse_eps(args.eps) if hasattr(args, "eps") else []
    try:
        result = command(cfg, args)
        return result
    finally:
        records = []
        if log.exists():
            with log.open("rb") as stream:
                stream.seek(offset)
                records = [json.loads(line) for line in stream if line.strip()]
        path = cfg.output_root / "run_manifest.json"
        previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        stages = previous.get("stages", {})
        stage_name = "ping:" + args.models if args.cmd == "ping" and getattr(args, "models", None) else args.cmd
        stages[stage_name] = {"status": "RATE_LIMITED" if any(r.get("error") == "RATE_LIMITED" for r in records) else "complete" if locals().get("result") == 0 else "failed",
                            "wall_time_s": time.monotonic() - started, "llm": summarize(records, cfg)}
        extra = {}
        summary = cfg.output_root / "judge/judge_summary.json"
        if args.cmd == "judge" and summary.exists():
            extra["max_calls_per_run"] = json.loads(summary.read_text(encoding="utf-8"))["preflight"]["max_calls_per_run"]
        if args.cmd == "ping" and getattr(args, "models", None):
            extra["max_calls_per_run"] = targeted_ping_budget(cfg, args.models.split(","))
        baseline_summary = cfg.output_root / "baseline/baseline_summary.json"
        if args.cmd == "baseline" and baseline_summary.exists():
            extra["max_calls_per_run"] = json.loads(baseline_summary.read_text(encoding="utf-8"))["max_calls_per_run"]
        extra["returned_model_strings"] = sorted(set(previous.get("returned_model_strings", [])) |
                                                   {r["model_string"] for r in records if r.get("model_string")})
        manifest(cfg, eps or previous.get("episodes", []), stages=stages, **extra)
