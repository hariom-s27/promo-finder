#!/usr/bin/env python
"""P08b C2: DEV check of v2 against v1 (offline: no LLM, no network, no gold, counts only).

    python tools/p08b_devcheck.py prepare     # copy saved moments/reveals/intensity/policy into scratch runs c2_v1, c2_v2
    # then build twice through the real CLI (the builder needs no credentials):
    #   python -m promo_finder build --eps <list> --run c2_v1 --allow-held-out
    #   python -m promo_finder build --eps <list> --run c2_v2 --allow-held-out --config-overlay config/v2.yaml
    python tools/p08b_devcheck.py compare     # byte identity of v1, DEV table, v2 counters, held-out fidelity

Sealed fresh episodes (31-34) are refused everywhere. Episode 35 is left out as well: its recap predecessor is
fresh episode 34 and the builder would have to read that script. Copies only; nothing is moved or deleted.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from promo_finder import builder as B  # noqa: E402
from promo_finder import diagnostic as D  # noqa: E402
from promo_finder.config import load_config  # noqa: E402
from promo_finder.labelling import HELD_OUT  # noqa: E402
from promo_finder.understanding import load_requested  # noqa: E402

FULL = "outputs/runs/full"
RUNS = ("c2_v1", "c2_v2")
DEV = (5, 6, 7, 8, 19, 20, 21, 22)
LEFT_OUT = {35}  # recap predecessor is a fresh episode
EPS = [e for e in range(1, 51) if e not in LEFT_OUT]
INPUTS = ("moments/moments_E{ep:02d}.json", "understanding/reveals_E{ep:02d}.json",
          "understanding/intensity_E{ep:02d}.json", "understanding/policy_E{ep:02d}.json")


def eps_list() -> list[int]:
    eps = [e for e in EPS if e not in D.SEALED]
    D.refuse_fresh(eps)
    return eps


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def prepare() -> int:
    eps = eps_list()
    for run in RUNS:
        for ep in eps:
            for pattern in INPUTS:
                rel = pattern.format(ep=ep)
                src, dst = ROOT / FULL / rel, ROOT / "outputs/runs" / run / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists() and dst.read_bytes() != src.read_bytes():
                    print(f"STOP: {dst.relative_to(ROOT).as_posix()} exists and differs")
                    return 1
                if not dst.exists():
                    shutil.copy2(src, dst)
    print(f"prepared {len(eps)} episodes x {len(INPUTS)} inputs in {', '.join(RUNS)} (copies); --eps {','.join(map(str, eps))}")
    return 0


def drops_total(summaries: dict, eps) -> dict:
    out: dict[str, int] = {}
    for ep in eps:
        for rule, n in summaries[f"E{ep:02d}"]["dropped"].items():
            out[rule] = out.get(rule, 0) + n
    return out


def compare() -> int:
    eps = eps_list()
    base = ROOT / "outputs/runs"
    saved_summary = read(ROOT / FULL / "promos/build_summary.json")["episodes"]
    v1_summary = read(base / "c2_v1/promos/build_summary.json")["episodes"]
    v2_summary = read(base / "c2_v2/promos/build_summary.json")["episodes"]
    for name, summ in (("c2_v1", v1_summary), ("c2_v2", v2_summary)):
        missing = [e for e in eps if f"E{e:02d}" not in summ]
        if missing or any(int(k[1:]) in D.SEALED for k in summ):
            print(f"STOP: {name} build summary does not cover exactly the requested non-fresh episodes")
            return 1

    # 1. v1 behaviour: candidates byte-identical to the saved P07b files, summaries equal
    same_bytes = sum((base / "c2_v1/promos" / f"candidates_E{e:02d}.json").read_bytes()
                     == (ROOT / FULL / "promos" / f"candidates_E{e:02d}.json").read_bytes() for e in eps)
    same_summary = sum(v1_summary[f"E{e:02d}"] == saved_summary[f"E{e:02d}"] for e in eps)
    print(f"v1 (switches off): candidates byte-identical to the saved P07b files in {same_bytes}/{len(eps)} episodes; "
          f"build summaries equal in {same_summary}/{len(eps)}")
    if same_bytes != len(eps) or same_summary != len(eps):
        print("STOP: v1 behaviour changed")
        return 1

    # 2. DEV table, counts only
    print("DEV episodes: kept v1 -> v2 (generated; extended / resolution-flagged generated in v2)")
    for e in DEV:
        a, b = v1_summary[f"E{e:02d}"], v2_summary[f"E{e:02d}"]
        print(f"  E{e:02d}: {a['kept']} -> {b['kept']} (generated {a['generated']} = {b['generated']}; "
              f"{b['extended_generated']} / {b['resolution_flagged_generated']})")
    dev1, dev2 = drops_total(v1_summary, DEV), drops_total(v2_summary, DEV)
    k1, k2 = sum(v1_summary[f"E{e:02d}"]["kept"] for e in DEV), sum(v2_summary[f"E{e:02d}"]["kept"] for e in DEV)
    print(f"DEV total kept {k1} -> {k2}; empty episodes v1 {[e for e in DEV if not v1_summary[f'E{e:02d}']['kept']]} "
          f"v2 {[e for e in DEV if not v2_summary[f'E{e:02d}']['kept']]}")
    print(f"DEV drops by rule v1: {dev1}")
    print(f"DEV drops by rule v2: {dev2}")
    cand2 = {e: read(base / "c2_v2/promos" / f"candidates_E{e:02d}.json")["candidates"] for e in DEV}
    ext = sum(bool(p["flags"].get("extended")) for c in cand2.values() for p in c)
    flg = sum(bool(p["flags"].get("contains_blocking_resolution")) for c in cand2.values() for p in c)
    print(f"DEV v2 kept candidates: {ext} extended, {flg} flagged contains_blocking_resolution, "
          f"{sum(p['montage'] for c in cand2.values() for p in c)} montage; "
          f"durations {min(p['duration_s'] for c in cand2.values() for p in c)}-{max(p['duration_s'] for c in cand2.values() for p in c)} s")

    # 3. invariants for every checked episode
    bad = [e for e in eps if v2_summary[f"E{e:02d}"]["generated"] != sum(v2_summary[f"E{e:02d}"]["dropped"].values()) + v2_summary[f"E{e:02d}"]["kept"]]
    same_generated = all(v1_summary[f"E{e:02d}"]["generated"] == v2_summary[f"E{e:02d}"]["generated"] for e in eps)
    print(f"accounting invariant holds in v2 for {len(eps) - len(bad)}/{len(eps)} episodes; generated pairs equal v1 in all: {same_generated}")
    if bad or not same_generated:
        print("STOP: accounting")
        return 1
    rest = [e for e in eps if e not in DEV and e not in HELD_OUT]
    allk1, allk2 = sum(v1_summary[f"E{e:02d}"]["kept"] for e in eps), sum(v2_summary[f"E{e:02d}"]["kept"] for e in eps)
    print(f"all {len(eps)} checked episodes (held-out {len(HELD_OUT)}, DEV {len(DEV)}, other {len(rest)}): kept v1 {allk1} -> v2 {allk2}")

    # 3b. what the judge stage has to do again: an estimate from the 45 checked episodes (fresh episodes excluded)
    top = 4  # config judge.full_run.top_per_episode
    unit = {"answer_key": 0.1558 / 41, "cold": 0.22426 / 214, "fidelity": 0.03079 / 132}  # P07b actual USD per call

    def judged_items(run: str, ep: int):
        cands = read(base / run / "promos" / f"candidates_E{ep:02d}.json")["candidates"]
        order = sorted(cands, key=lambda p: (-p["pre_score"], p["promo_id"]))[:top]
        return [(p["promo_id"], tuple((s["first_line_id"], s["last_line_id"]) for s in p["segments"])) for p in order]

    changed = new_items = fidelity = extra_repeat = items1 = items2 = 0
    for e in eps:
        a, b = judged_items("c2_v1", e), judged_items("c2_v2", e)
        items1 += len(a)
        items2 += len(b)
        if a != b:
            changed += 1
            fidelity += len(b)  # a new answer key means every item's fidelity request is new
        spans_before = {spans for _id, spans in a}
        fresh_items = [spans for _id, spans in b if spans not in spans_before]
        new_items += len(fresh_items)
        extra_repeat += 2 * bool(b and b[0][1] not in spans_before)  # the top item is judged three times
    cold = new_items + extra_repeat
    usd = changed * unit["answer_key"] + cold * unit["cold"] + fidelity * unit["fidelity"]
    print(f"judge stage vs v1 ({len(eps)} episodes): judged items {items1} -> {items2}; episodes whose judged selection changed {changed}; "
          f"new judged items {new_items}; estimated new calls: answer_key {changed}, cold {cold}, fidelity {fidelity}; "
          f"estimated extra USD {usd:.3f} (x{50 / len(eps):.2f} for all 50 episodes = {usd * 50 / len(eps):.3f}); "
          f"P07b unit prices, cache reuse assumed for unchanged requests")

    # 4. the implementation equals the held-out what-if reported at B3 (F2 + F5b)
    import p08b_diagnostic as T
    cfg = load_config()
    episodes = load_requested(cfg, list(HELD_OUT), allow_held_out=True)
    selected = {e.ep: e for e in episodes}
    problems = []
    for episode in episodes:
        a = lambda rel: T.read_artifact(ROOT, episode.ep, rel)  # noqa: E731
        trace = D.trace_episode(episode, a("moments/moments_E{ep:02d}.json"), a("understanding/reveals_E{ep:02d}.json"),
                                a("understanding/intensity_E{ep:02d}.json"), a("understanding/policy_E{ep:02d}.json"), cfg,
                                B.previous_episode(cfg, episode, selected),
                                too_short_mode="extend", resolution_mode="flag_unless_end")
        built = read(base / "c2_v2/promos" / f"candidates_E{episode.ep:02d}.json")["candidates"]
        problems += D.same_as_builder(trace, built, v2_summary[f"E{episode.ep:02d}"])
    held1 = sum(v1_summary[f"E{e:02d}"]["kept"] for e in HELD_OUT)
    held2 = sum(v2_summary[f"E{e:02d}"]["kept"] for e in HELD_OUT)
    print(f"held-out: v2 builder output equals the B3 what-if replay (F2+F5b) in {len(HELD_OUT) - len({p.split(':')[0] for p in problems})}"
          f"/{len(HELD_OUT)} episodes; kept {held1} -> {held2} candidates")
    if problems:
        print("STOP: v2 builder differs from the reported what-if")
        return 1
    return 0


def main(argv=None) -> int:
    cmd = (argv or sys.argv[1:] or [""])[0]
    if cmd == "prepare":
        return prepare()
    if cmd == "compare":
        return compare()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
