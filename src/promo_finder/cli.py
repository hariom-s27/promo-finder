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


def cmd_list_lines(cfg: Config, args) -> int:
    from .labelling import parse_eps, write_labelling

    try:
        eps = parse_eps(args.eps)
    except ValueError as e:
        print(f"--eps: {e}", file=sys.stderr)
        return 2
    episodes = _load_episodes(cfg, args)
    if episodes is None:
        return 2
    out_dir = cfg.root / "outputs" / "labelling"
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
    rep = check_sheet(header, rows, index, speakers, cfg)
    for line in format_report(rep, file_warnings):
        print(line)
    return 0 if rep.ok else 1


def cmd_make_workbook(cfg: Config, args) -> int:
    from openpyxl.utils.exceptions import IllegalCharacterError

    from .workbook import WorkbookError, template_header, write_workbook

    out = cfg.root / Path(args.out)
    if out.exists() and not args.force:
        print("refused: workbook already exists; use --force only to replace it deliberately", file=sys.stderr)
        return 1
    episodes = _load_episodes(cfg, args)
    if episodes is None:
        return 2
    try:
        eps, rows, scenes = write_workbook(episodes, out, template_header(cfg.root), args.force)
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

    xlsx, out = cfg.root / Path(args.xlsx), cfg.root / Path(args.out)
    try:
        export_labels(xlsx, out, template_header(cfg.root), cfg.root / "eval" / "HASHES.md")
    except WorkbookError as e:
        print(f"export-gold: {e}", file=sys.stderr)
        return 1
    except (OSError, BadZipFile, KeyError, ValueError):
        print("export-gold: unable to read workbook or write CSV; check paths and file access", file=sys.stderr)
        return 1
    return cmd_check_gold(cfg, argparse.Namespace(csv=str(out), data_dir=args.data_dir))


def _scrub(cfg: Config, text: str) -> str:
    for v in secret_values(cfg):
        text = text.replace(v, "***")
    return text


def cmd_ping(cfg: Config, args) -> int:
    from .llm import LLMClient, LLMError, estimate_tokens, _prompt_text, to_strict

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
        missing = [n for n in p.env_names() if not os.environ.get(n)]
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
        out = cfg.root / "outputs"
        out.mkdir(parents=True, exist_ok=True)
        (out / "ping_results.json").write_text(json.dumps({"models": results, "groq_models": groq_info,
                                                           "calls_made": client.calls_made}, indent=2), encoding="utf-8")
        print(f"real requests made: {client.calls_made}; wrote outputs/ping_results.json")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="promo_finder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parse", help="parse every episode in data_dir")
    p.add_argument("--data-dir", help="override data_dir")
    q = sub.add_parser("ping", help="one tiny call per configured model")
    q.add_argument("--no-cache", action="store_true", help="bypass the LLM cache")
    q.add_argument("--dry-run", action="store_true", help="estimate tokens, make no calls")
    from .labelling import HELD_OUT_SPEC

    ll = sub.add_parser("list-lines", help="write outputs/labelling/E##_lines.md (labelling aid)")
    ll.add_argument("--eps", default=HELD_OUT_SPEC, help=f"episode list/ranges (default {HELD_OUT_SPEC})")
    ll.add_argument("--data-dir", help="override data_dir")
    cg = sub.add_parser("check-gold", help="validate a gold label sheet (eval/gold_rubric.md)")
    cg.add_argument("csv", help="path to the gold CSV")
    cg.add_argument("--data-dir", help="override data_dir")
    mw = sub.add_parser("make-workbook", help="create an Excel workbook for held-out labelling")
    mw.add_argument("--out", default="outputs/labelling/gold_labelling.xlsx")
    mw.add_argument("--data-dir", help="override data_dir")
    mw.add_argument("--force", action="store_true", help="deliberately replace an existing workbook")
    eg = sub.add_parser("export-gold", help="export LABELS columns A-M and run check-gold")
    eg.add_argument("--xlsx", default="outputs/labelling/gold_labelling.xlsx")
    eg.add_argument("--out", default="eval/gold.csv")
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
    args = ap.parse_args(argv)
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    cmds = {"parse": cmd_parse, "ping": cmd_ping, "list-lines": cmd_list_lines, "check-gold": cmd_check_gold,
            "make-workbook": cmd_make_workbook, "export-gold": cmd_export_gold, "understand": cmd_understand,
            "find": cmd_find, "build": cmd_build}
    return cmds[args.cmd](cfg, args)
