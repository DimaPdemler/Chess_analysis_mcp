"""Game analysis tests. Uses a low depth for the engine-backed test to stay fast."""
from __future__ import annotations

import io

import chess.pgn

from server.core.game_analysis import analyze_game, resolve_player

# White hangs the queen on move 3 (Qxe5?? Nxe5): an unambiguous blunder at any depth.
BLUNDER_PGN = """[Event "test"]
[White "me"]
[Black "opp"]
[Result "*"]

1. e4 e5 2. Qh5 Nc6 3. Qxe5 Nxe5 *
"""

# A Lichess-style annotated PGN with [%eval], [%clk], NAGs and a variation.
ANNOTATED_PGN = """[Event "rated"]
[White "alice"]
[Black "bob"]
[Result "1-0"]

1. e4 { [%eval 0.2] [%clk 0:10:00] } 1... e5?! { (0.2 -> 0.5) Inaccuracy. } { [%clk 0:09:59] } (1... c5 2. Nf3) 2. Qh5 *
"""


def test_resolve_player():
    assert resolve_player({"White": "x"}, "white") == "white"
    assert resolve_player({"White": "x"}, "black") == "black"
    # auto matches configured username (default thedarktintin)
    assert resolve_player({"White": "thedarktintin", "Black": "z"}, "auto") == "white"
    assert resolve_player({"White": "z", "Black": "thedarktintin"}, "auto") == "black"
    # auto with no match falls back to white
    assert resolve_player({"White": "z", "Black": "y"}, "auto") == "white"


def test_annotated_pgn_walks_cleanly():
    """Comments/NAGs/variations are ignored; mainline is exactly the moves played."""
    game = chess.pgn.read_game(io.StringIO(ANNOTATED_PGN))
    assert game is not None
    sans = []
    board = game.board()
    for mv in game.mainline_moves():
        sans.append(board.san(mv))
        board.push(mv)
    assert sans == ["e4", "e5", "Qh5"]


def test_hanging_queen_flagged_blunder():
    session = analyze_game(BLUNDER_PGN, player="white", depth=8)
    # Move 3 Qxe5(+) should be a blunder (SAN includes the check marker).
    blunders = [m for m in session.mistakes if m.classification == "blunder"]
    assert any(m.move_san.startswith("Qxe5") and m.move_number == 3 for m in blunders)
    qxe5 = next(m for m in session.all_moves if m.move_san.startswith("Qxe5"))
    assert qxe5.win_swing > 15
    # Engine should recommend something other than hanging the queen.
    assert not qxe5.best_move_san.startswith("Qxe5")
    # Per-side accuracy is computed for both colours.
    assert 0 <= session.accuracy_white <= 100
    assert 0 <= session.accuracy_black <= 100
