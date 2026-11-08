from __future__ import annotations

from types import SimpleNamespace

from promo_finder import characters
from promo_finder.config import load_config
from promo_finder.llm import LLMResult, schema_errors


def test_gap_aware_four_episode_chunks(episode_factory):
    episodes = [episode_factory(ep, [(0, 10)]) for ep in [5, 6, 7, 8, 19, 20, 21, 22]]
    assert [[e.ep for e in group] for group in characters.chunks(episodes)] == [[5, 6, 7, 8], [19, 20, 21, 22]]
    assert [[e.ep for e in group] for group in characters.chunks(episodes, 3)] == [[5, 6, 7], [8], [19, 20, 21], [22]]


def test_character_schema_real_ids_and_labels_only(episode_factory):
    episode = episode_factory(5, [(0, 10), (10, 20)])
    episode.lines[1].speaker = "INVENTED SECOND"
    properties = characters.schema([episode])["properties"]["characters"]["items"]["properties"]
    assert properties["first_line"]["enum"] == [line.id for line in episode.lines]
    assert properties["speaker_label"]["enum"] == ["TEST SPEAKER", "INVENTED SECOND"]
    assert properties["relationships"]["items"]["properties"]["other_label"]["enum"] == properties["speaker_label"]["enum"]
    assert schema_errors("E05-L999", properties["first_line"])


def test_chunk_trims_corrects_first_line_and_checks_alias_provenance(episode_factory, write_config):
    episode = episode_factory(5, [(0, 10), (10, 20)])
    episode.lines[0].text = "invented alias and invented mention"
    data = {"characters": [{"speaker_label": "TEST SPEAKER", "role": " ".join(["invented"] * 8),
        "relationships": [{"other_label": "TEST SPEAKER", "relation": " ".join(["invented"] * 5)}],
        "aliases": ["invented alias", "absent invented alias"], "first_line": episode.lines[1].id}],
        "mentioned_names": ["invented mention", "TEST SPEAKER", "absent invented mention"]}
    fake = SimpleNamespace(call=lambda *args, **kwargs: LLMResult(data=data, model_string="fake-model", cache_key="fake-key"))
    result = characters.build_chunk([episode], load_config(write_config()), fake, 1)
    assert len(result["characters"][0]["role"].split()) == 6
    assert result["characters"][0]["first_line"] == episode.lines[0].id
    assert result["characters"][0]["aliases"] == ["invented alias"]
    assert result["mentioned_names"] == ["invented mention"]
    assert result["metadata"]["trims_by_field"]["role"] == 1
    assert result["metadata"]["trims_by_field"]["relationships.relation"] == 1
    assert result["metadata"]["first_line_corrections"] == 1
    assert result["metadata"]["dropped_unverified_names"] == 3


def test_merge_two_chunks_unions_and_keeps_earliest(episode_factory):
    episodes = [episode_factory(ep, [(0, 10)]) for ep in [5, 19]]
    def chunk(episode, alias, relation, role):
        return {"characters": [{"speaker_label": "TEST SPEAKER", "role": role,
            "relationships": [{"other_label": "TEST SPEAKER", "relation": relation}],
            "aliases": [alias], "first_line": episode.lines[0].id}], "mentioned_names": [],
            "metadata": {"model_string": "fake-model", "cache_key": str(episode.ep), "trims_by_field": {"role": 1}}}
    sheet = characters.merge([chunk(episodes[0], "invented alias", "invented link", "first role"),
                              chunk(episodes[1], "INVENTED ALIAS", "second link", "later role")], episodes)
    char = sheet["characters"][0]
    assert char["role"] == "first role" and char["first_line"] == episodes[0].lines[0].id
    assert len(char["aliases"]) == 1 and len(char["relationships"]) == 2
    assert sheet["coverage"] == 1 and not sheet["coverage_below_target"]
    assert sheet["metadata"]["trims_by_field"] == {"role": 2}


def test_camera_compaction_limit(episode_factory):
    from promo_finder.understanding_common import compact
    episode = episode_factory(5, [(0, 10)])
    episode.lines[0].kind = "camera"
    episode.lines[0].text = "x" * 200
    assert compact([episode]).endswith("x" * 120)


def test_alias_and_mentioned_name_trims_are_counted(episode_factory, write_config):
    episode = episode_factory(5, [(0, 10)])
    long_name = "invented first second third fourth fifth sixth seventh"
    episode.lines[0].text = long_name
    data = {"characters": [{"speaker_label": "TEST SPEAKER", "role": "invented role",
        "relationships": [], "aliases": [long_name], "first_line": episode.lines[0].id}],
        "mentioned_names": [long_name]}
    fake = SimpleNamespace(call=lambda *args, **kwargs: LLMResult(data=data, model_string="fake-model"))
    result = characters.build_chunk([episode], load_config(write_config()), fake, 1)
    assert len(result["characters"][0]["aliases"][0].split()) == 6
    assert len(result["mentioned_names"][0].split()) == 6
    assert result["metadata"]["trims_by_field"]["aliases"] == 1
    assert result["metadata"]["trims_by_field"]["mentioned_names"] == 1
