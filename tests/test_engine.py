"""Engine tests. Require the Stockfish binary; set STOCKFISH_PATH if not on PATH."""
from __future__ import annotations

import chess

from server.core import engine


def test_start_position_reasonable():
    res = engine.analyse(chess.STARTING_FEN, depth=14)
    assert res.lines
    # Start position is near-equal and slightly favours white.
    assert -100 <= (res.best.cp or 0) <= 200


def test_determinism_and_cache():
    fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    a = engine.analyse(fen, depth=14)
    b = engine.analyse(fen, depth=14)
    assert a.best.cp == b.best.cp
    assert a.best.pv_uci == b.best.pv_uci


def test_mate_in_one_detected():
    # Black king on h8, white queen+rook deliver: simple back-rank style mate in 1.
    # Position: white Qh5, mate with Qxh7#? Use a clean known mate-in-1.
    # White to move: Rd8 is mate (back rank). FEN: 6k1/5ppp/8/8/8/8/8/3R2K1 w - - 0 1
    fen = "6k1/5ppp/8/8/8/8/8/3R2K1 w - - 0 1"
    res = engine.analyse(fen, depth=12, multipv=1)
    best = res.best
    # Rd8 is mate in 1.
    assert best.pv_uci and best.pv_uci[0] == "d1d8"
    assert best.mate == 1


def test_clear_winning_capture():
    # White to move can win a hanging queen: black queen on d4 undefended, Nxd4? use
    # a simple free-rook position. White rook takes undefended black rook.
    # 4k3/8/8/8/3r4/8/3R4/4K3 w - - 0 1 : Rxd4 wins a rook.
    fen = "4k3/8/8/8/3r4/8/3R4/4K3 w - - 0 1"
    res = engine.analyse(fen, depth=14)
    assert res.best.pv_uci[0] == "d2d4"
