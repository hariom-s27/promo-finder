from __future__ import annotations

import pytest

from promo_finder.checker import build_index, check_promo, snap_to_lines
from promo_finder.config import PromoCfg
from promo_finder.parser import parse_dir

CFG = PromoCfg(min_s=20, max_s=60, max_segments=3)


@pytest.fixture
def index(episode_factory):
    e1 = episode_factory(1, [
        (0, 10000), (10000, 20000), (20000, 30000), (30000, 40000),
        (40000, 50000), (50000, 60000), (60000, 60001), (60001, 70000),
    ])
    e2 = episode_factory(2, [(0, 19999), (19999, 40000), (40000, 50000)])
    return build_index([e1, e2])


def all_line_times(index):
    return {x.start_ms for x in index.values()}, {x.end_ms for x in index.values()}


def assert_times_from_lines(res, index):
    starts, ends = all_line_times(index)
    for s in res.segments:
        assert s.start_ms in starts and s.end_ms in ends
        assert s.start_ms == index[s.line_ids[0]].start_ms
        assert s.end_ms == index[s.line_ids[-1]].end_ms


def test_exactly_20s_passes(index):
    r = check_promo([("E01-L001", "E01-L002")], index, CFG)
    assert r.ok and r.total_ms == 20000 and r.errors == []
    assert r.segments[0].line_ids == ["E01-L001", "E01-L002"]
    assert_times_from_lines(r, index)


def test_exactly_60s_passes(index):
    r = check_promo([("E01-L001", "E01-L006")], index, CFG)
    assert r.ok and r.total_ms == 60000


def test_19999_fails(index):
    r = check_promo([("E02-L001", "E02-L001")], index, CFG)
    assert not r.ok and r.total_ms == 19999 and r.errors == ["TOO_SHORT"]


def test_60001_fails(index):
    r = check_promo([("E01-L001", "E01-L007")], index, CFG)
    assert not r.ok and r.total_ms == 60001 and r.errors == ["TOO_LONG"]


def test_two_segments_across_two_episodes(index):
    r = check_promo([("E01-L001", "E01-L002"), ("E02-L003", "E02-L003")], index, CFG)
    assert r.ok, r.errors
    assert r.total_ms == 30000
    assert [s.ep for s in r.segments] == [1, 2]
    assert_times_from_lines(r, index)


def test_unknown_id(index):
    r = check_promo([("E01-L999", "E01-L002")], index, CFG)
    assert r.errors == ["UNKNOWN_ID"] and not r.ok


def test_cross_episode_span(index):
    r = check_promo([("E01-L001", "E02-L002")], index, CFG)
    assert r.errors == ["CROSS_EP_SPAN"]


def test_reversed_span(index):
    r = check_promo([("E01-L003", "E01-L001")], index, CFG)
    assert r.errors == ["REVERSED_SPAN"]


def test_too_many_segments(index):
    spans = [("E01-L001", "E01-L001"), ("E01-L003", "E01-L003"), ("E01-L005", "E01-L005"), ("E01-L008", "E01-L008")]
    r = check_promo(spans, index, CFG)
    assert r.errors == ["TOO_MANY_SEGMENTS"]


def test_out_of_order_across_episodes(index):
    r = check_promo([("E02-L003", "E02-L003"), ("E01-L001", "E01-L002")], index, CFG)
    assert r.errors == ["OUT_OF_ORDER"]


def test_out_of_order_within_episode(index):
    r = check_promo([("E01-L003", "E01-L003"), ("E01-L001", "E01-L002")], index, CFG)
    assert r.errors == ["OUT_OF_ORDER"]


def test_overlap(index):
    r = check_promo([("E01-L001", "E01-L002"), ("E01-L002", "E01-L003")], index, CFG)
    assert r.errors == ["OVERLAP"]


def test_bad_segment_time(episode_factory):
    idx = build_index([episode_factory(4, [(30000, 40000), (0, 25000)])])
    r = check_promo([("E04-L001", "E04-L002")], idx, CFG)  # last line ends before first starts
    assert r.errors == ["BAD_SEGMENT_TIME"]


def test_accepts_full_config_object(index):
    class Holder:
        promo = CFG

    assert check_promo([("E01-L001", "E01-L002")], index, Holder()).ok


def test_checker_never_invents_timestamps(index):
    # Any spans, valid or not, can only produce times that exist on parsed lines.
    ids = sorted(index)
    for a in ids:
        for b in ids:
            r = check_promo([(a, b)], index, CFG)
            assert_times_from_lines(r, index)


def test_snap_to_lines(index):
    span, ds, de = snap_to_lines(1, 12500, 38000, index)
    assert span == ("E01-L002", "E01-L004")
    assert (ds, de) == (-2500, 2000)
    # exact boundaries do not move
    assert snap_to_lines(1, 10000, 40000, index) == (("E01-L002", "E01-L004"), 0, 0)
    # end past the last line clamps to the last line
    span, ds, de = snap_to_lines(2, 100, 99999, index)
    assert span == ("E02-L001", "E02-L003") and (ds, de) == (-100, 50000 - 99999)
    # snapped spans always pass through the checker's own time rule
    r = check_promo([snap_to_lines(1, 12500, 38000, index)[0]], index, CFG)
    assert r.ok and r.total_ms == 30000


def test_with_parsed_fixtures(fixtures_dir):
    eps, _ = parse_dir(fixtures_dir / "normal")
    idx = build_index(eps)
    r = check_promo([("E01-L004", "E01-L007"), ("E02-L002", "E02-L003")], idx, CFG)
    assert r.ok, r.errors
    assert r.total_ms == (30000 - 8500) + (18000 - 5000)
