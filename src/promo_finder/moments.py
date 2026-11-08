"""AI line-ID pointers only; code validates, trims and adds the episode end."""

from __future__ import annotations

import copy
import json
from collections import Counter

from .characters import roles
from .config import Config
from .header import fields
from .llm import LLMClient
from .models import Episode
from .understanding_common import DATA_RULE, array, compact, enum, metadata, obj, trim, validate, words

HOOK_TYPES = {
    "H1": "hit/pushed/grabbed", "H2": "humiliated in front of others",
    "H3": "shocking line", "H4": "hidden identity/power revealed",
    "H5": "danger right now", "H6": "rich-vs-poor contrast of one person",
    "H7": "angry accusing question", "H8": "shocked face before we see why",
    "H9": "forbidden romance",
}
CLIFF_TYPES = {
    "C1": "big question unanswered", "C2": "danger in motion",
    "C3": "fact revealed, meaning not shown", "C4": "reveal cut off",
    "C5": "choice not made", "C6": "someone walks in at the worst moment",
    "C7": "underdog strikes back, bully not fallen", "C8": "frozen shocked face",
    "C9": '"I love you"/"I know what you did", no reply',
}

SYSTEM = DATA_RULE + """

You are an editor finding possible starts and ends for a promo. A promo is 20–60 seconds and is posted to pull strangers in.

A hook start is the first line of a promo. Something is already happening in its first 3 seconds: a hit or grab, a humiliation, a shocking line, a hidden identity or power revealed, danger right now, a rich/poor contrast, an angry accusing question, a shocked face before we see why, or forbidden romance. It is never scenery, a door, walking, a greeting, or a line that answers an earlier question.

A cliffhanger end is the last line of a promo. It stops one line before the answer, apology, rescue, hug, resolution or scene change, so the viewer must want to know what happens next. If a resolution mark exists, a good end is usually just before it.

Return 3 to 6 hook starts and 3 to 6 cliffhanger ends per episode, strongest first. This is a recall step; later code prunes candidates. Return fewer only if the episode truly has fewer.

Hook types:
""" + "\n".join(f"{code} {meaning}" for code, meaning in HOOK_TYPES.items()) + "\n\nCliff types:\n" + "\n".join(
    f"{code} {meaning}" for code, meaning in CLIFF_TYPES.items()) + """

Strength: 3 = strongest, 2 = medium, 1 = weakest.
Each why field: max 12 words.
Reveal/resolution hints may be incomplete.
Return only line IDs from this episode's allowed enum. Never return timestamps."""


def schema(episode: Episode) -> dict:
    def item(kind: str, codes: dict) -> dict:
        return obj({"line_id": enum([line.id for line in episode.lines]),
                    kind: enum(list(codes)), "strength": enum(["1", "2", "3"]), "why": words(12)})
    return obj({"hook_starts": array(item("hook_type", HOOK_TYPES)),
                "cliff_ends": array(item("cliff_type", CLIFF_TYPES))})


def messages(episode: Episode, header: dict, sheet: dict, marks: dict) -> list[dict]:
    context = {"show_header": fields(header), "characters": roles(sheet),
               "reveal_resolution_hints": {"note": "hints, may be incomplete", "marks": marks["marks"]}}
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False) + "\n" + compact([episode])}]


def clean(data: dict, episode: Episode) -> tuple[dict, dict]:
    data = copy.deepcopy(data)
    order = {line.id: line.idx for line in episode.lines if line.ep == episode.ep}
    dropped = duplicates = 0
    for name in ("hook_starts", "cliff_ends"):
        if isinstance(data, dict) and isinstance(data.get(name), list):
            valid = []
            for item in data[name]:
                if isinstance(item, dict) and isinstance(item.get("line_id"), str) and item["line_id"] not in order:
                    dropped += 1
                else:
                    valid.append(item)
            data[name] = valid
    validate(data, schema(episode))
    trims = Counter({"hook_starts.why": 0, "cliff_ends.why": 0})
    for name in ("hook_starts", "cliff_ends"):
        selected = {}
        for item in data[name]:
            item["why"] = trim(item["why"], 12, name + ".why", trims)
            previous = selected.get(item["line_id"])
            duplicates += previous is not None
            if previous is None or int(item["strength"]) > int(previous["strength"]):
                selected[item["line_id"]] = item
        data[name] = sorted(selected.values(), key=lambda item: order[item["line_id"]])
    model_hooks, model_cliffs = len(data["hook_starts"]), len(data["cliff_ends"])
    for item in data["cliff_ends"]:
        item["source"] = "model"
    last = next((line for line in reversed(episode.lines) if line.kind in ("dialogue", "action")), None)
    added = bool(last and last.id not in {item["line_id"] for item in data["cliff_ends"]})
    if added:
        data["cliff_ends"].append({"line_id": last.id, "cliff_type": "C1", "strength": "2",
                                   "why": "Episode end.", "source": "episode_end"})
        data["cliff_ends"].sort(key=lambda item: order[item["line_id"]])
    data["counts"] = {"model_hooks": model_hooks, "model_cliffs": model_cliffs,
                      "hook_starts": len(data["hook_starts"]), "cliff_ends": len(data["cliff_ends"]),
                      "episode_end_added": int(added),
                      "by_hook_type": {code: sum(x["hook_type"] == code for x in data["hook_starts"]) for code in HOOK_TYPES},
                      "by_cliff_type": {code: sum(x["cliff_type"] == code for x in data["cliff_ends"]) for code in CLIFF_TYPES}}
    data["flags"] = {"low_recall": model_hooks < 2 or model_cliffs < 2}
    return data, {"dropped_invalid_ids": dropped, "duplicates_removed": duplicates, "trims_by_field": dict(trims)}


def build(episode: Episode, header: dict, sheet: dict, marks: dict, cfg: Config,
          client: LLMClient, no_cache: bool = False) -> dict:
    purpose = cfg.purposes.get("moments")
    result = client.call(cfg.active.picker, messages(episode, header, sheet, marks), schema(episode),
                         purpose=f"p03.moments.E{episode.ep:02d}", no_cache=no_cache,
                         reasoning_effort=purpose.reasoning_effort if purpose else None)
    data, checks = clean(result.data, episode)
    trims = Counter(checks.pop("trims_by_field"))
    return {"episode": episode.ep, **data, "metadata": metadata(result, trims, **checks)}
