"""P08b diagnostic: the replay must equal the builder; attribution, what-ifs and the fresh-set refusal.

Every episode, line, speaker and gold promo here is invented."""

from __future__ import annotations

import json
import random

import pytest

from promo_finder import builder
from promo_finder import diagnostic as D
from promo_finder.checker import build_index
from promo_finder.config import load_config
from promo_finder.models import Episode, Line, Scene, line_id
from promo_finder.scoring import GoldPromo, PredPromo

SPEAKERS = ["SPK A", "SPK B", "SPK C", "SPK D", "SPK E", "SPK F"]


@pytest.fixture
def cfg(write_config):
    return load_config(write_config())


# ── invented inputs ─────────────────────────────────────────────────────


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


def add_cliff(data, index, strength="1"):
    data[1]["cliff_ends"].append({"line_id": data[0].lines[index].id, "cliff_type": "C2", "strength": strength,
                                  "why": "invented", "source": "model"})


def mark(data, index, kind="resolution", confidence="high"):
    data[2]["marks"].append({"line_id": data[0].lines[index].id, "type": kind, "confidence": confidence, "what": "invented"})


def random_bundle(ep: int, seed: int):
    rng = random.Random(seed)
    n = rng.randint(40, 90)
    lines, t, scene = [], 0, 1
    pool = SPEAKERS[:rng.randint(2, 6)]
    for i in range(1, n + 1):
        if rng.random() < 0.1:
            scene += 1
        kind = rng.choices(["dialogue", "action", "camera"], [0.8, 0.15, 0.05])[0]
        dur = rng.choice([1500, 2500, 3500, 5000, 7000, 9000])
        text = f"invented line {i}" + ("?" if rng.random() < 0.2 else "")
        lines.append(Line(id=line_id(ep, i), ep=ep, idx=i, scene=scene, kind=kind,
                          speaker=rng.choice(pool) if kind == "dialogue" else None, text=text,
                          start_ms=t, end_ms=t + dur, src_line=i))
        t += dur
    scenes = [Scene(number=s, heading="T", start_ms=0, end_ms=t, line_ids=[x.id for x in lines if x.scene == s])
              for s in sorted({x.scene for x in lines})]
    episode = Episode(ep=ep, source_file=f"episode-{ep:03d}-Episode 0.txt", source_id="0", header_ep=ep,
                      scenes=scenes, lines=lines, duration_ms=t)
    ids = [x.id for x in lines]
    provenance = {"model_string": "invented-model", "cache_key": f"invented-{seed}"}
    hooks = rng.sample(ids[:-3], rng.randint(3, 8))
    cliffs = rng.sample(ids[3:], rng.randint(3, 8))
    moments = {"episode": ep,
               "hook_starts": [{"line_id": k, "hook_type": "H3", "strength": rng.choice("123"), "why": "invented"} for k in hooks],
               "cliff_ends": [{"line_id": k, "cliff_type": "C1", "strength": rng.choice("123"), "why": "invented",
                               "source": "model"} for k in cliffs], "metadata": dict(provenance)}
    marks = [{"line_id": rng.choice(ids), "type": rng.choice(["reveal", "resolution"]),
              "confidence": rng.choice(["low", "medium", "high"]), "what": "invented"} for _ in range(rng.randint(0, 3))]
    reveals = {"episode": ep, "marks": marks, "metadata": {**provenance, "version": 2}}
    intensity = [{"line_id": k, "smooth": rng.random()} for k in ids]
    policy = [{"line_id": rng.choice(ids), "category": "violence", "term": "invented"} for _ in range(rng.randint(0, 2))]
    return episode, moments, reveals, intensity, policy


# ── the replay equals the builder ───────────────────────────────────────

SEEDS = range(60)


@pytest.mark.parametrize("mode", ["flag", "block"])
def test_replay_equals_builder_on_random_episodes(cfg, mode):
    cfg.spoiler.reveal_mode = mode
    totals = {rule: 0 for rule in D.RULES}
    montage = kept = 0
    for seed in SEEDS:
        data = random_bundle(5 if seed % 7 else 47, seed)
        output, summary = builder.build_episode(*data, cfg, None)
        trace = D.trace_episode(*data, cfg, None)
        assert D.same_as_builder(trace, output["candidates"], summary) == [], f"seed {seed}"
        for rule in D.RULES:
            totals[rule] += trace.dropped[rule]
        montage += sum(p["montage"] for p in trace.candidates)
        kept += len(trace.candidates)
    # the generator really exercises the rules it claims to replay
    assert all(totals[rule] > 0 for rule in ("checker", "J2", "J4", "resolution", "late_series", "dedupe"))
    assert montage > 0 and kept > 0
    if mode == "block":
        assert totals["reveal"] > 0


def test_replay_pairs_account_for_every_generated_pair(cfg):
    for seed in range(15):
        trace = D.trace_episode(*random_bundle(5, seed), cfg, None)
        assert len(trace.pairs) == trace.generated
        assert sum(p.first_drop == "kept" for p in trace.pairs) == len(trace.candidates)
        assert sorted(trace.dropped) == sorted(D.RULES)
        for pair in trace.pairs:
            if pair.violations:  # removed by a per-pair rule before the pool
                assert pair.promo is None and pair.first_drop not in ("kept", "dedupe", "cap")
            else:                # reached the pool: kept, or removed by dedupe/cap
                assert pair.promo is not None and pair.first_drop in ("kept", "dedupe", "cap")


def test_same_as_builder_reports_differences(cfg, episode_factory):
    data = bundle(episode_factory, cliff=3)
    output, summary = builder.build_episode(*data, cfg, None)
    trace = D.trace_episode(*data, cfg, None)
    assert D.same_as_builder(trace, output["candidates"], summary) == []
    bad = dict(summary, generated=summary["generated"] + 1)
    assert D.same_as_builder(trace, output["candidates"], bad)
    assert D.same_as_builder(trace, [], summary) or not output["candidates"]


# ── attribution ─────────────────────────────────────────────────────────


def test_too_short_pair_is_attributed_and_still_matches_by_raw_span(cfg, episode_factory):
    trace = D.trace_episode(*bundle(episode_factory, cliff=2), cfg, None)  # 15 s
    (pair,) = trace.pairs
    assert pair.raw_status == "TOO_SHORT" and pair.built is None and pair.span == pair.raw
    assert pair.first_drop == "checker" and pair.drop_detail == "checker:TOO_SHORT"
    assert pair.violations == {"checker:TOO_SHORT"} and not trace.candidates


def test_j4_is_the_sole_blocker_and_flag_mode_keeps_it(cfg, episode_factory):
    data = bundle(episode_factory, cliff=17)
    for line in data[0].lines[16:18]:
        line.speaker = "INVENTED OTHER"
    drop = D.trace_episode(*data, cfg, None)
    (pair,) = drop.pairs
    assert pair.first_drop == "J4" and pair.violations == {"J4"} and not drop.candidates
    flag = D.trace_episode(*data, cfg, None, j4_mode="flag")
    (kept,) = flag.candidates
    assert flag.dropped["J4"] == 0 and kept["flags"]["no_shared_speaker"] is True and kept["montage"]
    unpenalised = D.trace_episode(*data, cfg, None, j4_mode="flag", j4_penalty=0.0).candidates[0]
    assert kept["pre_score"] == pytest.approx(unpenalised["pre_score"] - 0.25)
    # the flag key exists only in flag mode: v1 candidates never carry it
    assert "no_shared_speaker" not in D.trace_episode(*bundle(episode_factory, cliff=17), cfg, None).candidates[0]["flags"]


def test_every_violation_is_listed_not_only_the_first(cfg, episode_factory):
    data = bundle(episode_factory, cliff=2)
    mark(data, 1)  # a resolution line inside a too-short pair
    (pair,) = D.trace_episode(*data, cfg, None).pairs
    assert pair.first_drop == "checker" and pair.violations == {"checker:TOO_SHORT", "resolution"}


def test_resolution_drop_and_late_series(cfg, episode_factory):
    data = bundle(episode_factory, cliff=5)
    mark(data, 2)
    (pair,) = D.trace_episode(*data, cfg, None).pairs
    assert pair.first_drop == "resolution" and pair.violations == {"resolution"}
    (late,) = D.trace_episode(*bundle(episode_factory, ep=47, cliff=5), cfg, None).pairs
    assert late.first_drop == "late_series"


def test_dedupe_and_cap_attribution(cfg, episode_factory):
    data = bundle(episode_factory, n=40, cliff=5)
    for index in (6, 7, 8):
        add_cliff(data, index)  # near-identical cuts: dedupe keeps the best
    trace = D.trace_episode(*data, cfg, None)
    assert [p.first_drop for p in trace.pairs].count("dedupe") == trace.dropped["dedupe"] > 0
    cfg.builder.max_per_episode = 1
    capped = D.trace_episode(*data, cfg, None)
    assert capped.dropped["cap"] >= 0 and len(capped.candidates) == 1
    assert builder.build_episode(*data, cfg, None)[1]["dropped"] == capped.dropped


# ── F2 prototype ────────────────────────────────────────────────────────


def short_bundle(episode_factory, n=30, step=3000, cliff=2):
    return bundle(episode_factory, n=n, step=step, cliff=cliff)  # hook L001, cliff L003: 9 s


def extension(data, cfg, resolution_ids=(), cliff_ids=()):
    index = build_index([data[0]])
    ids = [x.id for x in data[0].lines]
    return D.extend_end(data[0], index, ids[0], ids[2], cfg, set(resolution_ids), set(cliff_ids))


def test_extension_stops_at_the_first_line_boundary_reaching_20s(cfg, episode_factory):
    data = short_bundle(episode_factory)
    ids = [x.id for x in data[0].lines]
    assert extension(data, cfg) == (ids[0], ids[6])  # 7 lines x 3 s = 21 s; 6 lines = 18 s is still short


def test_extension_stops_before_resolution_and_at_next_cliff(cfg, episode_factory):
    data = short_bundle(episode_factory)
    ids = [x.id for x in data[0].lines]
    assert extension(data, cfg, resolution_ids={ids[4]}) is None       # resolution before 20 s
    assert extension(data, cfg, resolution_ids={ids[6]}) is None       # the 21 s line itself is a resolution
    assert extension(data, cfg, resolution_ids={ids[7]}) == (ids[0], ids[6])
    assert extension(data, cfg, cliff_ids={ids[5]}) is None            # next cliff line (18 s) still short: stop
    assert extension(data, cfg, cliff_ids={ids[6]}) == (ids[0], ids[6])  # may end ON a later cliff line


def test_extension_fails_when_the_episode_ends(cfg, episode_factory):
    data = short_bundle(episode_factory, n=6)
    assert extension(data, cfg) is None


def test_trace_extend_keeps_flags_and_never_penalises(cfg, episode_factory):
    data = short_bundle(episode_factory)
    assert not D.trace_episode(*data, cfg, None).candidates
    trace = D.trace_episode(*data, cfg, None, too_short_mode="extend")
    (promo,) = trace.candidates
    (pair,) = trace.pairs
    assert promo["flags"]["extended"] is True and pair.extended and trace.extended_kept == 1
    assert promo["duration_s"] == 21 and promo["segments"][0]["last_line_id"] == data[0].lines[6].id
    # 3 + 2 + 0.4 intensity, minus the existing recap penalty 0.5 (hook in the first 5 s); none for extension
    assert promo["flags"]["possible_recap"] is True
    assert promo["pre_score"] == pytest.approx(3 + 2 + 0.4 - 0.5)
    assert pair.raw != pair.built and pair.raw_status == "TOO_SHORT"


def test_trace_extend_respects_resolution_in_the_window(cfg, episode_factory):
    data = short_bundle(episode_factory)
    mark(data, 4)
    trace = D.trace_episode(*data, cfg, None, too_short_mode="extend")
    assert not trace.candidates and trace.pairs[0].drop_detail == "checker:TOO_SHORT"


def test_resolution_flag_whatif_keeps_flags_and_penalises(cfg, episode_factory):
    data = bundle(episode_factory, cliff=5)
    mark(data, 2)
    assert not D.trace_episode(*data, cfg, None).candidates
    flag = D.trace_episode(*data, cfg, None, resolution_mode="flag")
    (promo,) = flag.candidates
    assert flag.dropped["resolution"] == 0 and flag.pairs[0].resolution_flagged
    assert promo["flags"]["contains_blocking_resolution"] is True
    plain = D.trace_episode(*data, cfg, None, resolution_mode="flag", resolution_penalty=0.0).candidates[0]
    assert promo["pre_score"] == pytest.approx(plain["pre_score"] - 0.5)
    clean = D.trace_episode(*bundle(episode_factory, cliff=5), cfg, None, resolution_mode="flag").candidates[0]
    assert "contains_blocking_resolution" not in clean["flags"]  # only promos that hold a mark carry the flag


def end_bundle(episode_factory):
    # 2 s lines; the clip is L001..L012 = 24 s, so the last 3 s are [21 s, 24 s]
    return bundle(episode_factory, n=30, step=2000, cliff=11)


def f5b(data, cfg, **options):
    return D.trace_episode(*data, cfg, None, resolution_mode="flag_unless_end", **options)


def test_f5b_drops_a_resolution_at_the_end_and_keeps_an_earlier_one(cfg, episode_factory):
    final = end_bundle(episode_factory)
    mark(final, 11)                                           # the clip's final line
    trace = f5b(final, cfg)
    assert not trace.candidates and trace.pairs[0].first_drop == "resolution"
    assert [p["final_line"] for p in trace.pairs[0].resolution_positions] == [True]
    earlier = end_bundle(episode_factory)
    mark(earlier, 9)                                          # L010 ends 4 s before the clip end
    trace = f5b(earlier, cfg)
    (promo,) = trace.candidates
    assert promo["flags"]["contains_blocking_resolution"] is True and trace.dropped["resolution"] == 0
    (position,) = trace.pairs[0].resolution_positions
    assert position["clip_seconds_after"] == 4.0 and position["at_end"] is False
    plain = f5b(earlier, cfg, resolution_penalty=0.0).candidates[0]
    assert promo["pre_score"] == pytest.approx(plain["pre_score"] - 0.5)


def test_f5b_window_rule_overlap_versus_start(cfg, episode_factory):
    data = end_bundle(episode_factory)
    mark(data, 10)  # L011 = 20-22 s: overlaps the last 3 s window [21, 24] but starts before it
    assert not f5b(data, cfg).candidates                                              # "overlap" (default): at the end
    assert f5b(data, cfg, resolution_window_rule="start").candidates                  # "start": earlier, kept
    assert not f5b(data, cfg, resolution_window_rule="start", resolution_window_ms=4000).candidates
    assert f5b(data, cfg, resolution_window_ms=0).candidates                          # only the final line counts
    final = end_bundle(episode_factory)
    mark(final, 11)
    assert not f5b(final, cfg, resolution_window_ms=0).candidates


def test_f5b_resolution_in_the_first_piece_of_a_montage_is_earlier(cfg, episode_factory):
    data = bundle(episode_factory, cliff=17)                  # 90 s raw span becomes a two-piece montage
    mark(data, 1, confidence="medium")                        # inside the first piece
    trace = f5b(data, cfg)
    (promo,) = trace.candidates
    assert promo["montage"] and promo["flags"]["contains_blocking_resolution"]
    (position,) = trace.pairs[0].resolution_positions
    assert position["segment"] == 1 and position["of"] == 2 and position["at_end"] is False
    assert position["clip_seconds_after"] == 10.0 and position["confidence"] == "medium"
    last = bundle(episode_factory, cliff=17)
    mark(last, 17)                                            # the montage's final line
    assert not f5b(last, cfg).candidates


def test_low_confidence_marks_never_count_as_blocking(cfg, episode_factory):
    data = end_bundle(episode_factory)
    mark(data, 11, confidence="low")
    trace = f5b(data, cfg)
    assert trace.candidates and not trace.pairs[0].resolution_positions
    assert "contains_blocking_resolution" not in trace.candidates[0]["flags"]


def test_f5b_relations_to_v1_and_f5_on_random_episodes(cfg):
    for seed in range(40):
        data = random_bundle(5, seed)
        v1, flag, unless = (D.trace_episode(*data, cfg, None, **o) for o in
                            ({}, {"resolution_mode": "flag"}, {"resolution_mode": "flag_unless_end"}))
        key = lambda p: (p.hook, p.cliff)
        flag_by, unless_by = {key(p): p for p in flag.pairs}, {key(p): p for p in unless.pairs}
        for pair in v1.pairs:
            f, u = flag_by[key(pair)], unless_by[key(pair)]
            ends = any(x["at_end"] for x in u.resolution_positions)
            assert ("resolution" in u.violations) == ends                        # dropped exactly when it sits at the end
            assert "resolution" not in f.violations                              # F5 never drops on resolution
            assert u.resolution_flagged == bool(u.resolution_positions and not ends)
            assert f.resolution_flagged == bool(f.resolution_positions)
            if pair.first_drop == "resolution" and not ends:
                assert u.first_drop != "resolution"                              # F5b keeps what F5b keeps
        assert unless.dropped["resolution"] <= v1.dropped["resolution"]


def test_resolution_end_summary_and_rescue_detail(cfg, episode_factory):
    data = end_bundle(episode_factory)
    mark(data, 9)                                             # earlier resolution -> removed by v1, kept by F5b
    add_cliff(data, 12)                                       # a second pair whose resolution line is not at its end? (still earlier)
    v1 = D.trace_episode(*data, cfg, None)
    golds = [GoldPromo("G1", "pos", 3, v1.pairs[0].raw)]
    summary = D.resolution_end_summary({5: v1}, golds)
    assert summary["resolution_removed_pairs"]["pairs"] == len(v1.pairs) == 2
    assert summary["resolution_removed_pairs"]["earlier_only"] == 2 and summary["resolution_removed_pairs"]["at_end"] == 0
    assert summary["gold_matching"]["earlier_only_gold"] == ["G1"] and summary["gold_matching"]["at_end_gold"] == []
    assert summary["nearest_resolution_to_clip_end"]["3-10s"] >= 1
    kept = f5b(data, cfg)
    detail = D.rescue_detail({5: kept}, golds, ["G1"])
    row = detail["G1"][0]
    assert row["resolution_flagged"] is True and row["episode_rank"] >= 1
    assert row["resolution_lines"][0]["at_end"] is False and row["resolution_lines"][0]["line_id"] == data[0].lines[9].id


def test_gold_resolution_positions(episode_factory):
    episode = end_bundle(episode_factory)[0]
    index = build_index([episode])
    conf = {5: {episode.lines[3].id: "high", episode.lines[10].id: "medium"}}
    # gold = L003..L012: 20 s; marks at L004 (14 s after its end) and L011
    g = GoldPromo("G1", "pos", 3, ((5, 4000, 24000),))
    other = GoldPromo("G2", "pos", 3, ((5, 24000, 30000),))   # no marks inside
    out = D.gold_resolution_positions([g, other], index, conf)
    assert [(x["line_id"], x["clip_seconds_after"], x["at_end"]) for x in out["G1"]] == [
        (episode.lines[3].id, 16.0, False), (episode.lines[10].id, 2.0, True)]
    assert out["G2"] == []


def test_unknown_variant_option_refused(cfg, episode_factory):
    with pytest.raises(ValueError):
        D.trace_episode(*bundle(episode_factory), cfg, None, j4_mode="maybe")
    with pytest.raises(ValueError):
        D.trace_episode(*bundle(episode_factory), cfg, None, too_short_mode="stretch")
    with pytest.raises(ValueError):
        D.trace_episode(*bundle(episode_factory), cfg, None, resolution_mode="ignore")


# ── coverage against gold ───────────────────────────────────────────────


def gold(gid, start, end, ep=5):
    return GoldPromo(gid, "pos", 3, ((ep, start, end),))


def test_matching_gold_threshold_and_not_one_to_one():
    golds = [gold("G1", 0, 20000), gold("G2", 10000, 30000)]
    assert D.matching_gold(((5, 0, 20000),), golds) == ["G1"]
    assert D.matching_gold(((5, 5000, 25000),), golds) == ["G1", "G2"]  # tIoU 0.6 with each
    assert D.matching_gold(((5, 0, 9000),), golds) == []
    assert D.matching_gold(((6, 0, 20000),), golds) == []              # other episode: no overlap


def test_rule_table_counts_first_drop_sole_blocker_and_rescuable(cfg, episode_factory):
    data = bundle(episode_factory, cliff=17)
    for line in data[0].lines[16:18]:
        line.speaker = "INVENTED OTHER"
    add_cliff(data, 3)  # a second, short pair on the same hook
    trace = D.trace_episode(*data, cfg, None)
    j4_pair = next(p for p in trace.pairs if p.first_drop == "J4")
    golds = [gold("G1", j4_pair.span[0][1], j4_pair.span[-1][2])]
    # the J4 pair spans two segments; use the union span as the gold so tIoU is 1
    golds = [GoldPromo("G1", "pos", 3, j4_pair.span)]
    table = D.rule_table({5: trace}, golds, D.pool_matched({5: trace.candidates}, golds))
    row = table["rules"]["J4"]
    assert row["first_drop_pairs"] == 1 and row["first_drop_gold"] == ["G1"]
    assert row["sole_blocker_pairs"] == 1 and row["rescuable_gold"] == ["G1"]
    assert table["per_gold"]["G1"]["matching_pairs"] >= 1 and table["per_gold"]["G1"]["kept_pairs"] == 0
    assert table["rules"]["checker:TOO_SHORT"]["rescuable_gold"] == []


def test_rule_table_gold_already_in_pool_is_not_rescuable(cfg, episode_factory):
    data = bundle(episode_factory, cliff=5)
    trace = D.trace_episode(*data, cfg, None)
    cand = trace.candidates[0]
    golds = [GoldPromo("G1", "pos", 3, D.promo_segs(cand))]
    table = D.rule_table({5: trace}, golds, D.pool_matched({5: trace.candidates}, golds))
    assert table["per_gold"]["G1"]["kept_pairs"] == 1
    assert all(v["rescuable_gold"] == [] for v in table["rules"].values())


def test_prefilter_recall_raw_and_constructed(cfg, episode_factory):
    data = bundle(episode_factory, cliff=2)  # raw 15 s pair, dropped TOO_SHORT
    trace = D.trace_episode(*data, cfg, None)
    golds = [GoldPromo("G1", "pos", 3, trace.pairs[0].raw), GoldPromo("G2", "pos", 3, ((5, 60000, 90000),))]
    result = D.prefilter_recall({5: trace}, golds)
    assert result["raw_pair"]["matched"] == ["G1"] and result["raw_pair"]["unmatched"] == ["G2"]
    assert result["constructed_pair"]["matched"] == ["G1"]  # no construction: falls back to the raw span


def test_variant_coverage_judged_slots(cfg, episode_factory):
    data = bundle(episode_factory, n=40, cliff=5)
    for index in (9, 14, 19, 24, 29, 34):
        add_cliff(data, index)
    trace = D.trace_episode(*data, cfg, None)
    cands = trace.candidates
    assert len(cands) >= 5
    last = cands[-1]
    golds = [GoldPromo("G1", "pos", 3, D.promo_segs(cands[0])), GoldPromo("G2", "pos", 3, D.promo_segs(last)),
             GoldPromo("G3", "pos", 3, ((5, 400000, 420000),))]
    cov = D.variant_coverage({5: cands}, golds)
    assert cov["pool_recall"]["matched"] == ["G1", "G2"] and cov["pool_recall"]["unmatched"] == ["G3"]
    assert cov["per_gold"]["G1"]["judged_top4"] is True and cov["per_gold"]["G1"]["best_episode_rank"] == 1
    rank = cov["per_gold"]["G2"]["best_episode_rank"]
    assert cov["per_gold"]["G2"]["judged_top4"] == (rank <= 4) and cov["per_gold"]["G2"]["judged_top6"] == (rank <= 6)
    assert cov["candidates"] == {"total": len(cands), "episodes": 1, "empty_episodes": []}
    assert D.variant_coverage({5: [], 6: cands}, golds)["candidates"]["empty_episodes"] == [5]


def test_variant_coverage_reports_negatives_reached(cfg, episode_factory):
    data = bundle(episode_factory, n=40, cliff=5)
    for index in (9, 14, 19):
        add_cliff(data, index)
    cands = D.trace_episode(*data, cfg, None).candidates
    top, last = cands[0], cands[-1]
    negs = [GoldPromo("N1", "neg", 0, D.promo_segs(top)), GoldPromo("N2", "neg", 0, D.promo_segs(last)),
            GoldPromo("N3", "neg", 0, ((5, 400000, 420000),))]
    cov = D.variant_coverage({5: cands}, [], negatives=negs)
    assert cov["n_negatives"] == 3 and cov["negative_pool_hits"] == ["N1", "N2"]
    assert "N1" in cov["negative_judged_top4_hits"] and "N3" not in cov["negative_pool_hits"]
    assert D.variant_coverage({5: cands}, [])["n_negatives"] == 0   # negatives are optional


def test_best_kept_rank_and_concentration():
    L = [PredPromo(i, f"P{i}", ((ep, 0, 20000),)) for i, ep in enumerate([28, 28, 29, 28, 29, 2, 3, 28, 29, 4, 11], 1)]
    golds = [gold("G1", 0, 20000, ep=2), gold("G2", 0, 20000, ep=11), gold("G3", 0, 20000, ep=99)]
    rows = D.best_kept_rank(L, golds, judged_ids={"P6"}, top_k=10)
    by = {r["gold_id"]: r for r in rows}
    assert by["G1"]["best_pos"] == 6 and by["G1"]["best_judged"] is True and by["G1"]["matched_within_K"] is True
    assert by["G2"]["first_match_pos"] == 11 and by["G2"]["matched_within_K"] is False
    assert by["G3"]["first_match_pos"] is None and by["G3"]["best_tiou"] == 0.0
    top = D.top_episode_concentration(L, 10)
    assert top["per_episode"] == {28: 4, 29: 3, 2: 1, 3: 1, 4: 1} and top["max_in_one_episode"] == 4
    assert top["top2_episodes_share"] == pytest.approx(0.7) and top["distinct_episodes"] == 5


def test_moment_coverage_uses_the_two_second_tolerance(episode_factory):
    episode = episode_factory(5, [(i * 5000, (i + 1) * 5000) for i in range(20)])
    index = build_index([episode])
    moments = {5: {"hook_starts": [{"line_id": "E05-L003"}], "cliff_ends": [{"line_id": "E05-L010"}]}}
    golds = [GoldPromo("G1", "pos", 3, ((5, 10000, 50000),)),          # exact boundaries
             GoldPromo("G2", "pos", 3, ((5, 12000, 52000),)),          # 2.0 s off: still found
             GoldPromo("G3", "pos", 3, ((5, 12001, 52001),)),          # 2.001 s off: not found
             GoldPromo("G4", "pos", 3, ((5, 10000, 80000),))]          # hook found, cliff not
    cov = D.moment_coverage(moments, index, golds)
    assert cov["both_found"] == ["G1", "G2"]
    assert cov["hook_found"] == ["G1", "G2", "G4"] and cov["cliff_found"] == ["G1", "G2"]


def test_max_pair_tiou_raw_and_constructed(cfg, episode_factory):
    trace = D.trace_episode(*bundle(episode_factory, cliff=17), cfg, None)   # raw 90 s, becomes a montage
    pair = trace.pairs[0]
    golds = [GoldPromo("G1", "pos", 3, pair.raw), GoldPromo("G2", "pos", 3, pair.span)]
    best = D.max_pair_tiou({5: trace}, golds)
    assert best["G1"]["raw"] == 1.0 and best["G2"]["constructed"] == 1.0 and best["G2"]["raw"] < 1.0


def test_diversity_cap_prototype_rules():
    eps = [1, 1, 1, 2, 2, 3, 4]
    items = [{"i": i, "ep": e} for i, e in enumerate(eps)]
    order = lambda top, cap=2, xs=items: [x["i"] for x in D.diversity_cap(xs, lambda x: x["ep"], top, cap)]
    assert order(4) == [0, 1, 3, 4, 2, 5, 6]               # third item of episode 1 is deferred past the top
    assert order(3) == [0, 1, 3, 2, 4, 5, 6]
    assert order(7, 7) == list(range(7))                    # a loose cap changes nothing
    assert order(4, xs=[{"i": i, "ep": 1} for i in range(5)]) == [0, 1, 2, 3, 4]   # too few eligible: fill by order
    assert order(0) == list(range(7))
    # items after the top keep their original relative order, and nothing is lost or duplicated
    assert sorted(order(5)) == list(range(7))


def test_f3_whatif_on_a_list(tmp_path):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "tools" / "p08b_diagnostic.py"
    spec = importlib.util.spec_from_file_location("p08b_diagnostic_f3", path)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    eps = [28, 28, 28, 29, 29, 29, 2, 3, 4, 5, 6, 7]
    L = [PredPromo(i, f"P{i}", ((ep, 0, 20000),)) for i, ep in enumerate(eps, 1)]
    golds = [gold("G1", 0, 20000, ep=7)]                       # matches only the promo at position 12
    out = tool.f3_whatif(L, golds, K=12)
    assert out["deferred_from_top"] == ["P3", "P6"] and out["promoted_into_top"] == ["P11", "P12"]
    assert out["promoted_from_positions"] == [11, 12]
    assert out["recall_at_K"] == {"before": 1, "after": 1}          # same top-K set: recall cannot change
    assert out["precision_at_10"] == {"before": 0, "after": 1, "n": 10}
    assert out["top_concentration_after"]["max_in_one_episode"] == 2


def test_reports_contain_ids_and_counts_only(cfg, episode_factory):
    data = bundle(episode_factory, cliff=17)
    for line in data[0].lines[16:18]:
        line.speaker = "INVENTED OTHER"
    trace = D.trace_episode(*data, cfg, None, j4_mode="flag")
    golds = [GoldPromo("G1", "pos", 3, trace.candidates[0] and D.promo_segs(trace.candidates[0]))]
    blob = json.dumps([D.variant_coverage({5: trace.candidates}, golds),
                       D.rule_table({5: trace}, golds, D.pool_matched({5: trace.candidates}, golds)),
                       D.prefilter_recall({5: trace}, golds), D.pair_construction_counts({5: trace}, golds)], default=str)
    assert "invented line" not in blob and "INVENTED" not in blob and "SPK" not in blob


# ── the sealed fresh set ────────────────────────────────────────────────


@pytest.mark.parametrize("ep", [31, 32, 33, 34])
def test_fresh_episodes_are_refused(ep):
    with pytest.raises(D.SealedEpisode):
        D.refuse_fresh([1, 2, ep])


def test_held_out_and_dev_episodes_are_allowed():
    from promo_finder.labelling import HELD_OUT
    D.refuse_fresh(HELD_OUT)
    D.refuse_fresh([5, 30, 36, 18])


def test_tool_never_opens_a_fresh_artifact(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "tools" / "p08b_diagnostic.py"
    spec = importlib.util.spec_from_file_location("p08b_diagnostic", path)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    opened = []
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: opened.append(str(self)) or "{}")
    for ep in (31, 32, 33, 34):
        with pytest.raises(D.SealedEpisode):
            tool.read_artifact(tmp_path, ep, "promos/candidates_E{ep:02d}.json")
    assert opened == []
    assert tool.read_artifact(tmp_path, 2, "moments/moments_E{ep:02d}.json") == {}
    assert opened and "E02" in opened[0]
    assert set(tool.HELD_OUT).isdisjoint({31, 32, 33, 34})
