from __future__ import annotations

from promo_finder import reveals


def test_reveal_schema_ids_and_descriptions(episode_factory):
    episode = episode_factory(5, [(0, 10), (10, 20)])
    props = reveals.schema(episode)["properties"]["marks"]["items"]["properties"]
    assert props["line_id"]["enum"] == [line.id for line in episode.lines]
    assert props["what"] == {"type": "string", "description": "max 12 words"}


def test_recheck_drops_bad_ids_deduplicates_and_sorts(episode_factory):
    episode = episode_factory(5, [(0, 10), (10, 20)])
    def mark(line_id, kind="reveal", confidence="low"):
        return {"line_id": line_id, "type": kind, "confidence": confidence, "what": "invented fact"}
    data = {"marks": [mark(episode.lines[1].id), mark("E19-L001"), mark("E05-L999"),
                      mark(episode.lines[0].id, "resolution"), mark(episode.lines[1].id, confidence="high")]}
    marks, checks = reveals.clean(data, episode)
    assert [mark["line_id"] for mark in marks] == [line.id for line in episode.lines]
    assert marks[1]["confidence"] == "high"
    assert checks["dropped_invalid_ids"] == 2 and checks["duplicates_removed"] == 1


def test_what_trim_and_empty_marks(episode_factory):
    episode = episode_factory(5, [(0, 10)])
    marks, checks = reveals.clean({"marks": [{"line_id": episode.lines[0].id, "type": "reveal",
        "confidence": "medium", "what": " ".join(["invented"] * 14)}]}, episode)
    assert len(marks[0]["what"].split()) == 12 and checks["trims_by_field"]["what"] == 1
    assert reveals.clean({"marks": []}, episode)[0] == []


def test_v2_prompt_empty_allowed_and_purpose_effort(write_config, episode_factory):
    from promo_finder.config import PurposeCfg, load_config
    from promo_finder.header import LIMITS
    from test_llm import make_client, resp
    cfg = load_config(write_config())
    cfg.purposes["reveals"] = PurposeCfg(reasoning_effort="low")
    episode = episode_factory(5, [(0, 1000)])
    client, fake, _, _ = make_client(cfg, [resp('{"marks": []}')])
    result = reveals.build(episode, {key: "invented" for key in LIMITS}, {"characters": []}, cfg, client,
                           purpose_prefix="p03")
    assert result["marks"] == [] and result["metadata"]["version"] == 2
    prompt = fake.calls[0]["messages"][0]["content"]
    for required in ("Read every scene.", "an empty list is allowed if there truly are none", "hidden identity, lie",
                     "to the viewer", "an apology accepted", "E99-L001 = reveal; E99-L002 = resolution"):
        assert required in prompt
    assert "Return at least" not in prompt and "minimum count" not in prompt
    assert fake.calls[0]["reasoning_effort"] == "low"
