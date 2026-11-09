#!/usr/bin/env python
"""P08b D2: make the evaluation lists L and seal their hashes (no gold, no scoring, counts only on the console).

    python tools/make_L.py

Writes, once, under outputs/runs/full_v2/evaluation/ (never overwrites):
    tool_v2_held_out_L.json   v2 ranked output restricted to the held-out episodes
    tool_v2_fresh_L.json      v2 ranked output restricted to the fresh episodes 31-34
    tool_v1_fresh_L.json      v1 (P07b) ranked output restricted to 31-34
    baseline_fresh_L.json     frozen baseline order (P07b) restricted to 31-34
and L_seal.json with the sha256 of each of them, of the two sealed P08 held-out lists, and of the inputs. Hashes are LF-normalized (the P08 convention); new lists are LF-only anyway.
No label file is read: the lists are fixed before the fresh gold is sealed. K is null for the fresh lists
(K = 2 x |G| is set at scoring). The console shows counts only, never promo ids, spans, line ids or scores.

    python tools/make_L.py block-b

Fresh block B (episodes labelling.FRESH_B): writes tool_v2_fresh_b_L.json, tool_v1_fresh_b_L.json and
baseline_fresh_b_L.json once, keeps a copy of the previous seal (L_seal_before_block_b.json) and adds a
"block_b" section with their hashes to L_seal.json. It stops if the block A seal changed, if the selection no
longer reproduces FRESH_B, or if eval/gold_fresh_b.csv already exists (only its existence is tested).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from promo_finder import evaluation_lists as E  # noqa: E402
from promo_finder.labelling import FRESH, HELD_OUT  # noqa: E402

V1, V2 = "outputs/runs/full", "outputs/runs/full_v2"
HELD_OUT_K = 32  # the P08 value, fixed from the held-out gold before it was hashed
# the two sealed P08 held-out lists (recorded at P08 Part A, as LF-normalized sha256); part of the seal, not rewritten
SEALED_P08 = {
    f"{V1}/evaluation/tool_held_out_L.json": "0b97d2aacca7ea69283a9efec0f76ff175d4eea11582ef5bc33ad8337f47d424",
    f"{V1}/evaluation/baseline_held_out_L.json": "81d314bfa02df3f8d33da71766f4ee8113a43a1de982726049a1912062c24b1e",
}


class Stop(Exception):
    pass


def jload(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def hashes_md(root: Path) -> dict[str, str]:
    rows = {}
    for line in (root / "eval/HASHES.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 2 and len(cells[1]) == 64:
            rows[cells[0]] = cells[1]
    return rows


def preconditions(root: Path, sealed: dict[str, str], *, block_a_absent: bool = True) -> None:
    manifest = jload(root / V2 / "run_manifest.json")
    if manifest.get("status") != "complete" or any(s.get("status") != "complete" for s in manifest["stages"].values()):
        raise Stop("the v2 run is not complete")
    recorded = hashes_md(root)
    overlay = E.sha256_file(root / "config/v2.yaml")
    if recorded.get("config/v2.yaml") != overlay or manifest.get("overlay_sha256") != overlay:
        raise Stop("config/v2.yaml does not match HASHES.md or the run manifest")
    for rel, want in sealed.items():
        if E.lf_sha256_file(root / rel) != want:
            raise Stop(f"sealed P08 list changed: {Path(rel).name}")
    if block_a_absent and (root / V2 / "evaluation").exists() and any((root / V2 / "evaluation").glob("*_L.json")):
        raise Stop("lists already exist; they are written once")


def build(root: Path = ROOT, sealed: dict[str, str] | None = None, out=print) -> dict:
    sealed = SEALED_P08 if sealed is None else sealed
    preconditions(root, sealed)
    ranked_v1 = jload(root / V1 / "ranked/promos_dev.json")
    ranked_v2 = jload(root / V2 / "ranked/promos_dev.json")
    baseline = jload(root / V1 / "baseline/baseline_order.json")
    held, fresh = list(HELD_OUT), list(FRESH)
    plan = [
        ("tool_v2_held_out_L.json", E.tool_list(ranked_v2, held), "frozen config/eval_order.yaml (v2 run, lanes do not reorder)", HELD_OUT_K),
        ("tool_v2_fresh_L.json", E.tool_list(ranked_v2, fresh), "frozen config/eval_order.yaml (v2 run, lanes do not reorder)", None),
        ("tool_v1_fresh_L.json", E.tool_list(ranked_v1, fresh), "frozen config/eval_order.yaml (P07b run)", None),
        ("baseline_fresh_L.json", E.baseline_list(baseline, fresh), "frozen config/baseline.yaml round-robin (P07b run)", None),
    ]
    flagged = {r["promo_id"] for r in ranked_v2["promos"] if "blocking_resolution" in r.get("needs_human_reasons", [])}
    files = {}
    for name, rows, source, k in plan:
        path = root / V2 / "evaluation" / name
        sha = E.write_new(path, E.document(rows, source, k))
        covered = len({int(s["episode"]) for r in rows for s in r["segments"]}) if rows and "segments" in rows[0] else 0
        files[f"{V2}/evaluation/{name}"] = {"sha256": sha, "count": len(rows), "K": k, "episodes_with_promos": covered}
        extra = f", {sum(r['promo_id'] in flagged for r in rows)} flagged blocking_resolution" if name.startswith("tool_v2") else ""
        out(f"{name}: {len(rows)} promos in {covered} episodes{extra}; sha256 {sha}")
    existing = {rel: {"sha256": E.lf_sha256_file(root / rel), "sha256_raw_on_disk": E.sha256_file(root / rel),
                      "count": jload(root / rel)["count"]} for rel in sealed}
    for rel, row in existing.items():
        out(f"{Path(rel).name} (sealed at P08): {row['count']} promos; sha256 {row['sha256']}")
    seal = {"written_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "run": "full_v2",
            "label_files_read": 0, "fresh_episodes": fresh, "held_out_episodes": held,
            "note": "K is null for fresh lists: K = 2 x |G| is set at scoring. Lists are written once.",
            "files": files, "sealed_p08_held_out_lists": existing,
            "inputs": {f"{V1}/ranked/promos_dev.json": E.sha256_file(root / V1 / "ranked/promos_dev.json"),
                       f"{V2}/ranked/promos_dev.json": E.sha256_file(root / V2 / "ranked/promos_dev.json"),
                       f"{V1}/baseline/baseline_order.json": E.sha256_file(root / V1 / "baseline/baseline_order.json"),
                       "config/v2.yaml": E.sha256_file(root / "config/v2.yaml")}}
    seal_path = root / V2 / "evaluation/L_seal.json"
    seal_path.write_text(json.dumps(seal, indent=2) + "\n", encoding="utf-8", newline="\n")
    out(f"wrote L_seal.json; sha256 {E.sha256_file(seal_path)}")
    return seal


def build_block_b(root: Path = ROOT, sealed: dict[str, str] | None = None, out=print) -> dict:
    """Fresh block B: write the v1, v2 and baseline lists once and add their hashes to L_seal.json.

    Stops unless: the v2 run is complete; the block A seal is intact (its lists and inputs unchanged); the block B
    selection reproduces labelling.FRESH_B from builder output; and no block B gold file exists yet. The gold file
    is only tested for existence, never read."""
    from promo_finder.labelling import FRESH_B
    sealed = SEALED_P08 if sealed is None else sealed
    preconditions(root, sealed, block_a_absent=False)
    evaluation = root / V2 / "evaluation"
    seal_path = evaluation / "L_seal.json"
    if not seal_path.is_file():
        raise Stop("block A seal missing: run the block A lists first")
    seal = jload(seal_path)
    if "block_b" in seal or (evaluation / "L_seal_before_block_b.json").exists():
        raise Stop("block B is already sealed; it is written once")
    for rel, row in seal["files"].items():
        if E.lf_sha256_file(root / rel) != row["sha256"]:
            raise Stop(f"block A list changed since it was sealed: {Path(rel).name}")
    for rel, want in seal["inputs"].items():
        if E.sha256_file(root / rel) != want:
            raise Stop(f"input changed since the block A seal: {rel}")
    if (root / "eval/gold_fresh_b.csv").exists():
        raise Stop("block B gold already exists: the lists must be sealed before any gold")
    rule_file = root / "eval/match_rule_fresh_b.md"
    if not rule_file.is_file():
        raise Stop("eval/match_rule_fresh_b.md is missing")
    eligible = E.block_b_eligible()
    counts = E.symmetric_difference_counts(E.load_candidates(root, V1, eligible), E.load_candidates(root, V2, eligible))
    if sorted(E.pick_block_b(counts)) != sorted(FRESH_B):
        raise Stop("the selection rule no longer reproduces labelling.FRESH_B")
    ranked_v1, ranked_v2 = jload(root / V1 / "ranked/promos_dev.json"), jload(root / V2 / "ranked/promos_dev.json")
    baseline = jload(root / V1 / "baseline/baseline_order.json")
    block = list(FRESH_B)
    rows_v2, rows_v1 = E.tool_list(ranked_v2, block), E.tool_list(ranked_v1, block)
    plan = [("tool_v2_fresh_b_L.json", rows_v2, "frozen config/eval_order.yaml (v2 run, lanes do not reorder)"),
            ("tool_v1_fresh_b_L.json", rows_v1, "frozen config/eval_order.yaml (P07b run)"),
            ("baseline_fresh_b_L.json", E.baseline_list(baseline, block), "frozen config/baseline.yaml round-robin (P07b run)")]
    flagged = {r["promo_id"] for r in ranked_v2["promos"] if "blocking_resolution" in r.get("needs_human_reasons", [])}
    files = {}
    for name, rows, source in plan:
        sha = E.write_new(evaluation / name, E.document(rows, source, None))
        covered = len({int(s["episode"]) for r in rows for s in r["segments"]})
        files[f"{V2}/evaluation/{name}"] = {"sha256": sha, "count": len(rows), "K": None, "episodes_with_promos": covered}
        extra = f", {sum(r['promo_id'] in flagged for r in rows)} flagged blocking_resolution" if name.startswith("tool_v2") else ""
        out(f"{name}: {len(rows)} promos in {covered} episodes{extra}; sha256 {sha}")
    key = lambda p: tuple((s["episode"], s["start_ms"], s["end_ms"]) for s in p["segments"])  # noqa: E731
    k1, k2 = [key(p) for p in rows_v1], [key(p) for p in rows_v2]
    difference = {"v1_promos": len(k1), "v2_promos": len(k2), "same_time_spans_in_both": len(set(k1) & set(k2)),
                  "only_in_v1": len(set(k1) - set(k2)), "only_in_v2": len(set(k2) - set(k1)),
                  "positions_with_same_span": sum(a == b for a, b in zip(k1, k2)),
                  "first_differing_position": next((i + 1 for i, (a, b) in enumerate(zip(k1, k2)) if a != b), None)}
    out(f"v1 vs v2 block B lists: {difference}")
    previous = evaluation / "L_seal_before_block_b.json"
    previous.write_bytes(seal_path.read_bytes())            # a copy of the block A seal exactly as it was
    previous_sha = E.sha256_file(previous)
    seal["block_b"] = {
        "written_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "episodes": block,
        "selection": {"tool": "tools/pick_block_b.py", "rule_file": "eval/match_rule_fresh_b.md",
                      "rule_file_sha256": E.sha256_file(rule_file), "reproduced_from_builder_output": True,
                      "gold_file_exists": False, "label_files_read": 0},
        "note": "K is null: K = 2 x |G| is set at scoring. Written once, before any block B gold exists.",
        "files": files, "v1_vs_v2_difference": difference, "block_a_seal_sha256_before_block_b": previous_sha}
    seal_path.write_text(json.dumps(seal, indent=2) + "\n", encoding="utf-8", newline="\n")
    out(f"L_seal.json updated with block B; previous seal copy sha256 {previous_sha}; new L_seal.json sha256 {E.sha256_file(seal_path)}")
    return seal


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        build_block_b() if args == ["block-b"] else build()
    except (Stop, E.ListError) as exc:
        print(f"STOP: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
