#!/usr/bin/env python
"""P08b B2: recall diagnostic on the ALREADY-OPENED held-out set (no fresh episode, no LLM, no network).

    python tools/p08b_diagnostic.py

Replays the builder from the saved P07b moments, attributes every drop to a rule, checks gold coverage at
each stage, and prototypes the F1/F2 fixes as what-ifs. The replay must reproduce the saved builder output
exactly or the tool stops. Writes outputs/eval/p08b_diagnostic.json (git-ignored); the console shows counts,
gold IDs and episode numbers only, never script text.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from promo_finder import builder as B  # noqa: E402
from promo_finder import diagnostic as D  # noqa: E402
from promo_finder import scoring as S  # noqa: E402
from promo_finder.checker import build_index  # noqa: E402
from promo_finder.config import load_config  # noqa: E402
from promo_finder.labelling import HELD_OUT  # noqa: E402
from promo_finder.understanding import load_requested  # noqa: E402

RUN = "outputs/runs/full"
GOLD = ("eval/gold.csv", "e1a2287d724e7a46d2606c79562b6414d3d0a55324a276e189c5c183ef5bbdd4")
TOOL_L = (f"{RUN}/evaluation/tool_held_out_L.json", "0b97d2aacca7ea69283a9efec0f76ff175d4eea11582ef5bc33ad8337f47d424")
OUT = "outputs/eval/p08b_diagnostic.json"
K = 32
# what-if prototypes, never the builder: F1 = J4 -> flag (+0.25 pre_score penalty), F2 = TOO_SHORT -> extend the
# end to 20 s, F5 = blocking resolution -> flag (+0.5 pre_score penalty); F5 is a proposal only, not an approved fix
VARIANTS = {"v1": {}, "F1_j4_flag": {"j4_mode": "flag"}, "F2_too_short_extend": {"too_short_mode": "extend"},
            "F5_resolution_flag": {"resolution_mode": "flag"},
            "F1+F2": {"j4_mode": "flag", "too_short_mode": "extend"},
            "F2+F5": {"too_short_mode": "extend", "resolution_mode": "flag"},
            "F1+F2+F5": {"j4_mode": "flag", "too_short_mode": "extend", "resolution_mode": "flag"},
            # F5b: drop only when a blocking resolution line is the final line or ends inside the last 3 s
            "F5b_flag_unless_end": {"resolution_mode": "flag_unless_end"},
            "F2+F5b": {"too_short_mode": "extend", "resolution_mode": "flag_unless_end"},
            # sensitivity to the wording: "inside the last 3 s" read as the line STARTING inside it
            "F5b[start-rule]": {"resolution_mode": "flag_unless_end", "resolution_window_rule": "start"},
            "F2+F5b[start-rule]": {"too_short_mode": "extend", "resolution_mode": "flag_unless_end",
                                   "resolution_window_rule": "start"}}


def lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def read_artifact(root: Path, ep: int, rel: str):
    """Every per-episode read goes through here so the sealed fresh episodes can never be opened."""
    D.refuse_fresh([ep])
    return json.loads((root / RUN / rel.format(ep=ep)).read_text(encoding="utf-8"))


def stop(message: str) -> int:
    print(f"STOP: {message}")
    return 1


def main() -> int:
    root = ROOT
    D.refuse_fresh(HELD_OUT)  # belt and braces: the fixed episode list can never contain a fresh episode
    for rel, want in (GOLD, TOOL_L):
        if lf_sha256(root / rel) != want:
            return stop(f"hash mismatch for {rel}")
    print("hashes: gold and tool L match the sealed values")

    cfg = load_config()
    episodes = load_requested(cfg, list(HELD_OUT), allow_held_out=True)
    selected = {e.ep: e for e in episodes}
    index = build_index(episodes)
    summary_all = json.loads((root / RUN / "promos/build_summary.json").read_text(encoding="utf-8"))["episodes"]

    traces: dict[str, dict[int, D.EpisodeTrace]] = {name: {} for name in VARIANTS}
    moments_by_ep: dict[int, dict] = {}
    confidence_by_ep: dict[int, dict] = {}
    problems = []
    for episode in episodes:
        ep = episode.ep
        moments = read_artifact(root, ep, "moments/moments_E{ep:02d}.json")
        reveals = read_artifact(root, ep, "understanding/reveals_E{ep:02d}.json")
        intensity = read_artifact(root, ep, "understanding/intensity_E{ep:02d}.json")
        policy = read_artifact(root, ep, "understanding/policy_E{ep:02d}.json")
        saved = read_artifact(root, ep, "promos/candidates_E{ep:02d}.json")["candidates"]
        moments_by_ep[ep] = moments
        confidence_by_ep[ep] = {m["line_id"]: m["confidence"] for m in reveals["marks"]
                                if m["type"] == "resolution" and m["confidence"] in cfg.spoiler.resolution_block_confidence}
        previous = B.previous_episode(cfg, episode, selected)
        for name, options in VARIANTS.items():
            traces[name][ep] = D.trace_episode(episode, moments, reveals, intensity, policy, cfg, previous, **options)
        problems += D.same_as_builder(traces["v1"][ep], saved, summary_all[f"E{ep:02d}"])
    if problems:
        for line in problems:
            print("MISMATCH " + line)
        return stop("replay differs from the saved builder output; nothing reported")
    v1 = traces["v1"]
    funnel = {rule: sum(t.dropped[rule] for t in v1.values()) for rule in D.RULES}
    generated = sum(t.generated for t in v1.values())
    kept_total = sum(len(t.candidates) for t in v1.values())
    print(f"replay == saved builder output in all {len(v1)} held-out episodes "
          f"(generated {generated}, kept {kept_total}, drops {funnel})")

    rows = list(csv.DictReader(open(root / GOLD[0], newline="", encoding="utf-8-sig")))
    gold = S.gold_from_rows(rows, index)
    G = [g for g in gold if g.kind == "pos"]
    L_doc = json.loads((root / TOOL_L[0]).read_text(encoding="utf-8"))
    L = S.tool_preds_from_L(L_doc, index)
    saved_ids = {(p["promo_id"], promo_segs) for t in v1.values() for p in t.candidates
                 for promo_segs in [D.promo_segs(p)]}
    if saved_ids != {(p.promo_id, p.segments) for p in L}:
        return stop("replayed candidates differ from the sealed tool L")
    metrics = json.loads((root / "outputs/eval/metrics.json").read_text(encoding="utf-8"))
    ev = S.evaluate_list(L, gold, K)
    if ev["primary"]["recall_at_K"]["k"] != metrics["tool"]["primary"]["recall_at_K"]["k"]:
        return stop("Recall@K differs from the P08 official tool result")
    print(f"P08 check: tool Recall@{K} = {ev['primary']['recall_at_K']['k']}/{len(G)} (official, reproduced)")

    judged = {pid for ep in HELD_OUT for pid in read_artifact(root, ep, "judge/judge_E{ep:02d}.json")["selected_promo_ids"]}
    cand_by_ep = {name: {ep: t.candidates for ep, t in tr.items()} for name, tr in traces.items()}

    pool = D.pool_matched(cand_by_ep["v1"], G)
    pool_ids = sorted(g for g, v in pool.items() if v)
    a = {"n_gold": len(G), "k": len(pool_ids), "matched": pool_ids,
         "unmatched": sorted(g.gold_id for g in G if not pool[g.gold_id]), "kept_candidates": kept_total,
         "top_K_recall_official": ev["primary"]["recall_at_K"]["k"]}
    b = D.prefilter_recall(v1, G)
    c = D.rule_table(v1, G, pool)
    c["pair_construction"] = D.pair_construction_counts(v1, G)
    d = D.best_kept_rank(L, G, judged, K)
    e10 = D.top_episode_concentration(L, 10)
    e32 = D.top_episode_concentration(L, K)
    N = [g for g in gold if g.kind == "neg"]
    f = {name: D.variant_coverage(cand_by_ep[name], G, negatives=N) for name in VARIANTS}
    base_hit = set(f["v1"]["pool_recall"]["matched"])
    for name in VARIANTS:
        f[name]["extended_kept"] = sum(t.extended_kept for t in traces[name].values())
        f[name]["j4_flagged_pairs"] = sum(t.j4_flagged_generated for t in traces[name].values())
        f[name]["resolution_flagged_kept"] = sum(bool(p["flags"].get("contains_blocking_resolution"))
                                                 for t in traces[name].values() for p in t.candidates)
        f[name]["episodes_with_candidates"] = sum(1 for t in traces[name].values() if t.candidates)
        f[name]["gained_vs_v1"] = {g: f[name]["per_gold"][g] for g in sorted(set(f[name]["pool_recall"]["matched"]) - base_hit)}
        f[name]["lost_vs_v1"] = sorted(base_hit - set(f[name]["pool_recall"]["matched"]))
    g_moments = D.moment_coverage(moments_by_ep, index, G)
    g_moments["max_pair_tiou"] = D.max_pair_tiou(v1, G)
    f3 = f3_whatif(L, gold, K)
    rescue = {name: D.rescue_detail(traces[name], G, f[name]["gained_vs_v1"]) for name in VARIANTS if f[name]["gained_vs_v1"]}
    res_end = D.resolution_end_summary(v1, G)
    res_gold = D.gold_resolution_positions(G, index, confidence_by_ep)

    report = {"label": "P08b B2 diagnostic; held-out episodes only; counts, gold IDs, line IDs and episode numbers",
              "inputs": {GOLD[0]: GOLD[1], TOOL_L[0]: TOOL_L[1]},
              "checks": {"replay_equals_saved_builder_output": True, "episodes": len(v1), "generated": generated,
                         "kept": kept_total, "first_drop_counts": funnel,
                         "replayed_candidates_equal_tool_L": True, "recall_at_K_equals_P08": True},
              "a_pool_recall": a, "b_prefilter_recall": b, "c_drop_rules": c, "d_best_kept_rank": d,
              "e_top10_concentration": e10, "e_top32_concentration": e32, "f_whatif_variants": f,
              "g_moment_coverage": g_moments, "h_f3_diversity_cap_on_v1_L": f3,
              "i_resolution_position": {"rescued_gold_detail": rescue, "v1_resolution_removed_pairs": res_end,
                                        "gold_promos_resolution_marks": res_gold}}
    out = root / OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print_counts(report)
    print(f"wrote {OUT}")
    return 0


def f3_whatif(L, gold, K, per_episode: int = 2, top: int = 10) -> dict:
    """F3 prototype on the sealed v1 list: at most `per_episode` promos per episode in the top `top`."""
    capped = D.diversity_cap(L, lambda p: p.segments[0][0], top, per_episode)
    new_L = S.reorder(L, [p.promo_id for p in capped])
    before, after = S.evaluate_list(L, gold, K)["primary"], S.evaluate_list(new_L, gold, K)["primary"]
    old_top, new_top = {p.promo_id for p in L[:top]}, {p.promo_id for p in new_L[:top]}
    pos_of = {p.promo_id: p.pos for p in L}
    return {"per_episode": per_episode, "top": top,
            "deferred_from_top": sorted(old_top - new_top), "promoted_into_top": sorted(new_top - old_top),
            "promoted_from_positions": sorted(pos_of[x] for x in new_top - old_top),
            "recall_at_K": {"before": before["recall_at_K"]["k"], "after": after["recall_at_K"]["k"]},
            "precision_at_10": {"before": before["precision_at_10"]["k"], "after": after["precision_at_10"]["k"],
                                "n": after["precision_at_10"]["n"]},
            "top_concentration_after": D.top_episode_concentration(new_L, top)}


def _ids(xs) -> str:
    return ",".join(xs) if xs else "-"


def print_counts(r: dict) -> None:
    a, b, c = r["a_pool_recall"], r["b_prefilter_recall"], r["c_drop_rules"]
    print(f"(a) pool recall: {a['k']}/{a['n_gold']} gold matched by any of {a['kept_candidates']} kept candidates "
          f"(official top-{K} recall {a['top_K_recall_official']}); unmatched: {_ids(a['unmatched'])}")
    for key, label in (("raw_pair", "raw hook-to-cliff pair"), ("constructed_pair", "constructed pair")):
        print(f"(b) pre-filter recall, {label}: {b[key]['k']}/{b['n_gold']}; unmatched: {_ids(b[key]['unmatched'])}")
    pc = c["pair_construction"]
    print(f"(b) pairs by raw length: {pc['pairs']}; gold-matching pairs: {pc['gold_matching_pairs']}")
    print(f"(c) gold-matching pairs before any rule: {c['gold_matching_pairs']} of {sum(pc['pairs'].values())} pairs; "
          f"kept pairs {c['kept_gold_matching_pairs']}/{c['kept_pairs']} match a gold")
    print("    rule | pairs removed (first drop) | of which gold-matching | gold | sole-blocker pairs | rescuable gold (no kept match yet)")
    for row, v in c["rules"].items():
        print(f"    {row} | {v['all_pairs_dropped']} | {v['first_drop_pairs']} | {_ids(v['first_drop_gold'])} | "
              f"{v['sole_blocker_pairs']} | {_ids(v['rescuable_gold'])}")
    print("    per gold: matching pairs / kept / first-drop by rule / sole blocker by rule")
    for gid, v in c["per_gold"].items():
        print(f"    {gid}: {v['matching_pairs']} / {v['kept_pairs']} / {v['first_drop']} / {v['sole_blocker']}")
    print("(d) best kept candidate per gold: gold | best tIoU | best pos in L | judged | first pos with tIoU>=0.5 | within K")
    for x in r["d_best_kept_rank"]:
        print(f"    {x['gold_id']} | {x['best_tiou']} | {x['best_pos']} | {x['best_judged']} | {x['first_match_pos']} | {x['matched_within_K']}")
    for key in ("e_top10_concentration", "e_top32_concentration"):
        e = r[key]
        print(f"(e) top-{e['top']} by episode: {e['per_episode']}; distinct {e['distinct_episodes']}, max in one {e['max_in_one_episode']}")
    for name, v in r["f_whatif_variants"].items():
        cand = v["candidates"]
        gained = {g: (x["best_episode_rank"], x["judged_top4"], x["judged_top6"]) for g, x in v["gained_vs_v1"].items()}
        print(f"(f) {name}: pool recall {v['pool_recall']['k']}/{v['n_gold']}; gained vs v1 (episode rank, judged@4, judged@6) {gained or '-'}; "
              f"lost vs v1 {_ids(v['lost_vs_v1'])}; candidates {cand['total']} (v1 55), empty episodes {_ids(map(str, cand['empty_episodes']))}; "
              f"negatives reached by any candidate {len(v['negative_pool_hits'])}/{v['n_negatives']} ({_ids(v['negative_pool_hits'])}), "
              f"by a judged-top4 candidate {len(v['negative_judged_top4_hits'])} ({_ids(v['negative_judged_top4_hits'])}); "
              f"matched&judged top4 {len(v['matched_and_judged_top4'])}, top6 {len(v['matched_and_judged_top6'])}; "
              f"flagged J4 pairs {v['j4_flagged_pairs']}, extended kept {v['extended_kept']}, resolution-flagged kept {v['resolution_flagged_kept']}")
    m = r["g_moment_coverage"]
    print(f"(g) moments name the gold boundaries (within {m['tolerance_ms']} ms): hook {len(m['hook_found'])}/16, cliff {len(m['cliff_found'])}/16, "
          f"both {len(m['both_found'])}/16 ({_ids(m['both_found'])})")
    print("    gold | hook | cliff | max raw-pair tIoU | max constructed-pair tIoU")
    for gid, x in m["per_gold"].items():
        t = m["max_pair_tiou"][gid]
        print(f"    {gid} | {x['hook_found']} | {x['cliff_found']} | {t['raw']} | {t['constructed']}")
    i = r["i_resolution_position"]
    t = i["v1_resolution_removed_pairs"]
    print(f"(i) pairs removed by the resolution rule in v1: {t['resolution_removed_pairs']}; nearest resolution line to the clip end: "
          f"{t['nearest_resolution_to_clip_end']}; gold-matching: {t['gold_matching']}")
    for name, rows in i["rescued_gold_detail"].items():
        for gid, cands in rows.items():
            for c in cands[:2]:
                lines = [(x["line_id"], x["confidence"], x["clip_seconds_after"], "END" if x["at_end"] else "earlier") for x in c["resolution_lines"]]
                print(f"    {name}: {gid} <- {c['promo_id']} (episode rank {c['episode_rank']}, flagged {c['resolution_flagged']}, "
                      f"extended {c['extended']}, montage {c['montage']}); resolution lines (id, conf, clip seconds after, position): {lines or '-'}")
    print("    gold promos holding blocking resolution marks (id: [line, conf, clip seconds after, at end]):")
    for gid, marks in i["gold_promos_resolution_marks"].items():
        if marks:
            print(f"    {gid}: {[(x['line_id'], x['confidence'], x['clip_seconds_after'], x['at_end']) for x in marks]}")
    h = r["h_f3_diversity_cap_on_v1_L"]
    print(f"(h) F3 cap {h['per_episode']}/episode in top {h['top']} on v1 L: deferred {_ids(h['deferred_from_top'])}; promoted from positions "
          f"{h['promoted_from_positions']}; Recall@{K} {h['recall_at_K']['before']}->{h['recall_at_K']['after']}; "
          f"P@10 {h['precision_at_10']['before']}->{h['precision_at_10']['after']} (n {h['precision_at_10']['n']}); "
          f"top-10 by episode after: {h['top_concentration_after']['per_episode']}")


if __name__ == "__main__":
    sys.exit(main())
