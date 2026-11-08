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
