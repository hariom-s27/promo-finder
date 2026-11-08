"""Code-only ranking with frozen component definitions and explicit review lanes."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys

import yaml

from .checker import build_index
from .finding import check_selection, read_json
from .judging import checked_item
from .labelling import parse_eps
from .understanding import load_requested
from .understanding_common import UnderstandingError, write_json

POLICY = {"self_harm": 1.0, "nonconsent_abuse": 1.0, "sexual": 0.7, "minors": 0.5,
          "violence": 0.3, "profanity": 0.3, "shock_fear": 0.2}


def clip(value):
    return max(0.0, min(1.0, value))


def load_formula(cfg):
    path = cfg.root / "config/score_formula.yaml"
    raw = path.read_bytes()
    formula = yaml.safe_load(raw)
    expected = {"H": .3, "C": .2, "A": .2, "F": .2, "policy_safety": .1}
    if formula["weights"] != expected or formula["equal_weights"] != dict.fromkeys(expected, .2):
        raise UnderstandingError("unexpected formula weights")
    if formula["fit"]["penalties"] != cfg.builder.penalties.model_dump():
        raise UnderstandingError("formula and builder penalties differ")
    return formula, hashlib.sha256(raw).hexdigest()


def components(promo, judged, formula):
    agg, fidelity = judged["aggregate"], judged["fidelity"]
    if (not agg["successful_runs"] or fidelity["status"] != "ok" or not judged.get("answer_key") or
            any(agg["answers"].get(q) is None for q in ("hook_now", "ends_unresolved", "standalone", "orphan_line", "spoils_ending"))):
        return None
    flags = promo["flags"]
    if set(promo["policy"]) - set(POLICY):
        raise UnderstandingError("unknown policy category")
    H = agg["hook_rating_mean"] / 4 * (0.5 if agg["answers"]["hook_now"] == "no" else 1)
    C = agg["cliff_rating_mean"] / 4 * agg["yes_shares"]["ends_unresolved"]
    fv = {"yes": 1, "partly": .5, "no": 0}
    fidelity_value = sum(fv[fidelity["matches"][key]] for key in ("who", "stakes", "next")) / 3
    A = clip(.5 * agg["yes_shares"]["standalone"] + .5 * fidelity_value -
             (.25 if agg["answers"]["orphan_line"] == "yes" else 0))
    risk = 1.0 if agg["answers"]["spoils_ending"] == "yes" or flags.get("contains_low_conf_resolution") else .5 if flags.get("contains_reveal") else 0.0
    penalty = clip(sum(value for key, value in formula["fit"]["penalties"].items()
                       if (promo["montage"] if key == "montage" else flags.get(key, False))) / formula["fit"]["penalty_scale"])
    N = formula["fit"]["episode_count"]
    F = clip(.5 * (1 - (promo["episode"] - 1) / (N - 1)) + .5 * (1 - risk) - penalty)
    F_no_funnel = clip(1 - risk - penalty)
    P = max((formula["policy_weights"][key] for key in promo["policy"]), default=0.0)
    values = {"H": H, "C": C, "A": A, "F": F, "P": P, "policy_safety": 1-P}
    S = sum(formula["weights"][key] * values[key] for key in formula["weights"])
    equal = sum(formula["equal_weights"][key] * values[key] for key in formula["equal_weights"])
    sensitivity = S + formula["weights"]["F"] * (F_no_funnel - F)
    return {"H": H, "C": C, "A": A, "F": F, "P": P, "R": risk, "B": penalty,
            "F_no_funnel": F_no_funnel, "S": S, "S_equal": equal, "S_no_funnel": sensitivity}


def kendall_tau_b(xs, ys):
    if len(xs) != len(ys):
        raise ValueError("ranking lengths differ")
    concordant = discordant = tie_x = tie_y = tied_both = 0
    for i in range(len(xs)):
        for j in range(i + 1, len(xs)):
            dx, dy = xs[i] - xs[j], ys[i] - ys[j]
            if dx == 0 and dy == 0:
                tied_both += 1
            elif dx == 0:
                tie_x += 1
            elif dy == 0:
                tie_y += 1
            elif dx * dy > 0:
                concordant += 1
            else:
                discordant += 1
    denominator = math.sqrt((concordant + discordant + tie_x) * (concordant + discordant + tie_y))
    return {"tau_b": (concordant-discordant)/denominator if denominator else None,
            "n": len(xs), "concordant": concordant, "discordant": discordant,
            "ties_x_only": tie_x, "ties_y_only": tie_y, "ties_both": tied_both, "denominator": denominator}


def review_reasons(promo, judged, values, formula):
    if values is None:
        return ["missing_evidence"]
    reasons = []
    if values["P"] >= formula["lanes"]["policy_threshold"]:
        reasons.append("policy")
    flip = judged["aggregate"]["flip_rate"]
    if flip is not None and flip >= formula["lanes"]["flip_threshold"]:
        reasons.append("flip_rate")
    if promo["flags"].get("contains_reveal") and judged["aggregate"]["answers"]["spoils_ending"] == "yes":
        reasons.append("reveal_and_ending")
    return reasons


def launch_batch(rows, size=5):
    eligible = sorted((p for p in rows if not p["needs_human_reasons"] and p["S"] is not None), key=lambda p: (-p["S"], p["promo_id"]))
    selected, families, ids, filled = [], set(), set(), []
    for relax in (False, True):
        for row in eligible:
            if len(selected) >= size:
                break
            if row["promo_id"] in selected or ids.intersection(row["line_ids"]):
                continue
            if not relax and row["hook_type"] in families:
                continue
            selected.append(row["promo_id"])
            ids.update(row["line_ids"])
            families.add(row["hook_type"])
            if relax:
                filled.append(row["promo_id"])
    return {"promo_ids": selected, "family_relaxed_fill": filled, "shortfall": max(0, size-len(selected))}


def markdown(rows, launch, episodes):
    index = build_index(episodes)
    by_id = {row["promo_id"]: row for row in rows}
    order = [by_id[key] for key in launch["promo_ids"]] + [r for r in rows if r["promo_id"] not in launch["promo_ids"]]
    lines = ["# DEV ranked promos", ""]
    for row in order:
        lines.extend([f"## {row['promo_id']} | {row['batch_role']} | {row['lane']}",
                      f"S={row['S']} | H={row['H']} C={row['C']} A={row['A']} F={row['F']} P={row['P']}", ""])
        for key in row["line_ids"]:
            line = index[key]
            lines.append(" | ".join((key, line.kind, line.speaker or "", line.emotion or "", " ".join(line.text.split()))))
        lines.append("")
    return "\n".join(lines)


def run(cfg, episodes):
    check_selection([e.ep for e in episodes])
    formula, sha = load_formula(cfg)
    rows = []
    for episode in episodes:
        current = read_json(cfg.root / f"outputs/promos/candidates_E{episode.ep:02d}.json")["candidates"]
        judged_data = read_json(cfg.root / f"outputs/judge/judge_E{episode.ep:02d}.json")
        if judged_data.get("episode") != episode.ep:
            raise UnderstandingError("judge episode mismatch")
        judged = {item["promo_id"]: item for item in judged_data["items"] if not item["reference"]}
        if set(judged) != {p["promo_id"] for p in current}:
            raise UnderstandingError("judge coverage mismatch")
        for item in current:
            promo = checked_item(item, episode, cfg)
            result = judged[promo["promo_id"]]
            if result["candidate"] != promo:
                raise UnderstandingError("stale judge candidate")
            values = components(promo, result, formula)
            reasons = review_reasons(promo, result, values, formula)
            row = {"promo_id": promo["promo_id"], **(values or dict.fromkeys(("H", "C", "A", "F", "P", "R", "B", "F_no_funnel", "S", "S_equal", "S_no_funnel"))),
                   "segments": promo["segments"], "line_ids": promo["line_ids"], "hook_type": promo["hook"]["type"],
                   "cliff_type": promo["cliff"]["type"], "flags": promo["flags"], "policy": promo["policy"],
                   "judge": result, "flip_rate": result["aggregate"]["flip_rate"],
                   "per_question_disagreement": result["aggregate"]["per_question_disagreement"],
                   "needs_human_reasons": reasons, "formula_sha256": sha,
                   "model_provenance": promo["provenance"]}
            rows.append(row)
    rows.sort(key=lambda r: (r["S"] is None, -(r["S"] or 0), r["promo_id"]))
    launch = launch_batch(rows, formula["launch"]["size"])
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        row["lane"] = "needs_human" if row["needs_human_reasons"] else "launch_batch" if row["promo_id"] in launch["promo_ids"] else "reserve"
        row["batch_role"] = "control" if launch["promo_ids"] and row["promo_id"] == launch["promo_ids"][0] else "challenger" if row["promo_id"] in launch["promo_ids"] else "reserve"
    scored = [row for row in rows if row["S"] is not None]
    scores = [r["S"] for r in scored]
    summary = {"items": len(rows), "scored": len(scored), "formula_sha256": sha, "launch_batch": launch,
               "lane_counts": {lane: sum(r["lane"] == lane for r in rows) for lane in ("needs_human", "launch_batch", "reserve")},
               "score_distribution": {"min": min(scores) if scores else None, "median": statistics.median(scores) if scores else None, "max": max(scores) if scores else None},
               "kendall_equal": kendall_tau_b(scores, [r["S_equal"] for r in scored]),
               "kendall_no_funnel": kendall_tau_b(scores, [r["S_no_funnel"] for r in scored])}
    write_json(cfg.root / "outputs/ranked/promos_dev.json", {"summary": summary, "promos": rows})
    destination = cfg.root / "outputs/ranked/promos_dev.md"
    temporary = destination.with_suffix(".md.tmp")
    temporary.write_text(markdown(rows, launch, episodes), encoding="utf-8")
    temporary.replace(destination)
    return summary


def cmd_rank(cfg, args):
    try:
        eps = parse_eps(args.eps)
        check_selection(eps, args.allow_held_out)
        episodes = load_requested(cfg, eps, args.allow_held_out)
        print(json.dumps(run(cfg, episodes), sort_keys=True))
        return 0
    except Exception as exc:
        print("rank: failed; error=" + getattr(exc, "code", type(exc).__name__), file=sys.stderr)
        return 1
