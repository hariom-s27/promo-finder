from __future__ import annotations

import pytest

from promo_finder.policy import PolicyScanner


@pytest.mark.parametrize("text,category,term", [
    ("invented GUN prop", "violence", "gun"),
    ("invented heavy breathing cue", "sexual", "heavy breathing"),
    ("invented drugged condition", "nonconsent_abuse", "drugged"),
    ("invented rooftop location", "self_harm", "rooftop"),
    ("invented high school setting", "minors", "high school"),
    ("invented bastard insult", "profanity", "bastard"),
    ("invented screaming cue", "shock_fear", "screaming"),
    ("invented I\u2019LL KILL YOU phrase", "violence", "i'll kill you"),
])
def test_categories_and_canonical_terms(episode_factory, text, category, term):
    line = episode_factory(5, [(0, 10)]).lines[0]
    line.text = text
    flags = PolicyScanner().scan([line])
    assert {"line_id": line.id, "category": category, "term": term} in flags
    assert all(set(flag) == {"line_id", "category", "term"} for flag in flags)


def test_word_boundaries_and_same_line_combos(episode_factory):
    episode = episode_factory(5, [(0, 10), (10, 20), (20, 30), (30, 40)])
    for line, text in zip(episode.lines, ["invented childlike shotgun shovel end item", "invented kiss", "invented passionate", "invented boyfriend"]):
        line.text = text
    assert PolicyScanner().scan(episode.lines) == []


@pytest.mark.parametrize("text,category,term", [
    ("invented passionate kiss", "sexual", "kiss + passionate"),
    ("invented kiss on the bed", "sexual", "kiss + on the bed"),
    ("invented fiancé hit", "nonconsent_abuse", "fiancé + hit"),
    ("invented fiance choke", "nonconsent_abuse", "fiance + choke"),
    ("invented husband slap", "nonconsent_abuse", "husband + slap"),
    ("invented boyfriend hit", "nonconsent_abuse", "boyfriend + hit"),
])
def test_both_combo_rules(episode_factory, text, category, term):
    line = episode_factory(5, [(0, 10)]).lines[0]
    line.text = text
    scanner = PolicyScanner()
    assert {"line_id": line.id, "category": category, "term": term} in scanner.scan([line])
    assert scanner.promo_flags([line.id])[category] == [line.id]
    assert scanner.promo_flags([]) == {}


def test_phrase_whitespace_and_distinct_hits(episode_factory):
    line = episode_factory(5, [(0, 10)]).lines[0]
    line.text = "invented high\n school high school"
    assert PolicyScanner().scan([line]) == [{"line_id": line.id, "category": "minors", "term": "high school"}]
