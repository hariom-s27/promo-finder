#!/usr/bin/env python
"""P08: score tool and baseline once against the sealed gold set (eval/match_rule.md v1).

    python tools/score_p08.py score          # THE scoring run; refuses if metrics.json exists
    python tools/score_p08.py score --dev    # counted re-run, written as metrics_dev_N.json ("dev")

No LLM or network calls. Never prints script text, rationale or names: console output is
counts, IDs and numbers. Inputs are hash-checked before anything is computed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from promo_finder import scoring as S  # noqa: E402
from promo_finder.checker import build_index  # noqa: E402
from promo_finder.config import load_config  # noqa: E402
from promo_finder.parser import parse_dir  # noqa: E402

RUN = "outputs/runs/full"
FILES = {
    "match_rule": ("eval/match_rule.md", "d30dd8cd644512474b7b70f113692615e3a2123d4c1b1cfe4f7b20c1b66ff1e2"),
    "gold": ("eval/gold.csv", "e1a2287d724e7a46d2606c79562b6414d3d0a55324a276e189c5c183ef5bbdd4"),
    "longlist": ("outputs/gold_sealed/gold_longlist_v1.csv", "df6d7be38839630dcbf61cd66eb97346658fb46a27c1db52249d65edf7c2d03e"),
    "claude_v1": ("outputs/ai_labels/claude_v1.csv", "fafdcc025d1154deed6571e5efa7d724d880933266d3eb4650f713942b7c7acb"),
    "gpt_v1": ("outputs/ai_labels/gpt_v1.csv", "9229fa4625a4740fdb313184110084dce9f89e8e8d83e0f5ff9f00feb3c08573"),
    # recorded at P08 Part A, before scoring
    "tool_L": (f"{RUN}/evaluation/tool_held_out_L.json", "0b97d2aacca7ea69283a9efec0f76ff175d4eea11582ef5bc33ad8337f47d424"),
    "baseline_L": (f"{RUN}/evaluation/baseline_held_out_L.json", "81d314bfa02df3f8d33da71766f4ee8113a43a1de982726049a1912062c24b1e"),
}
UNHASHED = {"ranked": f"{RUN}/ranked/promos_dev.json", "baseline_order": f"{RUN}/baseline/baseline_order.json"}

DEFINITIONS = {
    "tIoU": "sum_e |P_e ∩ G_e| / sum_e |P_e ∪ G_e|, exact ms, per episode (match rule §2)",
    "matching": "greedy by rank i=1..K; p_i takes unmatched gold with highest tIoU >= tau; ties lowest gold_id (§4)",
    "recall_at_K": "matched gold / |G| at tau; K = 2|G| = 32; Wilson 95% (z=1.959964) (§5)",
    "hook_hit": "gold matched at tau 0.5 AND matched prediction's FIRST segment in the same episode as gold's FIRST segment AND |delta start| <= 2000 ms; share of |G| (§5)",
    "hook_found": "greedy one-to-one by rank over top K on the hook test alone (any tIoU); each prediction takes the unmatched gold with smallest |delta start|, ties lowest gold_id; share of |G|; diagnostic (§5)",
    "precision_at_10": "tau-0.5 matches among positions 1-10 of L / min(10, |L|) (§5)",
    "recall_by_grade": "Recall@K at tau 0.5 split by gold grade 3/2/1; descriptive (§5)",
    "negative_hit_rate": "share of negatives with tIoU >= 0.5 against ANY top-K prediction, not one-to-one (§5)",
    "mcnemar": "exact two-sided binomial test on discordant pairs of a_i (tool matched gold i) vs b_i (baseline matched gold i), tau 0.5 (§5)",
    "bootstrap": "paired bootstrap of mean(a-b), B=10000, random.Random(12345).choices, percentile 95% (numpy linear) (§5)",
    "baseline_sensitivity": "baseline list with the 20-60 s check off (P07b sensitivity_promos, held-out only, stored order) (§6)",
    "s_no_funnel_row": "tool L in frozen sensitivity_order_S_no_funnel (held-out only, stored order), verified against re-implementation (D62)",
    "longlist_top10": "EXPLORATORY: of tool top 10, how many reach tIoU >= 0.5 with ANY long-list positive (D46)",
    "label_agreement": "positives only; global greedy by highest tIoU (ties lower A gold_id, lower B row), one-to-one; F1 = 2*matched/(|A|+|B|); among tau-0.5 pairs: hook within 2 s (same first-segment episode), Cohen kappa hook_type and cliff_type, linear weighted kappa on grade, raw agreement beside each (D43)",
}


def lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def jload(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def seg_ep(s) -> int:
    return int(s["episode"] if isinstance(s, dict) else s[0])


def summary_row(ev: dict) -> dict:
    p = ev["primary"]
    return {"L_size": ev["L_size"], "K_used": ev["K_used"], "G_size": ev["G_size"],
            "recall_at_K": p["recall_at_K"], "hook_hit": p["hook_hit"], "hook_found": p["hook_found"],
            "precision_at_10": p["precision_at_10"], "negative_hit_rate": p["negative_hit_rate"],
            "recall_by_grade": p["recall_by_grade"],
            "recall_at_K_by_tau": {t: v["recall_at_K"] for t, v in ev["by_tau"].items()},
            "precision_at_10_by_tau": {t: v["precision_at_10"] for t, v in ev["by_tau"].items()}}


def baseline_held_out_context(root: Path) -> dict:
    """Invented timestamps and drops for held-out episodes (counts only; from P07b files)."""
    inv = drops = sdrops = 0
    reasons: dict[str, int] = {}
    for ep in sorted(S.HELD_OUT):
        d = jload(root / f"{RUN}/baseline/baseline_E{ep:02d}.json")
        it = d.get("invented_timestamps")
        inv += len(it) if isinstance(it, list) else int(it or 0)
        drops += len(d.get("drops") or [])
        sdrops += len(d.get("sensitivity_drops") or [])
        for dr in d.get("drops") or []:
            for r in dr.get("reasons", []) if isinstance(dr, dict) else []:
                reasons[r] = reasons.get(r, 0) + 1
    return {"held_out_invented_timestamps": inv, "held_out_drops": drops, "held_out_drop_reasons": reasons,
            "held_out_sensitivity_drops": sdrops}


class Abort(Exception):
    def __init__(self, code: int, reason: str):
        super().__init__(reason)
        self.code, self.reason = code, reason


def score(args) -> int:
    """Run the scorer; any built-in check failure is logged as "aborted, no metrics"."""
    if (ROOT / "outputs/eval/metrics.json").exists() and not args.dev:
        print("refused: outputs/eval/metrics.json exists (score once, match rule §7); use --dev for a counted re-run")
        return 2
    try:
        return _score(args)
    except (Abort, S.ScoringError) as exc:
        code, reason = (exc.code, exc.reason) if isinstance(exc, Abort) else (6, str(exc))
        ledger_path = ROOT / "outputs/eval/scoring_ledger.json"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger = jload(ledger_path) if ledger_path.exists() else []
        ledger.append({"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "mode": "dev" if args.dev else "primary", "status": "aborted, no metrics", "reason": reason})
        ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"STOP: {reason} (logged as aborted, no metrics)")
        return code


def _score(args) -> int:
    root = ROOT
    out_dir = root / "outputs/eval"
    ledger_path = out_dir / "scoring_ledger.json"
    main_path = out_dir / "metrics.json"
    for key, (rel, want) in FILES.items():
        got = lf_sha256(root / rel)
        if got != want:
            raise Abort(3, f"hash mismatch for {key} ({rel})")
    print("hashes: 7/7 match")

    cfg = load_config()
    episodes, _ = parse_dir(cfg.data_dir)
    index = build_index(episodes)

    gold = S.gold_from_rows(read_csv(root / FILES["gold"][0]), index)
    G = [g for g in gold if g.kind == "pos"]
    K = 2 * len(G)
    for g in gold:
        if any(s[0] not in S.HELD_OUT for s in g.segments):
            raise S.ScoringError(f"gold {g.gold_id} outside held-out episodes")

    tool_doc = jload(root / FILES["tool_L"][0])
    base_doc = jload(root / FILES["baseline_L"][0])
    if tool_doc["K"] != K or base_doc["K"] != K:
        raise S.ScoringError("K in L files differs from 2|G|")
    tool = S.tool_preds_from_L(tool_doc, index)
    base = S.baseline_preds(base_doc["promos"])
    S.assert_held_out(tool, "tool L")
    S.assert_held_out(base, "baseline L")
    if len(tool) != tool_doc["count"] or len(base) != base_doc["count"]:
        raise S.ScoringError("L count field differs from promo count")

    # baseline rebuild check + sensitivity list (§6)
    order = jload(root / UNHASHED["baseline_order"])
    rebuilt = S.baseline_preds(S.held_out_only(order["promos"]))
    if [(p.promo_id, p.segments) for p in rebuilt] != [(p.promo_id, p.segments) for p in base]:
        raise Abort(4, "baseline rebuild from baseline_order.json differs from sealed baseline L")
    base_sens = S.baseline_preds(S.held_out_only(order["sensitivity_promos"]))
    S.assert_held_out(base_sens, "baseline sensitivity L")

    # S_no_funnel order (D62)
    ranked = jload(root / UNHASHED["ranked"])
    rows_ho = [r for r in ranked["promos"] if r["segments"] and all(seg_ep(s) in S.HELD_OUT for s in r["segments"])]
    ho_ids = {r["promo_id"] for r in rows_ho}
    stored = [pid for pid in ranked["sensitivity_order_S_no_funnel"] if pid in ho_ids]
    mine = S.frozen_eval_order(rows_ho, "S_no_funnel")
    if stored != mine:
        raise Abort(5, "stored S_no_funnel order differs from re-implementation")
    if set(stored) != {p.promo_id for p in tool}:
        raise Abort(5, "S_no_funnel held-out set differs from tool L")
    tool_nf = S.reorder(tool, stored)

    ev_tool = S.evaluate_list(tool, gold, K)
    ev_base = S.evaluate_list(base, gold, K)
    ev_base_sens = S.evaluate_list(base_sens, gold, K)
    ev_tool_nf = S.evaluate_list(tool_nf, gold, K)

    a = list(ev_tool["matched_vector"].values())
    b = list(ev_base["matched_vector"].values())
    if list(ev_tool["matched_vector"]) != list(ev_base["matched_vector"]):
        raise S.ScoringError("paired vectors not aligned")

    longlist = S.gold_from_rows(read_csv(root / FILES["longlist"][0]), index)
    ll_pos = [g for g in longlist if g.kind == "pos"]
    claude = S.gold_from_rows(read_csv(root / FILES["claude_v1"][0]), index)
    gpt = S.gold_from_rows(read_csv(root / FILES["gpt_v1"][0]), index)

    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = jload(ledger_path) if ledger_path.exists() else []
    ledger.append({"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": "dev" if args.dev else "primary",
                   "status": "completed"})
    runs = len(ledger)

    full = {
        "label": "dev" if args.dev else "result",
        "scoring_runs": runs,
        "match_rule": "eval/match_rule.md v1",
        "statement": "n = 16 positives; all results are descriptive (match rule §5, §8)",
        "definitions": DEFINITIONS,
        "sources": {k: {"path": v[0], "sha256": v[1]} for k, v in FILES.items()}
                   | {k: {"path": v, "sha256_lf": lf_sha256(root / v)} for k, v in UNHASHED.items()},
        "counts": {"G": len(G), "negatives": len(gold) - len(G), "K": K, "tool_L": len(tool), "baseline_L": len(base),
                   "baseline_sensitivity_L": len(base_sens), "longlist_positives": len(ll_pos)},
        "checks": {"hashes": "7/7", "tool_ms_equal_checker_ms": True, "all_L_held_out": True,
                   "baseline_rebuild_equals_sealed": True, "s_no_funnel_stored_equals_reimplementation": True},
        "tool": ev_tool, "baseline": ev_base, "baseline_sensitivity_no_20_60": ev_base_sens, "tool_s_no_funnel_order": ev_tool_nf,
        "paired_tool_vs_baseline": {"n": len(a), "mcnemar": S.mcnemar_exact(a, b), "bootstrap": S.paired_bootstrap(a, b)},
        "exploratory_longlist_top10": {"k": S.any_match_count(tool, ll_pos, 10), "n": min(10, len(tool)),
                                       "label": "EXPLORATORY (D46)"},
        "label_agreement": {"gold_vs_claude_v1": S.label_agreement(gold, claude),
                            "gold_vs_gpt_v1": S.label_agreement(gold, gpt),
                            "claude_v1_vs_gpt_v1": S.label_agreement(claude, gpt)},
        "baseline_context": baseline_held_out_context(root),
        "diagnostics": {"tool_per_gold": S.per_gold_detail(tool, gold, K), "baseline_per_gold": S.per_gold_detail(base, gold, K),
                        "tool_top10": S.top_n_detail(tool, gold, 10)},
    }
    results = {
        "label": full["label"], "scoring_runs": runs, "statement": full["statement"], "definitions": DEFINITIONS,
        "counts": full["counts"],
        "tool": summary_row(ev_tool), "baseline": summary_row(ev_base),
        "baseline_sensitivity_no_20_60": summary_row(ev_base_sens), "tool_s_no_funnel_order": summary_row(ev_tool_nf),
        "paired_tool_vs_baseline": full["paired_tool_vs_baseline"],
        "exploratory_longlist_top10": full["exploratory_longlist_top10"],
        "label_agreement": {k: {kk: vv for kk, vv in v.items()} for k, v in full["label_agreement"].items()},
        "matched_gold_ids_tau_0.5": {"tool": [g for g, x in ev_tool["matched_vector"].items() if x],
                                     "baseline": [g for g, x in ev_base["matched_vector"].items() if x]},
    }
    target = main_path if not args.dev else out_dir / f"metrics_dev_{runs}.json"
    target.write_text(json.dumps(full, indent=2) + "\n", encoding="utf-8", newline="\n")
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8", newline="\n")
    if not args.dev:
        (root / "results").mkdir(exist_ok=True)
        (root / "results/metrics.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {target.relative_to(root).as_posix()} (scoring_runs={runs}, label={full['label']})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="score_p08")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("score", help="the single P08 scoring run")
    sc.add_argument("--dev", action="store_true", help="counted re-run; output labelled dev")
    args = ap.parse_args(argv)
    return score(args)


if __name__ == "__main__":
    sys.exit(main())
