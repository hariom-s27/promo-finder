"""Chunked character extraction and deterministic merging."""

from __future__ import annotations

from collections import Counter

from .config import Config
from .llm import LLMClient
from .models import Episode
from .policy import normalize, term_pattern
from .understanding_common import (DATA_RULE, array, compact, enum, metadata, obj,
                                   trim, validate, words)


def chunks(episodes: list[Episode], size: int = 4) -> list[list[Episode]]:
    if size < 1:
        raise ValueError("chunk size must be positive")
    result: list[list[Episode]] = []
    for episode in sorted(episodes, key=lambda e: e.ep):
        if not result or len(result[-1]) >= size or episode.ep != result[-1][-1].ep + 1:
            result.append([])
        result[-1].append(episode)
    return result


def schema(episodes: list[Episode]) -> dict:
    lines = [line for episode in episodes for line in episode.lines]
    labels = list(dict.fromkeys(line.speaker for line in lines if line.kind == "dialogue" and line.speaker))
    return obj({
        "characters": array(obj({
            "speaker_label": enum(labels), "role": words(6),
            "relationships": array(obj({"other_label": enum(labels), "relation": words(4)})),
            "aliases": array(words(6)), "first_line": enum([line.id for line in lines]),
        })),
        "mentioned_names": array(words(6)),
    })


def messages(episodes: list[Episode]) -> list[dict]:
    return [
        {"role": "system", "content": DATA_RULE + " Build a character sheet for every dialogue speaker. "
         "Roles: max 6 words; relations: max 4 words; aliases and mentioned names: max 6 words each. "
         "Aliases must be names/titles actually used in line text. Mentioned names must occur in text "
         "and must not be speaker labels. first_line is the earliest dialogue line with that speaker label."},
        {"role": "user", "content": compact(episodes)},
    ]


def build_chunk(episodes: list[Episode], cfg: Config, client: LLMClient, number: int,
                no_cache: bool = False) -> dict:
    response_schema = schema(episodes)
    result = client.call(cfg.active.picker, messages(episodes), response_schema,
                         purpose=f"p02.characters.chunk_{number:02d}", no_cache=no_cache)
    validate(result.data, response_schema)
    trims = Counter({name: 0 for name in ("role", "relationships.relation", "aliases", "mentioned_names")})
    first = {}
    text = normalize("\n".join(line.text for episode in episodes for line in episode.lines))
    for episode in episodes:
        for line in episode.lines:
            if line.kind == "dialogue" and line.speaker:
                first.setdefault(line.speaker, line.id)
    normalized_labels = {normalize(label) for label in first}
    corrected = dropped = 0
    characters = []
    for char in result.data["characters"]:
        label = char["speaker_label"]
        corrected += char["first_line"] != first[label]
        aliases = []
        for alias in char["aliases"]:
            shortened = trim(alias, 6, "aliases", trims)
            if shortened and term_pattern(alias).search(text):
                aliases.append(shortened)
            else:
                dropped += 1
        characters.append({"speaker_label": label, "role": trim(char["role"], 6, "role", trims),
                           "relationships": [
                               {"other_label": rel["other_label"],
                                "relation": trim(rel["relation"], 4, "relationships.relation", trims)}
                               for rel in char["relationships"]],
                           "aliases": aliases, "first_line": first[label]})
    mentioned = []
    for name in result.data["mentioned_names"]:
        shortened = trim(name, 6, "mentioned_names", trims)
        if shortened and normalize(name) not in normalized_labels and term_pattern(name).search(text):
            mentioned.append(shortened)
        else:
            dropped += 1
    return {"characters": characters, "mentioned_names": mentioned,
            "metadata": metadata(result, trims, episodes=[e.ep for e in episodes],
                                 first_line_corrections=corrected, dropped_unverified_names=dropped)}


def merge(chunks_data: list[dict], episodes: list[Episode]) -> dict:
    order = {line.id: (episode.ep, line.idx) for episode in episodes for line in episode.lines}
    merged = {}
    mentioned: dict[str, str] = {}
    for data in chunks_data:
        for name in data["mentioned_names"]:
            mentioned.setdefault(normalize(name), name)
        for char in data["characters"]:
            label = char["speaker_label"]
            if label not in merged:
                merged[label] = {**char, "aliases": [], "relationships": []}
            target = merged[label]
            if order[char["first_line"]] < order[target["first_line"]]:
                target["first_line"] = char["first_line"]
            aliases = {normalize(alias) for alias in target["aliases"]}
            for alias in char["aliases"]:
                if normalize(alias) not in aliases:
                    target["aliases"].append(alias)
                    aliases.add(normalize(alias))
            for rel in char["relationships"]:
                if rel not in target["relationships"]:
                    target["relationships"].append(dict(rel))
    labels = {normalize(label) for label in merged}
    dialogue = [line for episode in episodes for line in episode.lines if line.kind == "dialogue"]
    covered = sum(line.speaker in merged for line in dialogue)
    coverage = covered / len(dialogue) if dialogue else 0.0
    trims = Counter()
    for data in chunks_data:
        trims.update(data["metadata"]["trims_by_field"])
    return {"characters": sorted(merged.values(), key=lambda c: order[c["first_line"]]),
            "mentioned_names": [name for key, name in mentioned.items() if key not in labels],
            "coverage": coverage, "coverage_below_target": coverage < 0.95,
            "counts": {"characters": len(merged), "dialogue_lines": len(dialogue), "covered_dialogue_lines": covered},
            "metadata": {"model_strings": sorted({data["metadata"]["model_string"] for data in chunks_data}),
                         "cache_keys": [data["metadata"]["cache_key"] for data in chunks_data],
                         "trims_by_field": dict(trims), "chunks": [data["metadata"] for data in chunks_data]}}


def roles(sheet: dict) -> list[dict]:
    return [{key: char[key] for key in ("speaker_label", "role", "relationships")} for char in sheet["characters"]]
