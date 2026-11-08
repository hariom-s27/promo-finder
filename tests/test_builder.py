from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from promo_finder import builder
from promo_finder.checker import build_index, check_promo
from promo_finder.config import load_config


@pytest.fixture
def bcfg(write_config):
    cfg = load_config(write_config())
    # Existing cases explicitly exercise the P03 switches; P05 defaults are tested below.
    cfg.spoiler.reveal_mode = "block"
    cfg.spoiler.resolution_block_confidence = ["low", "medium", "high"]
    cfg.builder.max_speakers = 3
    cfg.builder.j5_at_final_end = True
    return cfg


def bundle(episode_factory, ep=5, n=20, step=5000, hook=0, cliff=3):
    episode = episode_factory(ep, [(i * step, (i + 1) * step) for i in range(n)])
    ids = [line.id for line in episode.lines]
    provenance = {"model_string": "invented-model", "cache_key": "invented-cache-key"}
    moments = {"episode": ep, "hook_starts": [{"line_id": ids[hook], "hook_type": "H3", "strength": "3", "why": "invented"}],
               "cliff_ends": [{"line_id": ids[cliff], "cliff_type": "C1", "strength": "2", "why": "invented", "source": "model"}],
               "metadata": dict(provenance)}
    reveals = {"episode": ep, "marks": [], "metadata": {**provenance, "version": 2}}
    intensity = [{"line_id": key, "smooth": 0.4} for key in ids]
    return episode, moments, reveals, intensity, []


def build(data, cfg, previous=None):
    return builder.build_episode(*data, cfg, previous)


def mark(data, index=1, kind="reveal"):
    data[2]["marks"].append({"line_id": data[0].lines[index].id, "type": kind, "confidence": "high", "what": "invented event"})


@pytest.mark.parametrize("cliff,duration", [(3, 20), (11, 60)])
def test_continuous_inclusive_bounds(episode_factory, bcfg, cliff, duration):
    data = bundle(episode_factory, cliff=cliff)
    output, summary = build(data, bcfg)
    promo = output["candidates"][0]
    assert promo["duration_s"] == duration and not promo["montage"]
    assert summary["generated"] == summary["kept"] == 1
    index = build_index([data[0]])
    checked = check_promo([(s["first_line_id"], s["last_line_id"]) for s in promo["segments"]], index, bcfg)
    assert checked.ok and checked.total_ms == duration * 1000


def test_short_and_unbuildable_long_are_counted(episode_factory, bcfg):
    output, summary = build(bundle(episode_factory, cliff=2), bcfg)
    assert output["candidates"] == [] and summary["checker_errors"] == {"TOO_SHORT": 1}
    bcfg.builder.max_segments = 1
    output, summary = build(bundle(episode_factory, cliff=12), bcfg)
    assert output["candidates"] == [] and summary["dropped"]["checker"] == 1


def test_montage_two_pieces_no_overlap_and_checker_times(episode_factory, bcfg):
    data = bundle(episode_factory, cliff=17)
    output, summary = build(data, bcfg)
    promo = output["candidates"][0]
    assert promo["montage"] and promo["duration_s"] == 20
    assert promo["pre_score"] == pytest.approx(4.65)
    first, second = promo["segments"]
    assert first["start_ms"] == 0 and first["end_ms"] == 10000
    assert second["start_ms"] == 80000 and second["end_ms"] == 90000
    assert first["end_ms"] <= second["start_ms"] and len(promo["line_ids"]) == len(set(promo["line_ids"]))
    assert check_promo([(s["first_line_id"], s["last_line_id"]) for s in promo["segments"]], build_index([data[0]]), bcfg).ok
    assert sum(summary["dropped"].values()) + summary["kept"] == summary["generated"]


@pytest.mark.parametrize("failure", ["scene", "oversized_line", "short_tail"])
def test_montage_construction_constraints(episode_factory, bcfg, failure):
    data = list(bundle(episode_factory, cliff=17))
    if failure == "scene":
        data[0].lines[1].scene = 2
    elif failure == "oversized_line":
        data[0].lines[0].end_ms = 21000
    else:
        # First piece can reach eight seconds, but the only non-overlapping tail cannot make twenty.
        data[0] = episode_factory(5, [(0, 4000), (4000, 8000), (70000, 74000)])
        ids = [line.id for line in data[0].lines]
        data[1]["cliff_ends"][0]["line_id"] = ids[-1]
        data = (*data[:3], [{"line_id": key, "smooth": 0.4} for key in ids], [])
    output, summary = build(data, bcfg)
    assert output["candidates"] == [] and summary["dropped"]["checker"] == 1


@pytest.mark.parametrize("montage", [False, True])
def test_j2_checks_each_segment_start(episode_factory, bcfg, montage):
    data = bundle(episode_factory, hook=1 if not montage else 0, cliff=4 if not montage else 17)
    before = 0 if not montage else 15
    data[0].lines[before].speaker = "INVENTED OTHER"
    data[0].lines[before].text = "Invented question?   "
    output, summary = build(data, bcfg)
    assert not output["candidates"] and summary["dropped"]["J2"] == 1


def test_j2_same_speaker_question_does_not_drop(episode_factory, bcfg):
    data = bundle(episode_factory, hook=1, cliff=4)
    data[0].lines[0].text = "Invented question?"
    assert build(data, bcfg)[1]["kept"] == 1


def test_j4_requires_shared_speaker(episode_factory, bcfg):
    data = bundle(episode_factory, cliff=17)
    for line in data[0].lines[16:18]:
        line.speaker = "INVENTED OTHER"
    output, summary = build(data, bcfg)
    assert not output["candidates"] and summary["dropped"]["J4"] == 1


def test_j5_continuous_include_and_total_limit_flag(episode_factory, bcfg):
    data = bundle(episode_factory)
    data[0].lines[4].kind = "camera"
    promo = build(data, bcfg)[0]["candidates"][0]
    assert promo["duration_s"] == 25 and promo["segments"][0]["last_line_id"] == data[0].lines[4].id
    assert promo["cliff"]["line_id"] == data[0].lines[3].id and not promo["flags"]["reaction_cut"]
    data = bundle(episode_factory, cliff=11)
    data[0].lines[12].kind = "action"
    promo = build(data, bcfg)[0]["candidates"][0]
    assert promo["duration_s"] == 60 and promo["flags"]["reaction_cut"]
    assert promo["pre_score"] == pytest.approx(4.65)


@pytest.mark.parametrize("constraint", ["first_max", "scene", "overlap", "total", "tail_scene"])
def test_j5_montage_e1_precedence(episode_factory, bcfg, constraint):
    if constraint == "overlap":
        episode = episode_factory(5, [(0, 4000), (4000, 8000), (8000, 14000), (14000, 20000)])
        episode.lines[2].kind = "action"
        spans = [(episode.lines[0].id, episode.lines[1].id), (episode.lines[2].id, episode.lines[3].id)]
    elif constraint == "total":
        episode = episode_factory(5, [(0, 5000), (5000, 10000), (10000, 15000), (100000, 150000), (150000, 155000)])
        episode.lines[4].kind = "action"
        spans = [(episode.lines[0].id, episode.lines[1].id), (episode.lines[3].id, episode.lines[3].id)]
    else:
        episode = bundle(episode_factory, cliff=17)[0]
        spans = [(episode.lines[0].id, episode.lines[1].id), (episode.lines[16].id, episode.lines[17].id)]
        if constraint == "tail_scene":
            episode.lines[18].kind = "camera"
            episode.lines[18].scene = 2
        else:
            episode.lines[2].kind = "action"
            if constraint == "first_max":
                episode.lines[2].end_ms = 25000
            else:
                episode.lines[2].scene = 2
    actual, cut, included = builder.include_reactions(episode, spans, build_index([episode]), bcfg)
    assert actual == spans and cut and included == 0
    assert check_promo(actual, build_index([episode]), bcfg).ok


def test_j5_montage_allowed_reaction_is_included_once(episode_factory, bcfg):
    data = bundle(episode_factory, cliff=17)
    data[0].lines[2].kind = "action"
    data[0].lines[3].kind = "camera"
    output, summary = build(data, bcfg)
    assert output["candidates"][0]["segments"][0]["last_line_id"] == data[0].lines[2].id
    assert summary["reactions_included"] == 1


def test_speaker_cap_and_policy_flags_never_drop(episode_factory, bcfg):
    data = bundle(episode_factory)
    for number, line in enumerate(data[0].lines[:4]):
        line.speaker = f"INVENTED {number}"
    assert build(data, bcfg)[1]["dropped"]["speakers"] == 1
    data = list(bundle(episode_factory))
    data[4] = [{"line_id": data[0].lines[1].id, "category": "violence", "term": "punch"}]
    promo = build(data, bcfg)[0]["candidates"][0]
    assert promo["policy"] == {"violence": [data[0].lines[1].id]}


@pytest.mark.parametrize("mode", ["block", "flag"])
def test_resolution_always_drops_including_added_reaction(episode_factory, bcfg, mode):
    bcfg.spoiler.reveal_mode = mode
    data = bundle(episode_factory)
    data[0].lines[4].kind = "action"
    mark(data, 4, "resolution")
    output, summary = build(data, bcfg)
    assert not output["candidates"] and summary["dropped"]["resolution"] == 1
    assert all(row["kept"] == 0 for row in summary["reveal_mode_comparison"].values())


def test_reveal_block_and_flag_counterfactual(episode_factory, bcfg):
    data = bundle(episode_factory)
    mark(data)
    output, summary = build(data, bcfg)
    assert not output["candidates"] and summary["dropped"]["reveal"] == 1
    assert summary["reveal_mode_comparison"] == {"block": {"pre_dedupe_kept": 0, "kept": 0},
                                                   "flag": {"pre_dedupe_kept": 1, "kept": 1}}
    bcfg.spoiler.reveal_mode = "flag"
    promo = build(data, bcfg)[0]["candidates"][0]
    assert promo["flags"]["contains_reveal"]


def test_late_series_drop(episode_factory, bcfg):
    output, summary = build(bundle(episode_factory, ep=46), bcfg)
    assert not output["candidates"] and summary["dropped"]["late_series"] == 1


def test_recap_similarity_normalization_and_penalty(episode_factory, bcfg):
    data = bundle(episode_factory, ep=6)
    previous = episode_factory(5, [(0, 1000)])
    previous.lines[-1].text = "THE, secret -- parcel!"
    data[0].lines[0].text = "the   secret parcel"
    output, summary = build(data, bcfg, previous)
    promo = output["candidates"][0]
    assert promo["flags"]["possible_recap"] and promo["pre_score"] == pytest.approx(4.9)
    assert summary["recap"]["method"] == "similarity"
    assert summary["recap"]["flagged_kept"] == {"similarity": 1, "fallback": 0}
    assert builder.normalized_recap("  A, B!  ") == "a b"


def test_recap_scan_and_predecessor_tail_limits(episode_factory, bcfg):
    current = bundle(episode_factory, ep=6)[0]
    previous = episode_factory(5, [(0, 1000), (1000, 2000)])
    previous.lines[0].text = "invented repeated event"
    previous.lines[1].text = "different"
    for line in current.lines:
        line.text = "invented repeated event"
    bcfg.builder.recap_prev_tail_lines = 1
    assert builder.recap_lines(current, previous, bcfg)[0] == set()
    previous.lines[-1].text = "invented repeated event"
    bcfg.builder.recap_scan_lines = 1
    assert builder.recap_lines(current, previous, bcfg)[0] == {current.lines[0].id}


@pytest.mark.parametrize("ratio,expected", [(0.85, True), (0.849, False)])
def test_recap_similarity_inclusive_threshold(episode_factory, bcfg, monkeypatch, ratio, expected):
    current = bundle(episode_factory, ep=6)[0]
    previous = episode_factory(5, [(0, 1000)])
    monkeypatch.setattr(builder, "SequenceMatcher", lambda *args: SimpleNamespace(ratio=lambda: ratio))
    ids, method = builder.recap_lines(current, previous, bcfg)
    assert bool(ids) is expected and method == "similarity"


@pytest.mark.parametrize("ep,hook,expected", [(1, 0, True), (5, 0, True), (5, 1, False), (6, 0, True)])
def test_recap_fallback_window(episode_factory, bcfg, ep, hook, expected):
    output, summary = build(bundle(episode_factory, ep=ep, hook=hook, cliff=hook + 3), bcfg)
    assert output["candidates"][0]["flags"]["possible_recap"] is expected
    assert summary["recap"]["method"] == "fallback"


def test_recap_available_predecessor_does_not_trigger_fallback(episode_factory, bcfg):
    data = bundle(episode_factory, ep=6)
    previous = episode_factory(5, [(0, 1000)])
    previous.lines[0].text = "entirely different material"
    output, summary = build(data, bcfg, previous)
    assert not output["candidates"][0]["flags"]["possible_recap"]
    assert summary["recap"]["flagged_kept"] == {"similarity": 0, "fallback": 0}


def test_held_out_predecessor_never_discovered_or_read(episode_factory, bcfg, monkeypatch):
    episode = bundle(episode_factory)[0]
    monkeypatch.setattr(builder, "find_episode_files", lambda *args: pytest.fail("held-out predecessor discovery"))
    assert builder.previous_episode(bcfg, episode, {}) is None
    class Sealed:
        ep = 4
        @property
        def lines(self):
            pytest.fail("held-out predecessor text read")
    assert builder.recap_lines(episode, Sealed(), bcfg)[1] == "fallback"


def test_unavailable_predecessor_and_selected_predecessor(episode_factory, bcfg, monkeypatch):
    episode = bundle(episode_factory, ep=6)[0]
    monkeypatch.setattr(builder, "find_episode_files", lambda *args: [])
    assert builder.previous_episode(bcfg, episode, {}) is None
    previous = episode_factory(5, [(0, 1000)])
    assert builder.previous_episode(bcfg, episode, {5: previous}) is previous


def test_dedupe_keeps_higher_pre_score(episode_factory, bcfg):
    data = bundle(episode_factory)
    other = copy.deepcopy(data[1]["cliff_ends"][0])
    other.update(line_id=data[0].lines[4].id, strength="1")
    data[1]["cliff_ends"].append(other)
    output, summary = build(data, bcfg)
    assert len(output["candidates"]) == 1 and summary["dropped"]["dedupe"] == 1
    assert output["candidates"][0]["cliff"]["line_id"] == data[0].lines[3].id


def candidate(start, end, score=5):
    return {"pre_score": score, "montage": False, "_hook_order": start, "_cliff_order": end,
            "segments": [{"episode": 5, "start_ms": start, "end_ms": end,
                          "first_line_id": f"invented-{start}", "last_line_id": f"invented-{end}"}]}


def test_dedupe_strict_threshold_and_cap(bcfg):
    kept, drops = builder.dedupe_cap([candidate(0, 34000), candidate(6000, 40000)], bcfg)
    assert len(kept) == 2 and drops["dedupe"] == 0
    kept, drops = builder.dedupe_cap([candidate(0, 34000), candidate(5000, 39000)], bcfg)
    assert len(kept) == 1 and drops["dedupe"] == 1
    kept, drops = builder.dedupe_cap([candidate(i * 30000, i * 30000 + 20000, 10 - i) for i in range(9)], bcfg)
    assert len(kept) == 8 and drops == {"dedupe": 0, "cap": 1}


def test_equal_score_tie_prefers_continuous(bcfg):
    montage = candidate(0, 20000)
    montage["montage"] = True
    continuous = candidate(0, 20000)
    kept, _ = builder.dedupe_cap([montage, continuous], bcfg)
    assert not kept[0]["montage"]


def test_every_kept_candidate_passes_checker_and_accounts(episode_factory, bcfg):
    data = bundle(episode_factory)
    for number in (6, 9, 15, 18):
        cliff = copy.deepcopy(data[1]["cliff_ends"][0])
        cliff["line_id"] = data[0].lines[number].id
        data[1]["cliff_ends"].append(cliff)
    output, summary = build(data, bcfg)
    index = build_index([data[0]])
    for promo in output["candidates"]:
        checked = check_promo([(seg["first_line_id"], seg["last_line_id"]) for seg in promo["segments"]], index, bcfg)
        assert checked.ok
        assert promo["line_ids"] == [key for seg in checked.segments for key in seg.line_ids]
        assert promo["duration_s"] == checked.total_ms / 1000
    assert summary["generated"] == summary["kept"] + sum(summary["dropped"].values())
