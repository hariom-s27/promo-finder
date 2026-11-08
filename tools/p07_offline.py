"""Count-only P07 migration, DEV preflight, and pilot extrapolation. No calls."""

from __future__ import annotations

import argparse
import json
import subprocess

from promo_finder.config import load_config
from promo_finder.estimation import estimate_50
from promo_finder.judging import dry_run, prepare
from promo_finder.labelling import parse_eps
from promo_finder.run_context import digest, fingerprints, for_run, manifest, migrate_dev
from promo_finder.understanding import DEV_SPEC, load_requested
from promo_finder.understanding_common import UnderstandingError, write_json

EXISTING_FROZEN = ("eval/match_rule.md", "eval/gold_rubric.md", "eval/gold_template.csv", "eval/HASHES.md", "config/score_formula.yaml")


def verify_frozen(cfg):
    import hashlib
    result = {}
    for rel in EXISTING_FROZEN:
        old = subprocess.run(["git", "show", "HEAD:" + rel], cwd=cfg.root, capture_output=True)
        if old.returncode:
            raise UnderstandingError("frozen file missing in HEAD")
        sha = digest(cfg.root / rel)
        if sha != hashlib.sha256(old.stdout).hexdigest():
            raise UnderstandingError("existing frozen file changed")
        result[rel] = sha
    return result


def verify_dev(cfg):
    episodes = load_requested(cfg, parse_eps(DEV_SPEC))
    prepared = prepare(cfg, episodes)
    plan = dry_run(cfg, episodes, prepared)
    if plan["current_items"] != 39 or plan["reference_items"] != 6:
        raise UnderstandingError("DEV candidate count changed")
    if plan["answer_key_cache"]["valid_cache_hits"] != 8:
        raise UnderstandingError("expected eight valid Azure cache hits")
    result = {"status": "passed", "plan": plan, "existing_frozen_sha256": verify_frozen(cfg), **fingerprints(cfg, required=True)}
    write_json(cfg.output_root / "judge/p07_preflight.json", result)
    return result


def verify_worktree(cfg):
    """Use the existing leak guard on changed paths without staging anything."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("p07_leak_guard", cfg.root / "tools/guard.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    changed = subprocess.run(["git", "diff", "--name-only", "--diff-filter=ACMR", "-z"], cwd=cfg.root, capture_output=True, check=True)
    added = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=cfg.root, capture_output=True, check=True)
    paths = sorted(set(p.decode("utf-8") for p in (changed.stdout + added.stdout).split(b"\0") if p))
    if guard.path_problems(paths):
        raise UnderstandingError("worktree guard refused a blocked path; contents were not read")
    data_dir = guard.resolve_data_dir(cfg.root, None)
    if not data_dir or not data_dir.is_dir():
        raise UnderstandingError("guard data source missing")
    shingles = guard.build_shingles(data_dir)
    hits = checked = 0
    for rel in paths:
        path = cfg.root / rel
        if guard.is_env_file(rel) or not path.is_file():
            continue
        content = path.read_bytes()
        if b"\0" in content[:8000]:
            continue
        checked += 1
        hits += bool(guard.scan_text(content.decode("utf-8", errors="replace"), shingles))
    result = {"status": "clean" if not hits else "failed", "files_checked": checked, "files_with_content_hits": hits,
              "mode": "changed worktree; existing guard functions; no staging"}
    write_json(cfg.output_root / "judge/p07_worktree_guard.json", result)
    if hits:
        raise UnderstandingError("worktree content guard failed; no matched text printed")
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("migrate-dev", "verify-dev", "estimate-50", "verify-frozen", "verify-worktree"))
    ap.add_argument("--run", default="dev")
    args = ap.parse_args(argv)
    cfg = for_run(load_config(), args.run)
    if args.action == "migrate-dev":
        result = migrate_dev(cfg)
        manifest(cfg, parse_eps(DEV_SPEC), migration=result)
    elif args.action == "verify-dev":
        result = verify_dev(cfg)
    elif args.action == "verify-frozen":
        result = {"sha256": verify_frozen(cfg), **fingerprints(cfg, required=True)}
    elif args.action == "verify-worktree":
        result = verify_worktree(cfg)
    else:
        saved = json.loads((cfg.output_root / "run_manifest.json").read_text(encoding="utf-8"))
        build = json.loads((cfg.output_root / "promos/build_summary.json").read_text(encoding="utf-8"))
        result = estimate_50(cfg, saved, build)
        write_json(cfg.output_root / "estimate_50.json", result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
