"""Game analysis tests. Uses a low depth for the engine-backed test to stay fast."""
from __future__ import annotations

import io

import chess.pgn

from server.core.game_analysis import (
    _detect_platform,
    _resolve_review_elo,
    analyze_game,
    resolve_player,
)

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


def test_resolve_player_matches_aliases(monkeypatch):
    from server import config

    # CHESS_ALIASES handles are recognised by player="auto" too (bare = any platform).
    monkeypatch.setattr(config, "USERNAME_ALIASES", [(None, "my_chesscom"), ("lichess", "myalt")])
    assert resolve_player({"White": "z", "Black": "my_chesscom"}, "auto") == "black"
    assert resolve_player({"White": "MyAlt", "Black": "z"}, "auto") == "white"  # case-insensitive


def test_platform_detection_and_elo_normalization():
    assert _detect_platform({"Site": "https://lichess.org/abcd"}) == "lichess"
    assert _detect_platform({"Site": "Chess.com", "Link": "https://chess.com/game/1"}) == "chesscom"
    assert _detect_platform({"Site": "Local"}) is None

    # Lichess Elo is pulled down to the common scale (offset -200); chess.com unchanged.
    li_headers = {"Site": "https://lichess.org/x", "WhiteElo": "2400"}
    elo, src = _resolve_review_elo(li_headers, "white", None, None)
    assert elo == 2200.0 and src == "lichess"
    cc_headers = {"Site": "Chess.com", "BlackElo": "1800"}
    elo, src = _resolve_review_elo(cc_headers, "black", None, None)
    assert elo == 1800.0 and src == "chesscom"
    # Explicit elo and named sensitivity win over the PGN; no headers -> default (None).
    assert _resolve_review_elo(li_headers, "white", 1600, None) == (1600.0, "explicit")
    assert _resolve_review_elo({}, "white", None, "master")[0] == 2400.0
    assert _resolve_review_elo({}, "white", None, None) == (None, None)


def test_review_elo_tightens_thresholds():
    """A master-level review uses smaller cutoffs (and stores the Elo) vs. the default."""
    strong = analyze_game(BLUNDER_PGN, player="white", depth=8, elo=2400)
    default = analyze_game(BLUNDER_PGN, player="white", depth=8)
    assert strong.review_elo == 2400.0 and strong.elo_source == "explicit"
    assert strong.thresholds[0] < default.thresholds[0]  # inaccuracy cutoff is tighter
    assert default.review_elo is None and default.thresholds == [5.0, 10.0, 15.0]


# Same blunder, but with lichess-style [%clk] comments: White is in time trouble (8s) on Qxe5.
CLOCK_PGN = """[Event "test"]
[White "me"]
[Black "opp"]
[Result "*"]
[TimeControl "600+0"]

1. e4 { [%clk 0:00:30] } 1... e5 { [%clk 0:09:55] } 2. Qh5 { [%clk 0:00:20] } 2... Nc6 { [%clk 0:09:50] } 3. Qxe5 { [%clk 0:00:08] } 3... Nxe5 { [%clk 0:09:45] } *
"""


def test_clock_parsing_and_time_trouble():
    """[%clk] comments are parsed onto MoveReview and drive the time_trouble motif."""
    from server.core import history

    sess = analyze_game(CLOCK_PGN, player="white", depth=8)
    blunder = next(m for m in sess.mistakes if m.move_san.startswith("Qxe5"))  # "Qxe5+" (check)
    assert blunder.clock_after == 8.0  # 0:00:08 remaining after the blunder
    assert blunder.opp_clock == 590.0  # opponent's clock at their previous move

    rec = history.build_game_record(sess)
    mm = next(x for x in rec["mistakes"] if x["san"].startswith("Qxe5"))
    assert "time_trouble" in mm["motifs"]


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
