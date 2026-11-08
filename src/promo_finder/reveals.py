"""Per-episode reveal and resolution pointers, rechecked against parsed input."""

from __future__ import annotations

import copy
import json
from collections import Counter

from .config import Config
from .header import fields
from .llm import LLMClient
from .models import Episode
from .understanding_common import DATA_RULE, array, compact, enum, metadata, obj, trim, validate, words


def schema(episode: Episode) -> dict:
    return obj({"marks": array(obj({
        "line_id": enum([line.id for line in episode.lines]),
        "type": enum(["reveal", "resolution"]),
        "confidence": enum(["low", "medium", "high"]), "what": words(12),
    }))})


def messages(episode: Episode, header: dict, sheet: dict) -> list[dict]:
    context = {"show_header": fields(header),
               "character_roles": [{"speaker_label": char["speaker_label"], "role": char["role"]}
                                   for char in sheet["characters"]]}
    return [{"role": "system", "content": DATA_RULE + " Mark a reveal when a secret or hidden fact comes out, "
             "and a resolution when a conflict is settled. Return only real line IDs from this episode. "
             "Do not force marks when neither event occurs. Each what field: max 12 words."},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False) + "\n" + compact([episode])}]


def clean(data: dict, episode: Episode) -> tuple[list[dict], dict]:
    response_schema = schema(episode)
    order = {line.id: line.idx for line in episode.lines if line.ep == episode.ep}
    # Drop bad IDs even if a fake provider or stale cache bypasses wrapper validation.
    data = copy.deepcopy(data)
    dropped = 0
    if isinstance(data, dict) and isinstance(data.get("marks"), list):
        kept = []
        for mark in data["marks"]:
            if isinstance(mark, dict) and isinstance(mark.get("line_id"), str) and mark["line_id"] not in order:
                dropped += 1
            else:
                kept.append(mark)
        data["marks"] = kept
    validate(data, response_schema)
    trims = Counter({"what": 0})
    result = {}
    duplicates = 0
    confidence = {"low": 0, "medium": 1, "high": 2}
    for mark in data["marks"]:
        mark["what"] = trim(mark["what"], 12, "what", trims)
        key = mark["line_id"], mark["type"]
        previous = result.get(key)
        if previous is not None:
            duplicates += 1
        if previous is None or confidence[mark["confidence"]] > confidence[previous["confidence"]]:
            result[key] = mark
    marks = sorted(result.values(), key=lambda m: (order[m["line_id"]], m["type"]))
    return marks, {"dropped_invalid_ids": dropped, "duplicates_removed": duplicates, "trims_by_field": dict(trims)}


def build(episode: Episode, header: dict, sheet: dict, cfg: Config,
          client: LLMClient, no_cache: bool = False) -> dict:
    result = client.call(cfg.active.picker, messages(episode, header, sheet), schema(episode),
                         purpose=f"p02.reveals.E{episode.ep:02d}", no_cache=no_cache)
    marks, checks = clean(result.data, episode)
    trims = Counter(checks.pop("trims_by_field"))
    return {"episode": episode.ep, "marks": marks,
            "counts_by_type": {kind: sum(mark["type"] == kind for mark in marks) for kind in ("reveal", "resolution")},
            "metadata": metadata(result, trims, **checks)}
