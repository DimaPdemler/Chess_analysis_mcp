"""Unit tests for the pure evaluation math (no engine needed)."""
from __future__ import annotations

import pytest

from server.core import evaluation as ev


def test_win_percent_zero_is_fifty():
    assert ev.win_percent(0) == pytest.approx(50.0)


def test_win_percent_monotonic_in_cp():
    cps = [-1000, -500, -200, -50, 0, 50, 200, 500, 1000]
    wins = [ev.win_percent(c) for c in cps]
    assert wins == sorted(wins)
    assert all(0.0 <= w <= 100.0 for w in wins)


def test_win_percent_symmetry():
    for cp in (50, 137, 400, 999):
        assert ev.win_percent(cp) + ev.win_percent(-cp) == pytest.approx(100.0)


def test_win_percent_clamps():
    # Beyond the clamp the value should not change.
    assert ev.win_percent(5000) == pytest.approx(ev.win_percent(1000))
    assert ev.win_percent(-5000) == pytest.approx(ev.win_percent(-1000))


def test_win_percent_from_score_mate():
    assert ev.win_percent_from_score(None, 3) == pytest.approx(100.0)
    assert ev.win_percent_from_score(None, -2) == pytest.approx(0.0)
    assert ev.win_percent_from_score(150, None) == pytest.approx(ev.win_percent(150))


def test_classification_thresholds():
    # drop just below / at each boundary (Lichess 5/10/15 win%-point thresholds)
    assert ev.classify(50, 50) == "best"          # no drop
    assert ev.classify(60, 56) == "good"          # drop 4 (>BEST_EPS, <5)
    assert ev.classify(60, 55) == "inaccuracy"    # drop 5
    assert ev.classify(60, 50) == "mistake"       # drop 10
    assert ev.classify(60, 45) == "blunder"       # drop 15
    assert ev.classify(90, 30) == "blunder"       # drop 60


def test_classification_is_best_flag():
    # Tiny drop but flagged as engine's top move -> best.
    assert ev.classify(50, 49, is_best=True) == "best"


def test_move_accuracy_range_and_direction():
    perfect = ev.move_accuracy(50, 50)
    bad = ev.move_accuracy(60, 20)
    assert 0.0 <= bad < perfect <= 100.0
    assert perfect == pytest.approx(100.0, abs=0.5)


def test_aggregate_accuracy():
    assert ev.aggregate_accuracy([]) == 100.0
    assert ev.aggregate_accuracy([90.0, 80.0]) == pytest.approx(85.0)
