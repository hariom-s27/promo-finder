"""Five-field show header with code-enforced word limits."""

from __future__ import annotations

import json
from collections import Counter

from .characters import roles
from .config import Config
from .llm import LLMClient
from .models import Episode
from .understanding_common import DATA_RULE, metadata, obj, trim, validate, words

LIMITS = {"genre": 4, "central_conflict": 20, "main_relationships": 25, "tone": 6, "setting": 10}


def schema() -> dict:
    return obj({field: words(limit) for field, limit in LIMITS.items()})


def messages(episodes: list[Episode], sheet: dict) -> list[dict]:
    return [{"role": "system", "content": DATA_RULE + " Summarize the show in the five short fields. "
             "Use only the supplied episode loglines and character roles/relationships. Respect field word limits."},
            {"role": "user", "content": json.dumps({
                "loglines": [{"episode": episode.ep, "logline": episode.logline} for episode in episodes],
                "characters": roles(sheet)}, ensure_ascii=False)}]


def build(episodes: list[Episode], sheet: dict, cfg: Config, client: LLMClient, no_cache: bool = False) -> dict:
    result = client.call(cfg.active.picker, messages(episodes, sheet), schema(),
                         purpose="p02.header", no_cache=no_cache)
    validate(result.data, schema())
    trims = Counter({field: 0 for field in LIMITS})
    data = {field: trim(result.data[field], limit, field, trims) for field, limit in LIMITS.items()}
    return {**data, "metadata": metadata(result, trims)}


def fields(header: dict) -> dict:
    return {field: header[field] for field in LIMITS}
