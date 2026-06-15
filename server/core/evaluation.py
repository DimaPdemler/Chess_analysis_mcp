"""Evaluation math: centipawns -> win%, move classification, per-move accuracy.

Formulas follow Lichess's published approach (spec §6). Everything here is pure and
deterministic so it is trivially testable and reproducible.
"""
from __future__ import annotations

import math
from typing import Literal

Classification = Literal["best", "good", "inaccuracy", "mistake", "blunder"]

# Lichess sigmoid constant for cp -> win%.
_WIN_K = 0.00368208

# Clamp cp magnitude before the sigmoid; beyond this the win% is already ~saturated.
_CP_CLAMP = 1000

# Classification thresholds on the win% drop (win_before - win_after), in win% points
# (0-100 scale). These mirror Lichess, which thresholds its winningChances scale [-1,1]
# at 0.1/0.2/0.3; multiplied by 50 that is 5/10/15 win% points. Verified to reproduce
# Lichess's own labels on example_pgns/game1.pgn.
BLUNDER_DROP = 15.0
MISTAKE_DROP = 10.0
INACCURACY_DROP = 5.0

# A move within this win% of the engine's best is considered "best".
BEST_EPS = 2.0


def win_percent(cp: int | float) -> float:
    """Convert a centipawn score (side-to-move relative) to a win% in [0, 100].

    cp == 0 -> 50. Positive favours the side to move. Mate scores should be passed
    in as large +/- centipawn values (see win_percent_from_score)."""
    c = max(-_CP_CLAMP, min(_CP_CLAMP, cp))
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-_WIN_K * c)) - 1.0)


def win_percent_from_score(cp: int | None, mate: int | None) -> float:
    """Win% from either a centipawn value or a mate-in-N.

    Exactly one of cp / mate is expected to be meaningful (python-chess gives mate
    when a forced mate is found). Mate for the side to move -> ~100, mate against -> ~0.
    """
    if mate is not None:
        return 100.0 if mate > 0 else 0.0
    if cp is None:
        return 50.0
    return win_percent(cp)


def classify(win_before: float, win_after: float, *, is_best: bool = False) -> Classification:
    """Classify a move by the drop in the mover's win% (win_before - win_after).

    win_before = best win% available before the move (from the mover's perspective).
    win_after  = win% after the move actually played (from the mover's perspective).
    Set is_best=True when the move played equals the engine's top choice.
    """
    drop = win_before - win_after
    if drop >= BLUNDER_DROP:
        return "blunder"
    if drop >= MISTAKE_DROP:
        return "mistake"
    if drop >= INACCURACY_DROP:
        return "inaccuracy"
    if is_best or drop <= BEST_EPS:
        return "best"
    return "good"


def move_accuracy(win_before: float, win_after: float) -> float:
    """Per-move accuracy% in [0, 100] from the win% drop (Lichess-style)."""
    drop = max(0.0, win_before - win_after)
    acc = 103.1668 * math.exp(-0.04354 * drop) - 3.1669
    return max(0.0, min(100.0, acc))


def aggregate_accuracy(accuracies: list[float]) -> float:
    """Aggregate per-move accuracies into a single per-side accuracy%.

    Simple arithmetic mean to start (the plan notes this can be upgraded to
    Lichess's volatility-weighted mean later). Empty -> 100 (no moves to fault).
    """
    if not accuracies:
        return 100.0
    return sum(accuracies) / len(accuracies)
