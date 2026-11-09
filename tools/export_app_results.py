"""Export only typed, text-free promo metadata and saved Azure usage for the app."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path("app/assets/full_results.json")
SOURCES = ("outputs/runs/full/ranked/promos_dev.json", "outputs/runs/full/run_manifest.json",
           "outputs/runs/full_v2/run_manifest.json")
STAGES = ("understand", "find", "build", "judge", "rank", "baseline", "snap/check")
LANES = {"launch_batch", "reserve", "needs_human"}
PROMO_FIELDS = {"episode", "start", "end", "duration", "hook_type", "cliff_type", "S", "lane", "rank"}


def number(value, *, integer=False):
    if type(value) not in ((int,) if integer else (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid numeric export field")
    return value


def timestamp(ms):
    tenths = (number(ms, integer=True) + 50) // 100
    minutes, rest = divmod(tenths, 600)
    seconds, tenth = divmod(rest, 10)
    return f"{minutes:02d}:{seconds:02d}.{tenth}"


def promo_row(promo):
    segments = promo["segments"]
    if not isinstance(segments, list) or not segments:
        raise ValueError("promo segments missing")
    episode = number(segments[0]["episode"], integer=True)
    if episode < 1 or any(segment["episode"] != episode for segment in segments):
        raise ValueError("invalid promo episode")
    duration = 0
    for segment in segments:
        start, end = (number(segment[key], integer=True) for key in ("start_ms", "end_ms"))
        if end <= start:
            raise ValueError("invalid segment order")
        duration += end - start
    hook, cliff, lane = promo["hook_type"], promo["cliff_type"], promo["lane"]
    if hook not in {f"H{i}" for i in range(1, 10)} or cliff not in {f"C{i}" for i in range(1, 10)} or lane not in LANES:
        raise ValueError("unrecognised type or lane code")
    score = promo["S"]
    if score is not None and (type(score) not in (int, float) or not math.isfinite(score)):
        raise ValueError("invalid score")
    rank = number(promo["rank"], integer=True)
    if rank < 1:
        raise ValueError("invalid rank")
    return {"episode": episode, "start": " + ".join(timestamp(s["start_ms"]) for s in segments),
            "end": " + ".join(timestamp(s["end_ms"]) for s in segments), "duration": ((duration + 50) // 100) / 10,
            "hook_type": hook, "cliff_type": cliff, "S": score, "lane": lane, "rank": rank}


def usage(providers):
    if set(providers) - {"azure", "azure_foundry"}:
        raise ValueError("full-result usage must be Azure only")
    totals = {key: sum(number(row[key], integer=True) for row in providers.values())
              for key in ("calls", "http_requests", "input_tokens", "output_tokens")}
    totals["tokens"] = totals["input_tokens"] + totals["output_tokens"]
    totals["usd"] = round(sum(number(row["usd"]) for row in providers.values()), 8)
    return totals


def build_export(root=ROOT):
    raw = {relative: (root / relative).read_bytes() for relative in SOURCES}
    ranked, full, v2 = (json.loads(raw[relative]) for relative in SOURCES)
    for manifest in (full, v2):
        if manifest["status"] != "complete" or manifest["episodes"] != list(range(1, 51)):
            raise ValueError("export requires completed fifty-episode runs")
    promos = sorted((promo_row(row) for row in ranked["promos"]), key=lambda row: row["rank"])
    if [row["rank"] for row in promos] != list(range(1, len(promos) + 1)):
        raise ValueError("promo ranks must be unique and contiguous")
    stages = []
    for name in STAGES:
        stage = full["stages"][name]
        if stage["status"] != "complete":
            raise ValueError("export requires completed stages")
        stages.append({"stage": name, **usage(stage["llm"]["providers"]),
                       "wall_time_s": number(stage["wall_time_s"])})
    totals = {**usage(full["llm"]["providers"]), "wall_time_s": number(full["wall_time_s"])}
    for key in ("calls", "http_requests", "input_tokens", "output_tokens"):
        if sum(stage[key] for stage in stages) != totals[key]:
            raise ValueError("stage and run usage counts disagree")
    if abs(sum(stage["usd"] for stage in stages) - totals["usd"]) > 1e-7:
        raise ValueError("stage and run costs disagree")
    launch = [row for row in promos if row["lane"] == "launch_batch"]
    if len(launch) > 5:
        raise ValueError("saved launch batch exceeds five")
    scale = {"shows_per_month": 150, "per_show_usd": totals["usd"], "per_show_minutes": totals["wall_time_s"] / 60,
             "monthly_usd": round(totals["usd"] * 150, 8), "monthly_minutes": totals["wall_time_s"] / 60 * 150,
             "monthly_serial_hours": totals["wall_time_s"] / 3600 * 150}
    return {"schema_version": 1, "promos": promos, "launch_batch": launch, "cost_at_scale": scale,
            "azure_stages": stages, "azure_totals": totals,
            "v2_cost_usd": usage(v2["llm"]["providers"])["usd"],
            "source_sha256": {relative: hashlib.sha256(value).hexdigest() for relative, value in raw.items()}}


def main():
    export = build_export()
    target = ROOT / TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(export, ensure_ascii=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"promos": len(export["promos"]), "stages": len(export["azure_stages"]), "bytes": target.stat().st_size}))


if __name__ == "__main__":
    main()
