"""05_race_model.race against answers solved by hand."""
from __future__ import annotations

import pytest


def test_coin_flip_twos(model):
    # Each possession scores 2 with probability 1/2, else nothing; both need 2.
    # x = 1/2 + (1/2)(1/2)x  =>  x = 2/3 with the ball, 1/3 without.
    p = [0.5, 0.0, 0.5, 0.0, 0.0]
    assert model.race(2, 2, True, p, p, {}) == pytest.approx(2 / 3, abs=1e-12)
    assert model.race(2, 2, False, p, p, {}) == pytest.approx(1 / 3, abs=1e-12)


def test_certain_scoring_means_the_ball_wins(model):
    p = [0.0, 0.0, 1.0, 0.0, 0.0]
    assert model.race(2, 2, True, p, p, {}) == 1.0
    assert model.race(2, 2, False, p, p, {}) == 0.0
    # Home needs 4 (two possessions), away needs 2: away wins on its first trip.
    assert model.race(4, 2, True, p, p, {}) == 0.0


def test_one_point_needs_two_states(model):
    # Needs (2, 1), threes only with probability q, ball to home:
    # home scores (q) and wins; else away scores (q) and wins; else repeat.
    q = 0.4
    p = [1 - q, 0.0, 0.0, q, 0.0]
    x = q / (1 - (1 - q) ** 2)
    assert model.race(2, 1, True, p, p, {}) == pytest.approx(x, abs=1e-12)


def test_symmetry_and_monotonicity(model):
    p = [0.49, 0.03, 0.32, 0.15, 0.01]
    memo = {}
    for nh in range(1, 12):
        for na in range(1, 12):
            # Equal needs, ball to home: home is favored; swapping roles is 1 - x.
            assert model.race(nh, na, True, p, p, memo) == pytest.approx(
                1 - model.race(na, nh, False, p, p, memo), abs=1e-12)
            if nh > 1:
                assert model.race(nh - 1, na, True, p, p, memo) >= model.race(nh, na, True, p, p, memo)
