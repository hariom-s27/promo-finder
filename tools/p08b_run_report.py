#!/usr/bin/env python
"""P08b D1: counts-only report of the live v2 run next to v1 (never opens promo text, spans, line ids or scores).

    python tools/p08b_run_report.py

Reads run manifests, the call log (metadata only), build summaries and the ranked file of outputs/runs/full_v2
and outputs/runs/full, and aggregates by group: held-out (16 episodes), fresh (31-34) and other. Held-out and
fresh numbers are aggregates only. Writes outputs/runs/full_v2/p08b_live_results.json (git-ignored).
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from promo_finder.accounting import part_name, summarize  # noqa: E402
from promo_finder.config import load_config  # noqa: E402
from promo_finder.labelling import FRESH, FRESH_B, HELD_OUT  # noqa: E402

V1, V2 = "outputs/runs/full", "outputs/runs/full_v2"
PHYSICAL_CAP = 791
DRY_CEILING_USD = 6.80505724       # the dry plan's upper bound (D86a accepted USD 6.81)
V1_ACTUAL_USD = 0.90769904         # P07b actual, reported-usage list price
PROMO_EP = re.compile(r"^P05-E(\d{2})-")
GROUPS = ("held_out", "fresh", "fresh_b", "other")   # held-out, fresh and fresh_b: aggregates only


def group_of(ep: int) -> str:
    return "held_out" if ep in HELD_OUT else "fresh" if ep in FRESH else "fresh_b" if ep in FRESH_B else "other"


def jload(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def promo_group(row: dict) -> str:
    return group_of(int(PROMO_EP.match(row["promo_id"]).group(1)))


def ranked_counts(ranked: dict) -> dict:
    """Aggregate counts by group from a ranked file: no ids, spans or scores leave this function."""
    out = {g: {"kept": 0, "selected_for_judging": 0, "scored": 0, "failed_evidence": 0, "extended": 0,
               "blocking_resolution_flagged": 0, "montage": 0, "lanes": Counter(), "needs_human_reasons": Counter()}
           for g in GROUPS}
    for row in ranked["promos"]:
        g = out[promo_group(row)]
        g["kept"] += 1
        g["selected_for_judging"] += row["judge_status"] != "not_selected"
        g["scored"] += row["judge_status"] == "scored"
        g["failed_evidence"] += row["judge_status"] == "failed_evidence"
        g["extended"] += bool(row["flags"].get("extended"))
        g["blocking_resolution_flagged"] += bool(row["flags"].get("contains_blocking_resolution"))
        g["montage"] += bool(len(row["segments"]) == 2)
        g["lanes"][row["lane"]] += 1
        for reason in row["needs_human_reasons"]:
            g["needs_human_reasons"][reason] += 1
    for g in out.values():
        g["lanes"], g["needs_human_reasons"] = dict(g["lanes"]), dict(g["needs_human_reasons"])
    return out


def build_counts(build_summary: dict) -> dict:
    out = {g: {"episodes": 0, "generated": 0, "kept": 0, "empty_episodes": 0, "dropped": Counter(),
               "extended_generated": 0, "resolution_flagged_generated": 0} for g in GROUPS}
    for key, summary in build_summary["episodes"].items():
        g = out[group_of(int(key[1:]))]
        g["episodes"] += 1
        g["generated"] += summary["generated"]
        g["kept"] += summary["kept"]
        g["empty_episodes"] += summary["kept"] == 0
        g["dropped"].update(summary["dropped"])
        g["extended_generated"] += summary.get("extended_generated", 0)
        g["resolution_flagged_generated"] += summary.get("resolution_flagged_generated", 0)
    for g in out.values():
        g["dropped"] = dict(g["dropped"])
    return out


def other_per_episode(build_summary: dict) -> dict:
    """Per-episode kept counts for the episodes that are neither held-out nor fresh."""
    return {key: s["kept"] for key, s in build_summary["episodes"].items() if group_of(int(key[1:])) == "other"}


def llm_report(root: Path, cfg) -> dict:
    run = root / V2
    manifest = jload(run / "run_manifest.json")
    records = [json.loads(line) for line in (run / "logs/llm_calls.jsonl").read_bytes().splitlines() if line.strip()]
    llm = summarize(records, cfg)
    if manifest.get("llm") is not None and llm != manifest["llm"]:
        raise SystemExit("STOP: call-log accounting differs from the run manifest")
    failed = [r for r in records if r.get("event") == "http_attempt_failed"]
    filtered = [r for r in failed if r.get("error_code") == "CONTENT_FILTERED"]
    providers = llm["providers"]
    http = sum(row["http_requests"] for row in providers.values())
    parts = {}
    for label, row in llm["parts"].items():
        name = label.split(":")[0]
        agg = parts.setdefault(name, {"calls": 0, "http_requests": 0, "cache_hits": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0})
        for k in ("calls", "http_requests", "cache_hits", "input_tokens", "output_tokens"):
            agg[k] += row[k]
        agg["usd"] += row["usd"] or 0.0
    return {"status": manifest.get("status"), "wall_time_s": manifest.get("wall_time_s"),
            "stage_status": {k: v.get("status") for k, v in manifest.get("stages", {}).items()},
            "stage_wall_time_s": {k: v.get("wall_time_s") for k, v in manifest.get("stages", {}).items()},
            "logical_calls": sum(r["calls"] for r in providers.values()), "http_requests": http, "physical_cap": PHYSICAL_CAP,
            "cache_hits": sum(r["cache_hits"] for r in providers.values()),
            "usd_reported_usage": sum(r["usd"] or 0.0 for r in providers.values()),
            "dry_ceiling_usd": DRY_CEILING_USD, "v1_actual_usd": V1_ACTUAL_USD,
            "providers": {p: {k: r[k] for k in ("calls", "http_requests", "cache_hits", "input_tokens", "output_tokens", "usd", "http_429s")}
                          for p, r in providers.items()},
            "parts": parts, "http_errors": dict(Counter(r["error"] for r in failed)),
            "content_filtered_requests": len(filtered),
            "content_filtered_by_part": dict(Counter(part_name(r["purpose"]) for r in filtered)),
            "returned_model_strings": sorted({m for r in llm["parts"].values() for m in r["model_strings"]}),
            "stage_llm": {k: {"calls": sum(p["calls"] for p in v["llm"]["providers"].values()),
                              "cache_hits": sum(p["cache_hits"] for p in v["llm"]["providers"].values()),
                              "usd": sum(p["usd"] or 0.0 for p in v["llm"]["providers"].values())}
                          for k, v in manifest.get("stages", {}).items() if v.get("llm")}}


def report(root: Path = ROOT) -> dict:
    cfg = load_config()
    v1, v2 = root / V1, root / V2
    r1, r2 = jload(v1 / "ranked/promos_dev.json"), jload(v2 / "ranked/promos_dev.json")
    b1, b2 = jload(v1 / "promos/build_summary.json"), jload(v2 / "promos/build_summary.json")
    sel1, sel2 = r1["summary"], r2["summary"]
    result = {"label": "P08b D1 live v2 run; counts only (held-out and fresh are aggregates)",
              "run": llm_report(root, cfg),
              "builder": {"v1": build_counts(b1), "v2": build_counts(b2)},
              "ranked": {"v1": ranked_counts(r1), "v2": ranked_counts(r2)},
              "other_episodes_kept_per_episode": {"v1": other_per_episode(b1), "v2": other_per_episode(b2)},
              "totals": {"v1": {k: sel1[k] for k in ("items", "scored", "judge_selected")},
                         "v2": {k: sel2[k] for k in ("items", "scored", "judge_selected")}},
              "lanes": {"v1": sel1["lane_counts"], "v2": sel2["lane_counts"]},
              "launch_batch_size": {"v1": len(sel1["launch_batch"]["promo_ids"]), "v2": len(sel2["launch_batch"]["promo_ids"])},
              "blocking_resolution_rows": sel2.get("blocking_resolution_rows", 0)}
    for name, doc in (("v1", sel1), ("v2", sel2)):
        if doc["items"] != sum(g["kept"] for g in result["ranked"][name].values()):
            raise SystemExit(f"STOP: {name} ranked rows do not add up")
    return result


def main() -> int:
    result = report()
    out = ROOT / V2 / "p08b_live_results.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    r = result["run"]
    print(f"run status {r['status']}; stages {r['stage_status']}; wall {r['wall_time_s']:.0f} s")
    print(f"LLM: {r['logical_calls']} logical calls, {r['http_requests']}/{r['physical_cap']} HTTP requests, {r['cache_hits']} cache hits, "
          f"USD {r['usd_reported_usage']:.5f} (v1 actual {r['v1_actual_usd']}, dry ceiling {r['dry_ceiling_usd']}); "
          f"HTTP errors {r['http_errors']}; CONTENT_FILTERED {r['content_filtered_requests']} {r['content_filtered_by_part']}")
    for provider, row in r["providers"].items():
        print(f"  {provider}: {row}")
    print("  by part:", {k: {kk: (round(vv, 5) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in r["parts"].items()})
    print("  by stage (calls / cache hits / USD):", {k: (v["calls"], v["cache_hits"], round(v["usd"], 5)) for k, v in r["stage_llm"].items()})
    print("  models:", r["returned_model_strings"])
    for g in GROUPS:
        a, b = result["builder"]["v1"][g], result["builder"]["v2"][g]
        x, y = result["ranked"]["v1"][g], result["ranked"]["v2"][g]
        print(f"[{g}] episodes {b['episodes']}: generated {a['generated']} -> {b['generated']}; kept {a['kept']} -> {b['kept']}; "
              f"empty episodes {a['empty_episodes']} -> {b['empty_episodes']}")
        print(f"      v1 drops {a['dropped']}")
        print(f"      v2 drops {b['dropped']}; extended (generated) {b['extended_generated']}, resolution-flagged (generated) {b['resolution_flagged_generated']}")
        print(f"      judged selected {x['selected_for_judging']} -> {y['selected_for_judging']}; scored {x['scored']} -> {y['scored']}; failed evidence {x['failed_evidence']} -> {y['failed_evidence']}")
        print(f"      v2 kept: extended {y['extended']}, blocking_resolution flagged {y['blocking_resolution_flagged']}, montage {y['montage']}; "
              f"lanes v1 {x['lanes']} -> v2 {y['lanes']}")
        print(f"      needs_human reasons v1 {x['needs_human_reasons']} -> v2 {y['needs_human_reasons']}")
    print("totals:", result["totals"], "| lanes:", result["lanes"], "| launch batch size:", result["launch_batch_size"],
          "| rows with blocking_resolution:", result["blocking_resolution_rows"])
    print("wrote", (ROOT / V2 / "p08b_live_results.json").relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
