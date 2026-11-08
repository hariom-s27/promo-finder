from __future__ import annotations

import pytest

from promo_finder.intensity import profile


def test_deterministic_normalized_smoothed_and_text_free(episode_factory):
    episode = episode_factory(5, [(0, 10), (10, 20), (20, 30)])
    episode.lines[0].text = "invented ordinary statement with several extra words"
    episode.lines[1].text = "INVENTED! WHY?!"
    episode.lines[1].emotion = " ANGRY "
    episode.lines[1].speaker = "INVENTED SECOND"
    episode.lines[2].kind = "sfx"
    rows = profile(episode)
    assert rows == profile(episode)
    assert min(row["score"] for row in rows) == 0
    assert max(row["score"] for row in rows) == 1
    assert all(0 <= row["smooth"] <= 1 for row in rows)
    assert rows[0]["smooth"] == pytest.approx((rows[0]["score"] + rows[1]["score"]) / 2)
    assert rows[1]["smooth"] == pytest.approx(sum(row["score"] for row in rows) / 3)
    assert rows[1]["features"] == {"exclamations": 2, "questions": 1, "all_caps_words": 2,
        "strong_emotion": 1, "sfx": 0, "action_violence_shock": 0, "speaker_change": 1, "short_dialogue": 1}
    assert rows[2]["features"]["sfx"] == 1
    assert all(set(row) == {"line_id", "score", "smooth", "features"} for row in rows)


def test_constant_and_empty_profile(episode_factory):
    episode = episode_factory(5, [(0, 10), (10, 20)])
    assert all(row["score"] == row["smooth"] == 0 for row in profile(episode))
    episode.lines = []
    assert profile(episode) == []


def test_action_verb_boundaries_and_previous_dialogue(episode_factory):
    episode = episode_factory(5, [(0, 10), (10, 20), (20, 30), (30, 40)])
    episode.lines[1].kind = "action"
    episode.lines[1].text = "invented shove action"
    episode.lines[2].speaker = "INVENTED SECOND"
    episode.lines[3].kind = "action"
    episode.lines[3].text = "invented shovel prop"
    rows = profile(episode)
    assert rows[1]["features"]["action_violence_shock"] == 1
    assert rows[3]["features"]["action_violence_shock"] == 0
    assert rows[2]["features"]["speaker_change"] == 1
    assert rows[0]["features"]["speaker_change"] == 0


def test_configured_weights_control_score(episode_factory):
    from promo_finder.config import IntensityCfg

    episode = episode_factory(5, [(0, 10), (10, 20)])
    episode.lines[0].text = "invented!"
    episode.lines[1].text = "invented?"
    cfg = IntensityCfg()
    cfg.weights = {key: 0 for key in cfg.weights}
    cfg.weights["questions"] = 1
    assert [row["score"] for row in profile(episode, cfg)] == [0, 1]
