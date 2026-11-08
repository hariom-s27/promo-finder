from __future__ import annotations

from types import SimpleNamespace

from promo_finder import header
from promo_finder.config import load_config
from promo_finder.llm import LLMResult, schema_errors


def test_header_schema_and_description_limits():
    schema = header.schema()
    assert schema["required"] == list(header.LIMITS)
    assert schema["additionalProperties"] is False
    for field, limit in header.LIMITS.items():
        assert schema["properties"][field] == {"type": "string", "description": f"max {limit} words"}
    assert schema_errors({}, schema)


def test_header_trims_each_field_after_validation(episode_factory, write_config):
    episode = episode_factory(5, [(0, 10)])
    fake = SimpleNamespace(call=lambda *args, **kwargs: LLMResult(
        data={field: " ".join(["invented"] * (limit + 2)) for field, limit in header.LIMITS.items()},
        model_string="fake-model", cache_key="fake-key"))
    result = header.build([episode], {"characters": []}, load_config(write_config()), fake)
    for field, limit in header.LIMITS.items():
        assert len(result[field].split()) == limit
        assert result["metadata"]["trims_by_field"][field] == 1


def test_header_input_excludes_aliases_mentions_and_first_line(episode_factory):
    episode = episode_factory(5, [(0, 10)])
    sheet = {"characters": [{"speaker_label": "TEST SPEAKER", "role": "invented role", "relationships": [],
                             "aliases": ["EXCLUDED ALIAS"], "first_line": episode.lines[0].id}],
             "mentioned_names": ["EXCLUDED MENTION"]}
    text = header.messages([episode], sheet)[1]["content"]
    assert "EXCLUDED" not in text and "first_line" not in text
    assert "relationships" in text and "loglines" in text
