#!/usr/bin/env python
"""Score sealed fresh blocks separately, once each; held-out v2 is post-hoc.

No network or LLM client. All outputs contain numbers and IDs only. Use
`verify`, `score --block a`, `score --block b`, then `held-out`.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from promo_finder import evaluation_lists as E, gold as G, scoring as S  # noqa: E402
from promo_finder.checker import build_index  # noqa: E402
from promo_finder.config import load_config  # noqa: E402
from promo_finder.labelling import FRESH_SPLIT, FRESH_B_SPLIT, HELD_OUT_SPLIT  # noqa: E402
from promo_finder.parser import parse_dir  # noqa: E402

V1, V2 = "outputs/runs/full", "outputs/runs/full_v2"
EVALUATION = f"{V2}/evaluation"
SEAL_SHA = "b5ed3ab3a7e62a90302f0a806aba6a641abf146220945a0e566825a8e4ea9bbb"
P08_SHA = "23f5aa90e8c691633da71f3aaf7e17bc64b10dd37f6e8891d9b5155a2cd1f927"
REQUIRED_HASHES = {
    "eval/match_rule.md", "eval/gold_rubric.md", "eval/gold_template.csv", "eval/gold.csv",
    "outputs/gold_sealed/gold_longlist_v1.csv", "outputs/ai_labels/claude_v1.csv",
    "outputs/ai_labels/gpt_v1.csv", "config/score_formula.yaml", "config/eval_order.yaml",
    "config/baseline.yaml", "config/v2.yaml", "eval/match_rule_fresh.md",
    "eval/match_rule_fresh_b.md", "eval/gold_fresh.csv", "eval/gold_fresh_b.csv",
}
BLOCKS = {"a": (FRESH_SPLIT, 8, 2, "fresh"), "b": (FRESH_B_SPLIT, 4, 1, "fresh_b"),
          "held_out": (HELD_OUT_SPLIT, 16, 6, "held_out")}
DEFINITIONS = {
    "recall_at_K": "greedy one-to-one matches / positive gold; K=2*|G|; primary tau=0.5",
    "matching": "rank order through K; highest set tIoU; ties lowest gold_id; integer milliseconds",
    "hook_hit": "matched at tau=0.5 and first-segment start within 2000 ms in same episode / |G|",
    "hook_found": "hook-only greedy matches in top K / |G|; closest start, then lowest gold_id",
    "precision_at_10": "matches from top-K greedy matching at positions <=10 / min(10,|L|); K<10 stays unchanged",
    "negative_hit_rate": "negatives overlapping any top-K prediction at tIoU>=0.5 / negative gold; not one-to-one",
    "recall_by_grade": "matched positives / positives of each grade; descriptive",
    "wilson95": "Wilson 95%, z=1.959964; n=0 is undefined",
    "paired": "aligned per-gold vectors; exact two-sided McNemar; paired bootstrap B=10000, seed=12345, linear percentile 95%",
    "baseline_sensitivity": "stored snapped baseline order with 20-60 s check off, restricted to the block",
}


class Stop(ValueError):
    """Fail closed; never repair or reseal an evaluation input."""


def jload(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path, lf=False):
    data = path.read_bytes()
    return hashlib.sha256(data.replace(b"\r\n", b"\n") if lf else data).hexdigest()


def require(ok, message):
    if not ok:
        raise Stop(message)


def verify(root=ROOT, seal_sha=SEAL_SHA, p08_sha=P08_SHA):
    """Verify every hash row before reading any labels as CSV or any list as JSON."""
    rows, by_path = [], {}
    for line in (root / "eval/HASHES.md").read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| File "):
            continue
        c = [x.strip() for x in line.strip("|").split("|")]
        require(len(c) >= 3 and re.fullmatch(r"[0-9a-f]{64}", c[1]), "malformed HASHES row")
        rel, digest = c[:2]
        path = root / rel
        require(path.resolve().is_relative_to(root.resolve()), "HASHES path outside repository")
        require(path.is_file() and sha(path, lf=True) == digest, "HASHES mismatch: " + rel)
        require(len(path.read_bytes().replace(b"\r\n", b"\n")) == int(c[2]), "HASHES byte count mismatch: " + rel)
        require(rel not in by_path or by_path[rel] == digest, "conflicting duplicate HASHES row: " + rel)
        by_path[rel] = digest
        rows.append({"path": rel, "sha256_lf": digest})
    require(REQUIRED_HASHES <= by_path.keys(), "required HASHES rows missing")
    duplicates = Counter(r["path"] for r in rows)
    require(duplicates["eval/gold_fresh.csv"] == 2, "expected two block A HASHES rows")
    path = root / EVALUATION / "L_seal.json"
    require(sha(path) == seal_sha, "L_seal.json differs from approved seal")
    seal = jload(path)
    require(seal["fresh_episodes"] == list(FRESH_SPLIT.episodes), "block A episodes differ from seal")
    require(seal["block_b"]["episodes"] == list(FRESH_B_SPLIT.episodes), "block B episodes differ from seal")
    expected_files = {f"{EVALUATION}/{name}_L.json" for name in (
        "tool_v2_held_out", "tool_v2_fresh", "tool_v1_fresh", "baseline_fresh")}
    expected_b = {f"{EVALUATION}/{name}_fresh_b_L.json" for name in ("tool_v2", "tool_v1", "baseline")}
    require(set(seal["files"]) == expected_files and set(seal["block_b"]["files"]) == expected_b,
            "sealed file set differs")
    raw_inputs = {}
    for group in (seal["files"], seal["block_b"]["files"]):
        for rel, row in group.items():
            require(sha(root / rel) == row["sha256"], "sealed list mismatch: " + rel)
            raw_inputs[rel] = row["sha256"]
    for rel, row in seal["sealed_p08_held_out_lists"].items():
        require(sha(root / rel, lf=True) == row["sha256"], "sealed P08 list mismatch: " + rel)
        require(sha(root / rel) == row["sha256_raw_on_disk"], "P08 raw bytes changed: " + rel)
        raw_inputs[rel] = row["sha256_raw_on_disk"]
    for rel, digest in seal["inputs"].items():
        require(sha(root / rel) == digest, "sealed source mismatch: " + rel)
        raw_inputs[rel] = digest
    b = seal["block_b"]
    require(sha(root / b["selection"]["rule_file"]) == b["selection"]["rule_file_sha256"], "block B rule mismatch")
    require(sha(root / EVALUATION / "L_seal_before_block_b.json") == b["block_a_seal_sha256_before_block_b"],
            "previous seal copy mismatch")
    manifest = jload(root / V2 / "run_manifest.json")
    require(manifest["status"] == "complete" and all(v["status"] == "complete" for v in manifest["stages"].values()),
            "v2 run incomplete")
    require(manifest["overlay_sha256"] == by_path["config/v2.yaml"], "run overlay hash mismatch")
    require(sha(root / "outputs/eval/metrics.json") == p08_sha, "official P08 metrics changed")
    for rel in ("eval/HASHES.md", f"{EVALUATION}/L_seal.json", f"{V2}/run_manifest.json", "outputs/eval/metrics.json"):
        raw_inputs[rel] = sha(root / rel)
    return {"HASHES_rows": rows, "duplicate_rows": {p: n for p, n in duplicates.items() if n > 1},
            "seal_sha256": seal_sha, "raw_inputs": raw_inputs, "seal": seal}


def context(root):
    cfg = load_config(root / "config.yaml")  # config only; never loads secrets
    episodes, _ = parse_dir(cfg.data_dir)
    return build_index(episodes)


def read_gold(root, split, index, positive_count, negative_count):
    path = root / split.default_gold
    header, cells, file_warnings = G.read_sheet(path)
    speakers = {line.speaker for line in index.values() if line.speaker}
    report = G.check_sheet(header, cells, index, speakers, split=split)
    errors = Counter(e for row in report.rows for e in row.errors)
    require(report.ok, "gold validation errors: " + json.dumps({"file": report.file_errors, "rows": dict(errors)}))
    with path.open(encoding="utf-8-sig", newline="") as f:
        gold = S.gold_from_rows(csv.DictReader(f), index)
    require(sum(g.kind == "pos" for g in gold) == positive_count and sum(g.kind == "neg" for g in gold) == negative_count,
            "gold counts differ from approval")
    require(all(g.segments and all(s[0] in split.episodes for s in g.segments) for g in gold), "gold outside block")
    return gold, {"errors": 0, "rationale_name_hits": errors.get("NAME_IN_RATIONALE", 0),
                  "warnings": file_warnings + report.warnings}


def load_predictions(root, name, split, index, sealed_row):
    doc = jload(root / EVALUATION / f"{name}_L.json")
    require(doc["count"] == sealed_row["count"] == len(doc["promos"]), "L count differs from seal")
    require([r["rank"] for r in doc["promos"]] == list(range(1, doc["count"] + 1)), "L rank is not position")
    require(all(E.inside(r, split.episodes) for r in doc["promos"]), "L contains a promo outside block")
    preds = S.baseline_preds(doc["promos"]) if name.startswith("baseline") else S.tool_preds_from_L(doc, index)
    require(len({p.promo_id for p in preds}) == len(preds), "duplicate prediction IDs")
    if doc["K"] is not None:
        require(doc["K"] == 32 and split == HELD_OUT_SPLIT, "unexpected K in sealed list")
    return doc, preds


def evaluate(preds, gold, k):
    # Keep the frozen matching code. Add the omitted P@10 Wilson interval from its stored k/n.
    result = S.evaluate_list(preds, gold, k)
    for row in result["by_tau"].values():
        p = row["precision_at_10"]
        p.update(S.share(p["k"], p["n"]))
    return result


def paired(left, right):
    a, b = left["matched_vector"], right["matched_vector"]
    require(list(a) == list(b), "paired gold vectors differ")
    return {"n": len(a), "mcnemar": S.mcnemar_exact(list(a.values()), list(b.values())),
            "bootstrap": S.paired_bootstrap(list(a.values()), list(b.values()))}


def baseline_context(root, episodes):
    """Section 6 counts only; never return generated baseline text."""
    invented = drops = sensitivity_drops = 0
    reasons = Counter()
    sources = {}
    for ep in episodes:
        rel = f"{V1}/baseline/baseline_E{ep:02d}.json"
        path = root / rel
        sources[rel] = sha(path)
        doc = jload(path)
        timestamps = doc.get("invented_timestamps")
        invented += len(timestamps) if isinstance(timestamps, list) else int(timestamps or 0)
        drops += len(doc.get("drops") or [])
        sensitivity_drops += len(doc.get("sensitivity_drops") or [])
        for row in doc.get("drops") or []:
            if isinstance(row, dict):
                reasons.update(row.get("reasons", []))
    return {"invented_timestamps": invented, "dropped": drops, "drop_reasons": dict(reasons),
            "sensitivity_dropped": sensitivity_drops, "sources_sha256": sources}


def compute(root, block, verification, index):
    split, positive_count, negative_count, suffix = BLOCKS[block]
    gold, validation = read_gold(root, split, index, positive_count, negative_count)
    k = positive_count * 2
    rows = verification["seal"]["block_b"]["files"] if block == "b" else verification["seal"]["files"]
    systems, diagnostics = {}, {}
    ranked = {"v2": jload(root / V2 / "ranked/promos_dev.json")}
    if block != "held_out":
        ranked["v1"] = jload(root / V1 / "ranked/promos_dev.json")
    for version, doc in ranked.items():
        name = f"tool_{version}_{suffix}"
        ldoc, preds = load_predictions(root, name, split, index, rows[f"{EVALUATION}/{name}_L.json"])
        require(E.tool_list(doc, split.episodes) == ldoc["promos"], "tool L rebuild differs from sealed order")
        systems[version] = evaluate(preds, gold, k)
        diagnostics[version] = S.per_gold_detail(preds, gold, k)
    comparisons, base_context = {}, {}
    if block != "held_out":
        name = f"baseline_{suffix}"
        ldoc, preds = load_predictions(root, name, split, index, rows[f"{EVALUATION}/{name}_L.json"])
        order = jload(root / V1 / "baseline/baseline_order.json")
        require(E.baseline_list(order, split.episodes) == ldoc["promos"], "baseline L rebuild differs")
        sensitivity_rows = [r for r in order["sensitivity_promos"] if E.inside(r, split.episodes)]
        sensitivity = S.baseline_preds(sensitivity_rows)
        systems["baseline"] = evaluate(preds, gold, k)
        systems["baseline_sensitivity_no_20_60"] = evaluate(sensitivity, gold, k)
        diagnostics["baseline"] = S.per_gold_detail(preds, gold, k)
        comparisons = {"v2_vs_v1": paired(systems["v2"], systems["v1"]),
                       "v2_vs_baseline": paired(systems["v2"], systems["baseline"])}
        base_context = baseline_context(root, split.episodes)
    else:
        # Reuse the official P08 results. Never run the original scorer again.
        official = jload(root / "outputs/eval/metrics.json")
        require(official["scoring_runs"] == 1, "official P08 scoring count changed")
        systems["v1_official"] = official["tool"]
        systems["baseline_official"] = official["baseline"]
        comparisons = {"v2_vs_v1": paired(systems["v2"], official["tool"]),
                       "v2_vs_baseline": paired(systems["v2"], official["baseline"])}
    return {"block": block, "episodes": list(split.episodes), "K": k, "G": positive_count,
            "negatives": negative_count, "label": "post-hoc (after seeing v1 results)" if block == "held_out" else "result",
            "scoring_runs": 1, "definitions": DEFINITIONS, "validation": validation,
            "systems": systems, "paired": comparisons, "diagnostics": diagnostics, "baseline_context": base_context,
            "statement": "Separate block; never pooled. Small sample; descriptive only. Single labeller had read the show.",
            "block_b_disclosure": "Episodes 15-17 were pilot episodes: only counts and a few promo IDs seen, no spans or content. Selected for v1/v2 candidate differences; not random. G=4; one gold=25 percentage points." if block == "b" else None}


def write_new(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, indent=2) + "\n")


def paths(root, block):
    folder = root / "outputs/eval" / ("p08b_held_out_posthoc" if block == "held_out" else f"p08b_fresh_{block}")
    return folder / "metrics.json", folder / "scoring_ledger.json", root / "results" / f"p08b_{block}.json"


def score(root, block, seal_sha=SEAL_SHA, p08_sha=P08_SHA):
    metrics_path, ledger_path, result_path = paths(root, block)
    require(not any(p.exists() for p in (metrics_path, ledger_path, result_path)), "block already attempted or scored; refuses another run")
    verification = verify(root, seal_sha, p08_sha)
    index = context(root)
    provenance = {k: v for k, v in verification.items() if k != "seal"}
    provenance["code_sha256"] = {p.relative_to(root).as_posix(): sha(p) for p in sorted((root / "src/promo_finder").glob("*.py"))}
    scorer = root / "tools/score_p08b.py"
    if scorer.is_file():
        provenance["code_sha256"]["tools/score_p08b.py"] = sha(scorer)
    ledger = {"block": block, "scoring_runs": 1, "status": "started", "started_utc": datetime.now(timezone.utc).isoformat(),
              "provenance": provenance}
    # Reserve the block before reading gold as labels or performing any matching.
    write_new(ledger_path, ledger)
    try:
        result = compute(root, block, verification, index)
        # No input may change between the preflight and the write.
        require(verify(root, seal_sha, p08_sha)["raw_inputs"] == verification["raw_inputs"], "inputs changed during scoring")
        require(all(sha(root / rel) == digest for rel, digest in result["baseline_context"].get("sources_sha256", {}).items()),
                "baseline context inputs changed during scoring")
        result["provenance"] = provenance
        write_new(metrics_path, result)
        public = {key: value for key, value in result.items() if key != "diagnostics"}
        write_new(result_path, public)
        ledger.update(status="completed", finished_utc=datetime.now(timezone.utc).isoformat(), metrics_sha256=sha(metrics_path),
                      public_result_sha256=sha(result_path))
    except Exception as exc:
        ledger.update(status="aborted, no completed result", error_type=type(exc).__name__)
        raise
    finally:
        ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    sc = sub.add_parser("score")
    sc.add_argument("--block", choices=("a", "b"), required=True)
    sub.add_parser("held-out")
    args = ap.parse_args(argv)
    try:
        if args.command == "verify":
            v = verify()
            print(f"verified {len(v['HASHES_rows'])} HASHES rows; duplicate block A rows identical; all seals and inputs match")
        else:
            block = "held_out" if args.command == "held-out" else args.block
            result = score(ROOT, block)
            print(f"block {block}: {result['label']}; G={result['G']}, negatives={result['negatives']}, K={result['K']}; scoring_runs=1")
            for system, ev in result["systems"].items():
                r = ev["primary"]["recall_at_K"]
                print(f"  {system}: Recall@K {r['k']}/{r['n']}; L={ev['L_size']}, K_used={ev['K_used']}")
        return 0
    except (Stop, S.ScoringError, E.ListError, OSError, ValueError, KeyError) as exc:
        # Validation exceptions contain only codes/IDs. Avoid printing arbitrary data or OS paths.
        print(f"STOP: {exc}" if isinstance(exc, (Stop, S.ScoringError, E.ListError)) else f"STOP: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
