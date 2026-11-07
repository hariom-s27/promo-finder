"""set_tiou tests (eval/match_rule.md section 2). All numbers invented or from DR09."""

from __future__ import annotations

import pytest

from promo_finder.tiou import set_tiou

S = 1000


def test_identical_is_one():
    p = [(1, 10 * S, 40 * S), (2, 0, 5 * S)]
    assert set_tiou(p, list(p)) == 1.0


def test_disjoint_is_zero():
    assert set_tiou([(1, 0, 10 * S)], [(1, 20 * S, 30 * S)]) == 0.0


def test_touching_is_zero():
    assert set_tiou([(1, 0, 10 * S)], [(1, 10 * S, 30 * S)]) == 0.0


def test_dr09_single_segment():
    assert set_tiou([(1, 100 * S, 140 * S)], [(1, 104 * S, 150 * S)]) == pytest.approx(0.72)


def test_dr09_multi_segment():
    gold = [(1, 30 * S, 45 * S), (1, 512 * S, 530 * S)]
    pred = [(1, 32 * S, 47 * S), (1, 515 * S, 534 * S)]
    assert set_tiou(gold, pred) == pytest.approx(0.72, abs=0.005)


def test_different_episodes_never_overlap():
    assert set_tiou([(1, 0, 30 * S)], [(2, 0, 30 * S)]) == 0.0
    # same times, half in a matching episode
    assert set_tiou([(1, 0, 10 * S), (2, 0, 10 * S)], [(1, 0, 10 * S), (3, 0, 10 * S)]) == pytest.approx(1 / 3)


def test_overlapping_segments_merged_before_measuring():
    a = [(1, 0, 20 * S), (1, 10 * S, 30 * S)]  # union 0-30
    assert set_tiou(a, [(1, 0, 30 * S)]) == 1.0


def test_empty_is_zero():
    assert set_tiou([], []) == 0.0
    assert set_tiou([(1, 5, 5)], [(1, 5, 5)]) == 0.0


def test_symmetric():
    a = [(1, 0, 25 * S), (2, 3 * S, 9 * S)]
    b = [(1, 5 * S, 40 * S), (2, 0, 4 * S)]
    assert set_tiou(a, b) == set_tiou(b, a)
