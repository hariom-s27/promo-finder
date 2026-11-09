"""Evaluation lists L (match rules v1 §3 and fresh §3): the ranked output restricted to an episode set.

Pure functions; the tool in tools/make_L.py does the file I/O. A list keeps promos whose segments ALL lie in
the episode set, in the system's frozen order. Making a list never reads a label file: the lists must be fixed
before any gold is sealed, so they cannot depend on it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from . import ranking
from .labelling import FRESH, HELD_OUT, parse_eps
from .understanding import DEV_SPEC

LATE_SERIES_START = 46
BLOCK_B_SIZE = 4


class ListError(ValueError):
    """A precondition for a faithful list does not hold; nothing is written."""


# ── fresh block B: episodes where v2 changes the candidates ─────────────
# Selection rule (stated verbatim in eval/match_rule_fresh_b.md). Builder output only; no label is read.


def block_b_eligible(episodes: Iterable[int] = range(1, 51)) -> list[int]:
    """Every episode except the held-out set, the DEV episodes, the fresh block A (31-34) and episodes 46+."""
    dev = set(parse_eps(DEV_SPEC))
    return [e for e in episodes if e not in HELD_OUT and e not in dev and e not in FRESH and e < LATE_SERIES_START]


def span_set(candidates: Iterable[Mapping]) -> frozenset:
    """A kept-candidate set, each candidate identified by its segments: (episode, first line id, last line id)."""
    return frozenset(tuple((int(s["episode"]), s["first_line_id"], s["last_line_id"]) for s in c["segments"])
                     for c in candidates)


def load_candidates(root: Path, run: str, episodes: Iterable[int]) -> dict[int, list]:
    """The kept candidates of each episode in a run folder (builder output; the caller passes only unsealed episodes)."""
    return {ep: json.loads((root / run / f"promos/candidates_E{ep:02d}.json").read_text(encoding="utf-8"))["candidates"]
            for ep in episodes}


def symmetric_difference_counts(v1: Mapping[int, Sequence], v2: Mapping[int, Sequence]) -> dict[int, int]:
    """Per episode: how many candidates are kept by exactly one of v1 and v2."""
    if set(v1) != set(v2):
        raise ListError("v1 and v2 cover different episodes")
    return {ep: len(span_set(v1[ep]) ^ span_set(v2[ep])) for ep in sorted(v1)}


def pick_block_b(counts: Mapping[int, int], size: int = BLOCK_B_SIZE) -> list[int]:
    """The `size` episodes with the largest count; ties go to the lower episode number. Ranked order."""
    if len(counts) < size:
        raise ListError("fewer eligible episodes than the block size")
    return [ep for ep, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:size]]


def inside(row: Mapping, episodes: Iterable[int]) -> bool:
    eps = set(episodes)
    segments = row.get("segments") or []
    return bool(segments) and all(int(s["episode"]) in eps for s in segments)


def check_frozen_order(ranked_doc: Mapping) -> None:
    """The stored order must be the frozen evaluation order (S descending, then pre_score for unscored promos,
    promo id ascending), independent of lanes (D66)."""
    rows = ranked_doc["promos"]
    stored = [r["promo_id"] for r in rows]
    if stored != list(ranked_doc["evaluation_order"]):
        raise ListError("rows are not in the stored evaluation order")
    if [r["promo_id"] for r in ranking.evaluation_order(rows)] != stored:
        raise ListError("stored order differs from the frozen ordering rule")
    if len(set(stored)) != len(stored):
        raise ListError("duplicate promo ids")


def tool_list(ranked_doc: Mapping, episodes: Sequence[int]) -> list[dict]:
    """Tool L: rank = position in L (match rule: "rank i" means position in L), ids and segments only."""
    check_frozen_order(ranked_doc)
    kept = [r for r in ranked_doc["promos"] if inside(r, episodes)]
    return [{"rank": n, "promo_id": r["promo_id"], "segments": r["segments"]} for n, r in enumerate(kept, 1)]


def baseline_list(order_doc: Mapping, episodes: Sequence[int]) -> list[dict]:
    """Baseline L: its frozen round-robin output order, restricted to the episode set."""
    kept = [r for r in order_doc["promos"] if inside(r, episodes)]
    return [{"rank": n, "episode": r["episode"], "within_episode_rank": r["within_episode_rank"],
             "spans": r["spans"], "segments": r["segments"]} for n, r in enumerate(kept, 1)]


def document(rows: list[dict], order_source: str, k: int | None) -> dict:
    """K is None for the fresh set: K = 2 x |G| is fixed at scoring, when the gold is sealed."""
    return {"K": k, "count": len(rows), "order_source": order_source, "promos": rows}


def render(doc: Mapping) -> str:
    return json.dumps(doc, indent=2) + "\n"


def write_new(path: Path, doc: Mapping) -> str:
    """Write once (never overwrite); return the sha256 of the exact bytes."""
    if path.exists():
        raise ListError(f"refused: {path.name} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = render(doc).encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lf_sha256_file(path: Path) -> str:
    """sha256 of the bytes with CRLF turned into LF: how P08 recorded the held-out list hashes (the files were
    written on Windows). New lists are written with LF only, so for them both hashes are equal."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
