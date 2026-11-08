from __future__ import annotations

import json

from promo_finder import moments
from promo_finder.config import PurposeCfg, load_config
from promo_finder.header import LIMITS
from test_llm import make_client, resp


def item(line_id, kind="hook_type", strength="2", why="invented reason"):
    return {"line_id": line_id, kind: "H3" if kind == "hook_type" else "C1", "strength": strength, "why": why}


def test_episode_enums_and_strict_schema(episode_factory):
    episode = episode_factory(5, [(0, 1000), (1000, 2000)])
    schema = moments.schema(episode)
    for name in ("hook_starts", "cliff_ends"):
        props = schema["properties"][name]["items"]["properties"]
        assert props["line_id"]["enum"] == [line.id for line in episode.lines]
        assert props["strength"]["enum"] == ["1", "2", "3"]
        assert props["why"] == {"type": "string", "description": "max 12 words"}
    def walk(node):
        if isinstance(node, dict):
            assert not {"pattern", "minLength", "maxLength", "minItems"} & node.keys()
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert node["required"] == list(node["properties"])
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(schema)


def test_clean_bad_ids_strength_dedupe_order_trim_and_fallback(episode_factory):
    episode = episode_factory(5, [(i * 1000, (i + 1) * 1000) for i in range(4)])
    ids = [line.id for line in episode.lines]
    data, checks = moments.clean({"hook_starts": [item(ids[1], strength="1"), item("E19-L001"),
        item(ids[0], why=" ".join(["invented"] * 15)), item(ids[1], strength="3")],
        "cliff_ends": [item(ids[2], "cliff_type"), item("E05-L999", "cliff_type")]}, episode)
    assert [x["line_id"] for x in data["hook_starts"]] == ids[:2]
    assert data["hook_starts"][1]["strength"] == "3"
    assert len(data["hook_starts"][0]["why"].split()) == 12
    assert checks["dropped_invalid_ids"] == 2 and checks["duplicates_removed"] == 1
    assert checks["trims_by_field"]["hook_starts.why"] == 1
    assert data["flags"]["low_recall"] and data["counts"]["model_cliffs"] == 1
    assert data["cliff_ends"][-1] == {"line_id": ids[-1], "cliff_type": "C1", "strength": "2",
        "why": "Episode end.", "source": "episode_end"}


def test_episode_end_uses_last_dialogue_action_and_is_not_duplicated(episode_factory):
    episode = episode_factory(5, [(0, 1000), (1000, 2000), (2000, 3000)])
    episode.lines[-1].kind = "camera"
    episode.lines[1].kind = "action"
    last = episode.lines[1].id
    data, _ = moments.clean({"hook_starts": [], "cliff_ends": [item(last, "cliff_type")]}, episode)
    assert data["counts"]["episode_end_added"] == 0
    assert data["cliff_ends"][0]["source"] == "model"
    data, _ = moments.clean({"hook_starts": [], "cliff_ends": []}, episode)
    assert data["cliff_ends"][0]["line_id"] == last and data["flags"]["low_recall"]


def test_normal_recall_and_equal_strength_first_wins(episode_factory):
    episode = episode_factory(5, [(0, 1000), (1000, 2000)])
    ids = [line.id for line in episode.lines]
    data, _ = moments.clean({"hook_starts": [item(ids[0], why="first"), item(ids[0], why="second"), item(ids[1])],
        "cliff_ends": [item(key, "cliff_type") for key in ids]}, episode)
    assert not data["flags"]["low_recall"] and data["hook_starts"][0]["why"] == "first"


def test_moment_build_effort_provenance_and_context(write_config, episode_factory):
    cfg = load_config(write_config())
    cfg.purposes["moments"] = PurposeCfg(reasoning_effort="low")
    episode = episode_factory(5, [(0, 1000)])
    client, fake, _, _ = make_client(cfg, [resp(json.dumps({"hook_starts": [], "cliff_ends": []}))])
    header = {key: "invented" for key in LIMITS}
    sheet = {"characters": [{"speaker_label": "TEST SPEAKER", "role": "invented role", "relationships": []}]}
    result = moments.build(episode, header, sheet, {"marks": []}, cfg, client)
    request = fake.calls[0]
    assert request["reasoning_effort"] == "low" and "temperature" not in request
    assert "hints, may be incomplete" in request["messages"][1]["content"]
    assert result["metadata"]["model_string"] == "fake-model-2026" and len(result["metadata"]["cache_key"]) == 64
    for code, meaning in {**moments.HOOK_TYPES, **moments.CLIFF_TYPES}.items():
        assert f"{code} {meaning}" in request["messages"][0]["content"]
