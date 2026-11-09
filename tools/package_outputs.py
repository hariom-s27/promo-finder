"""Copy an allowlisted raw-output package and ZIP; console output is counts/size only."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import re
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "kuku_promo_finder_raw_outputs"
RUN_DIRS = ("understanding", "moments", "promos", "judge", "ranked", "baseline", "evaluation")
RUN_FILES = ("run_manifest.json", "dry_run.json", "p07b_live_results.json", "p08b_live_results.json", "code_fingerprint.json",
             "d102_execution_context.json", "d102_live_evidence.json", "d102_audit.json",
             "d104_execution_context.json", "d104_live_evidence.json", "d104_cache_copy.json")
EVAL_DIRS = ("", "p08b_fresh_a", "p08b_fresh_b", "p08b_held_out_posthoc")
GOLD_FILES = ("gold.csv", "gold_fresh.csv", "gold_fresh_b.csv")
AI_FILES = ("gpt_v1.csv", "claude_v1.csv")


def safe_file(root, path):
    """Resolve only regular workspace sources, with no linked ancestors."""
    root = root.resolve()
    path.absolute().relative_to(root)
    for node in (path, *path.parents):
        if node == root:
            break
        if node.is_symlink() or (hasattr(node, "is_junction") and node.is_junction()):
            raise ValueError("package refuses linked sources")
    path.resolve().relative_to(root)
    if not path.is_file():
        raise ValueError("required package source missing")
    return path


def sources(root, free_run="free_demo"):
    if not re.fullmatch(r"free_demo(?:_[A-Za-z0-9_-]+)?", free_run):
        raise ValueError("invalid free run selection")
    selected = []
    names = ["full", "full_v2", free_run]
    if free_run != "free_demo" and (root / "outputs/runs/free_demo/run_manifest.json").is_file():
        names.append("free_demo")  # Preserve the earlier partial attempt as separate evidence.
    for name in names:
        base = root / "outputs/runs" / name
        manifest = safe_file(root, base / "run_manifest.json")
        state = json.loads(manifest.read_text(encoding="utf-8"))
        historical_partial = name == "free_demo" and free_run != name
        if state.get("status") != "complete" and not historical_partial:
            raise ValueError("package requires all three completed runs")
        if name in {"full", "full_v2"} and state.get("episodes") != list(range(1, 51)):
            raise ValueError("full run does not cover fifty episodes")
        if name.startswith("free_demo") and state.get("episodes") != [23, 24]:
            raise ValueError("free demo episode selection differs")
        for stage in RUN_DIRS:
            folder = base / stage
            if not folder.exists():
                if name.startswith("free_demo") and (historical_partial or stage in {"baseline", "evaluation"}):
                    continue
                raise ValueError("required run stage missing")
            for path in sorted(folder.rglob("*")):
                if ".llm_cache" in path.relative_to(base).parts:
                    continue
                if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                    raise ValueError("package refuses linked sources")
                if path.is_file():
                    selected.append(safe_file(root, path))
        selected.extend(safe_file(root, base / f) for f in RUN_FILES if (base / f).is_file())
    for part in EVAL_DIRS:
        selected.extend(safe_file(root, root / "outputs/eval" / part / f)
                        for f in ("metrics.json", "scoring_ledger.json"))
    selected.extend(safe_file(root, root / "eval" / f) for f in GOLD_FILES)
    return sorted(set(selected))


def redacted_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or not any(f.strip().lower() == "rationale" for f in fields):
            raise ValueError("AI labels need one rationale column")
        keep = [f for f in fields if f.strip().lower() != "rationale"]
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=keep, lineterminator="\n")
        writer.writeheader()
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("malformed AI label row")
            writer.writerow({key: row[key] for key in keep})
    return output.getvalue().encode("utf-8")


def render_review(root, top_per_episode=3):
    """Private Drive review only: saved official ranking plus original saved parsed lines."""
    ranked = json.loads(safe_file(root, root / "outputs/runs/full/ranked/promos_dev.json").read_text(encoding="utf-8"))
    groups = {}
    for row in sorted(ranked["promos"], key=lambda row: row["rank"]):
        episode = row["segments"][0]["episode"]
        groups.setdefault(episode, [])
        if len(groups[episode]) < top_per_episode:
            groups[episode].append(row)
    lines = ["# Confidential: top promos by episode", "", "Drive-only review. Never commit this file or the package.",
             f"Up to {top_per_episode} promos per episode, in saved official rank order. No new judging or scoring.", ""]
    count = 0
    for episode, promos in sorted(groups.items()):
        source = safe_file(root, root / f"outputs/parsed/E{episode:02d}.json")
        parsed = json.loads(source.read_text(encoding="utf-8"))
        if parsed["ep"] != episode:
            raise ValueError("review parsed-episode mismatch")
        index = {line["id"]: line for line in parsed["lines"]}
        lines.extend([f"## Episode {episode}", ""])
        for promo in promos:
            selected = [index[key] for key in promo["line_ids"]]
            for segment in promo["segments"]:
                if (index[segment["first_line_id"]]["start_ms"] != segment["start_ms"] or
                        index[segment["last_line_id"]]["end_ms"] != segment["end_ms"]):
                    raise ValueError("review source timestamps differ from saved promo")
            spans = " + ".join(f"{s['start_ms']/1000:.3f}–{s['end_ms']/1000:.3f} s" for s in promo["segments"])
            lines.extend([f"### Rank {promo['rank']} | {promo['lane']} | S={promo['S']}",
                          f"Cuts: {spans} | hook {promo['hook_type']} | cliff {promo['cliff_type']}", "", "Judge answers:"])
            judge = promo.get("judge")
            answers = (judge or {}).get("aggregate", {}).get("answers", {})
            lines.extend([f"- {key}: {value}" for key, value in answers.items()] or ["- No saved aggregate answers (unselected or unavailable)."])
            lines.extend(["", "Transcript:", ""])
            for line in selected:
                if line["ep"] != episode:
                    raise ValueError("review line belongs to another episode")
                label = line.get("speaker") or line["kind"]
                lines.append(f"> [{line['start_ms']/1000:.3f}–{line['end_ms']/1000:.3f}] {label}: " + line["text"].replace("\n", " "))
            lines.append("")
            count += 1
    return "\n".join(lines) + "\n", count


def package(root=ROOT, free_run="free_demo"):
    root = root.resolve()
    destination = root / "outputs/package" / PACKAGE
    archive = destination.with_suffix(".zip")
    if destination.exists() or archive.exists():
        raise ValueError("package destination already exists; no overwrite or deletion")
    # Validate and redact everything before creating the destination.
    files = sources(root, free_run)
    ai = {Path("ai_labels_redacted") / f: redacted_csv(safe_file(root, root / "outputs/ai_labels" / f)) for f in AI_FILES}
    review, review_count = render_review(root)
    hashes = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    destination.mkdir(parents=True)
    for source in files:
        target = destination / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != hashes[source.relative_to(root).as_posix()]:
            raise ValueError("package copy hash mismatch")
    for relative, raw in ai.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (destination / "review").mkdir()
    (destination / "review/top_promos_by_episode.md").write_text(review, encoding="utf-8", newline="\n")
    (destination / "README.txt").write_text(
        "Local confidential raw outputs; do not commit this folder or ZIP.\n"
        "outputs/runs/full: official v1, all fifty episodes.\n"
        "outputs/runs/full_v2: optional v2, all fifty episodes.\n"
        f"outputs/runs/{free_run}: completed Groq demo, episodes 23-24; no comparison baseline or evaluation.\n"
        "Any separate free_demo folder preserves the earlier D102 partial attempt, not another completed run.\n"
        "Run folders contain understanding, moments, promos, judge, ranked, baseline/evaluation where applicable, and manifests.\n"
        "outputs/eval: existing P08 and separate P08b A/B/post-hoc metrics and scoring ledgers.\n"
        "eval: local gold labels. ai_labels_redacted: AI label exports with rationale removed.\n"
        "review/top_promos_by_episode.md: up to three saved top promos per episode, with judge answers and confidential transcripts; Drive-only, never commit.\n"
        "No .llm_cache, secrets, standalone source scripts, or sealed AI-label originals are included.\n"
        "These outputs may contain confidential generated text. Existing scoring was not rerun.\n", encoding="utf-8", newline="\n")
    counts = Counter()
    total = 0
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                relative = path.relative_to(destination)
                zipped.write(path, (Path(PACKAGE) / relative).as_posix())
                counts[relative.parts[0]] += 1
                total += path.stat().st_size
    return {"files": sum(counts.values()), "files_by_folder": dict(counts), "review_promos": review_count,
            "total_bytes": total, "zip_bytes": archive.stat().st_size}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--free-run", default="free_demo_d104")
    args = parser.parse_args(argv)
    try:
        result = package(free_run=args.free_run)
    except (OSError, ValueError, csv.Error, json.JSONDecodeError):
        print(json.dumps({"completed_packages": 0}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
