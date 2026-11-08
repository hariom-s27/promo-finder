"""Archive P03 and calculate builder ablations; prints counts only, no AI calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from promo_finder import builder
from promo_finder.config import load_config
from promo_finder.finding import check_selection, read_json
from promo_finder.labelling import parse_eps
from promo_finder.understanding import DEV_SPEC, load_requested
from promo_finder.understanding_common import UnderstandingError, write_json


def archive(root):
    source = root / "outputs/promos"
    destination = source / "archive_p03"
    files = sorted(p for p in source.iterdir() if p.is_file() and p.name != "p05_ablation.json")
    if destination.exists():
        manifest = read_json(destination / "manifest.json")
        for name, expected in manifest["sha256"].items():
            if hashlib.sha256((destination / name).read_bytes()).hexdigest() != expected:
                raise UnderstandingError("archive hash mismatch")
        return manifest
    for path in files:
        if path.name.startswith("candidates_") and any(not p["promo_id"].startswith("P03-") for p in read_json(path)["candidates"]):
            raise UnderstandingError("cannot archive a rebuilt candidate set as P03")
    destination.mkdir(parents=True)
    hashes = {}
    for path in files:
        shutil.copy2(path, destination / path.name)
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"sha256": hashes}
    write_json(destination / "manifest.json", manifest)
    return manifest


def variant(cfg, enabled):
    result = cfg.model_copy(deep=True)
    result.spoiler.reveal_mode = "flag" if "A1" in enabled else "block"
    result.spoiler.resolution_block_confidence = ["medium", "high"] if "A2" in enabled else ["low", "medium", "high"]
    result.builder.max_speakers = None
    result.builder.speakers_soft = 4
    result.builder.speakers_hard = 5 if "A3" in enabled else 4
    result.builder.j5_at_final_end = "A4" not in enabled
    return result


def ablations(cfg, episodes):
    all_rules = {"A1", "A2", "A3", "A4"}
    settings = {"P03": set(), **{f"only_{key}": {key} for key in sorted(all_rules)},
                "all": all_rules, **{f"without_{key}": all_rules - {key} for key in sorted(all_rules)}}
    prepared = []
    for episode in episodes:
        number = f"E{episode.ep:02d}"
        prepared.append((episode,
            read_json(cfg.root / f"outputs/moments/moments_{number}.json"),
            read_json(cfg.root / f"outputs/understanding/reveals_{number}.json"),
            read_json(cfg.root / f"outputs/understanding/intensity_{number}.json"),
            read_json(cfg.root / f"outputs/understanding/policy_{number}.json"),
            builder.previous_episode(cfg, episode, {e.ep: e for e in episodes})))
    results, candidates = {}, {}
    for name, enabled in settings.items():
        config = variant(cfg, enabled)
        rows, promos = {}, []
        for episode, moments, reveals, intensity, policy, previous in prepared:
            data, summary = builder.build_episode(episode, moments, reveals, intensity, policy, config, previous)
            rows[f"E{episode.ep:02d}"] = summary
            promos.extend(data["candidates"])
        candidates[name] = promos
        results[name] = {"enabled": sorted(enabled), "kept": len(promos), "episodes": rows,
                         "dropped": {rule: sum(row["dropped"][rule] for row in rows.values()) for rule in builder.RULES}}
    def identity(p):
        return (p["episode"], p["hook"]["line_id"], p["cliff"]["line_id"], p["montage"])
    def comparison(before, after):
        old, new = {identity(p): p for p in before}, {identity(p): p for p in after}
        common = old.keys() & new.keys()
        return {"matched_kept": len(common), "changed_final_end": sum(old[k]["segments"][-1]["last_line_id"] != new[k]["segments"][-1]["last_line_id"] for k in common),
                "newly_kept": len(new.keys()-old.keys()), "no_longer_kept": len(old.keys()-new.keys())}
    archived = read_json(cfg.root / "outputs/promos/archive_p03/build_summary.json")
    for ep, summary in results["P03"]["episodes"].items():
        old = archived["episodes"][ep]
        if any(summary[key] != old[key] for key in ("generated", "dropped", "kept")):
            raise UnderstandingError("P03 reproduction mismatch")
    return {"variants": results, "end_line_comparison": {"P03_vs_P05": comparison(candidates["P03"], candidates["all"]),
             "A4_on_off": comparison(candidates["without_A4"], candidates["all"])}, "archived_baseline": archived}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eps", default=DEV_SPEC)
    args = parser.parse_args()
    cfg = load_config()
    eps = parse_eps(args.eps)
    check_selection(eps)
    if not set(eps) <= set(parse_eps(DEV_SPEC)):
        raise UnderstandingError("offline evidence is DEV-only")
    archive(cfg.root)
    results = ablations(cfg, load_requested(cfg, eps))
    write_json(cfg.root / "outputs/promos/p05_ablation.json", results)
    print(json.dumps({"kept": {name: data["kept"] for name, data in results["variants"].items()},
                      "end_line_comparison": results["end_line_comparison"]}, sort_keys=True))


if __name__ == "__main__":
    main()
