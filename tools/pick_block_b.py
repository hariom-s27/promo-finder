#!/usr/bin/env python
"""P08b fresh block B: pick the 4 episodes where v2 changes the kept candidates (builder output only, counts only).

    python tools/pick_block_b.py            # compute, save the full table, print only the 4 picks and their counts
    python tools/pick_block_b.py --verify   # recompute and check that labelling.FRESH_B equals the picks

Selection rule (also stated verbatim in eval/match_rule_fresh_b.md):
  Eligible episodes are all episodes except the held-out episodes (1-4, 11-14, 26-29, 42-45), the DEV episodes
  (5-8, 19-22), the block A episodes 31-34, and episodes 46 and above. For each eligible episode, count the
  candidates that exactly one of v1 (outputs/runs/full) and v2 (outputs/runs/full_v2) keeps, each candidate
  identified by its segments (episode, first line id, last line id): the size of the symmetric difference of the
  two kept-candidate sets. Block B is the 4 eligible episodes with the largest count; ties go to the lower
  episode number. No gold file or label is read.

The full per-episode table goes to outputs/eval/block_b_selection.json (git-ignored); the console shows only
the 4 episode numbers and their counts, never candidate content.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from promo_finder import evaluation_lists as E  # noqa: E402

V1, V2 = "outputs/runs/full", "outputs/runs/full_v2"
OUT = "outputs/eval/block_b_selection.json"


def load(root: Path, run: str, episodes) -> dict:
    return E.load_candidates(root, run, episodes)


def select(root: Path = ROOT) -> tuple[list[int], dict[int, int]]:
    eligible = E.block_b_eligible()
    counts = E.symmetric_difference_counts(load(root, V1, eligible), load(root, V2, eligible))
    return E.pick_block_b(counts), counts


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    picks, counts = select()
    if "--verify" in args:
        from promo_finder.labelling import FRESH_B
        ok = sorted(picks) == sorted(FRESH_B)
        print("block B selection reproduces labelling.FRESH_B:", ok)
        return 0 if ok else 1
    out = ROOT / OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rule": __doc__.split("Selection rule", 1)[1].split("The full per-episode")[0].strip(),
                               "eligible_episodes": sorted(counts), "symmetric_difference_by_episode": counts,
                               "block_b_ranked": picks}, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("block B episodes (ranked) and symmetric-difference counts: "
          + ", ".join(f"E{ep:02d}: {counts[ep]}" for ep in picks))
    print("block B episodes (ascending):", ",".join(str(ep) for ep in sorted(picks)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
