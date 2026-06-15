"""PGN -> ordered mistake list -> ReviewSession.

We analyse every position along the mainline exactly once (results are cached in the
engine pool), then derive each move's before/after win% from consecutive positions:

    win_before(my move at P)  = best win% at P            (I am to move at P)
    win_after (my move at P)  = 100 - best win% at P+1    (opponent is to move at P+1)

Terminal positions (checkmate/stalemate/draw) are scored directly without the engine.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import chess
import chess.pgn

from server import config
from server.core import engine
from server.core.evaluation import (
    aggregate_accuracy,
    classify,
    move_accuracy,
    win_percent_from_score,
)
from server.core.session import MoveReview, ReviewSession


@dataclass
class _PosEval:
    """Evaluation of a single position, from the side-to-move's perspective."""

    win_stm: float  # win% for the side to move
    cp_stm: float  # signed centipawns for the side to move (mate -> +/-MATE_SCORE_CP)
    best_pv_uci: list[str]  # principal variation (empty if terminal)
    is_terminal: bool


def _signed_cp(cp: int | None, mate: int | None) -> float:
    if mate is not None:
        return float(config.MATE_SCORE_CP) if mate > 0 else float(-config.MATE_SCORE_CP)
    return float(cp if cp is not None else 0)


def _evaluate_position(board: chess.Board, *, depth: int) -> _PosEval:
    """Evaluate `board` from the side-to-move's perspective, handling terminal cases."""
    outcome = board.outcome(claim_draw=True)
    if outcome is not None:
        if outcome.winner is None:  # draw of any kind
            return _PosEval(win_stm=50.0, cp_stm=0.0, best_pv_uci=[], is_terminal=True)
        # There is a winner; the side to move is the one who is checkmated -> losing.
        side_to_move_won = outcome.winner == board.turn
        win = 100.0 if side_to_move_won else 0.0
        cp = float(config.MATE_SCORE_CP) if side_to_move_won else float(-config.MATE_SCORE_CP)
        return _PosEval(win_stm=win, cp_stm=cp, best_pv_uci=[], is_terminal=True)

    res = engine.analyse(board.fen(), depth=depth, multipv=1)
    best = res.best
    return _PosEval(
        win_stm=win_percent_from_score(best.cp, best.mate),
        cp_stm=_signed_cp(best.cp, best.mate),
        best_pv_uci=list(best.pv_uci),
        is_terminal=False,
    )


def _pv_to_san(board: chess.Board, pv_uci: list[str], *, max_plies: int = 12) -> list[str]:
    """Convert a UCI principal variation to SAN by replaying on a copy of `board`."""
    b = board.copy(stack=False)
    sans: list[str] = []
    for uci in pv_uci[:max_plies]:
        try:
            move = chess.Move.from_uci(uci)
            sans.append(b.san(move))
            b.push(move)
        except (ValueError, AssertionError):
            break
    return sans


def resolve_player(headers: dict[str, str], player: str) -> str:
    """Resolve player='white'|'black'|'auto' to a concrete color."""
    p = (player or "auto").lower()
    if p in ("white", "black"):
        return p
    # auto: match the configured username against the PGN headers.
    name = config.USERNAME.lower().strip()
    if name:
        if headers.get("White", "").lower().strip() == name:
            return "white"
        if headers.get("Black", "").lower().strip() == name:
            return "black"
    return "white"


def analyze_game(pgn: str, player: str = "auto", *, depth: int | None = None) -> ReviewSession:
    """Analyse a PGN and build a ReviewSession for `player`'s mistakes."""
    depth = depth or config.SWEEP_DEPTH
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        raise ValueError("Could not parse a game from the provided PGN.")

    headers = dict(game.headers)
    me = resolve_player(headers, player)
    my_turn = chess.WHITE if me == "white" else chess.BLACK

    # Replay the mainline, collecting (board_before, move) pairs. We ignore any embedded
    # comments / NAGs / variations by only walking mainline_moves().
    board = game.board()
    steps: list[tuple[chess.Board, chess.Move]] = []
    for move in game.mainline_moves():
        steps.append((board.copy(stack=False), move))
        board.push(move)
    final_board = board

    # Evaluate every position once: the position before each move, plus the final one.
    pos_evals: list[_PosEval] = []
    for before, _move in steps:
        pos_evals.append(_evaluate_position(before, depth=depth))
    pos_evals.append(_evaluate_position(final_board, depth=depth))

    all_my_moves: list[MoveReview] = []
    white_accs: list[float] = []
    black_accs: list[float] = []

    for i, (before, move) in enumerate(steps):
        mover_is_white = before.turn == chess.WHITE
        eval_at = pos_evals[i]
        eval_next = pos_evals[i + 1]

        # From the mover's perspective.
        win_before = eval_at.win_stm
        win_after = 100.0 - eval_next.win_stm
        cp_before = eval_at.cp_stm
        cp_after = -eval_next.cp_stm
        acc = move_accuracy(win_before, win_after)

        if mover_is_white:
            white_accs.append(acc)
        else:
            black_accs.append(acc)

        if before.turn != my_turn:
            continue  # only build full reviews for my moves

        best_uci = eval_at.best_pv_uci[0] if eval_at.best_pv_uci else move.uci()
        is_best = move.uci() == best_uci
        classification = classify(win_before, win_after, is_best=is_best)

        best_line_san = _pv_to_san(before, eval_at.best_pv_uci)
        best_move_san = best_line_san[0] if best_line_san else before.san(move)

        review = MoveReview(
            ply=i + 1,
            move_number=before.fullmove_number,
            color="white" if mover_is_white else "black",
            move_san=before.san(move),
            move_uci=move.uci(),
            fen_before=before.fen(),
            fen_after=_fen_after(before, move),
            eval_before=round(cp_before, 1),
            eval_after=round(cp_after, 1),
            win_before=round(win_before, 1),
            win_after=round(win_after, 1),
            win_swing=round(win_before - win_after, 1),
            classification=classification,
            best_move_san=best_move_san,
            best_line_uci=eval_at.best_pv_uci[:12],
            best_line_san=best_line_san,
            accuracy=round(acc, 1),
        )
        all_my_moves.append(review)

    mistakes = [
        m for m in all_my_moves if m.classification in ("inaccuracy", "mistake", "blunder")
    ]

    session = ReviewSession(
        pgn=pgn,
        player=me,
        headers=headers,
        result=headers.get("Result", "*"),
        accuracy_white=round(aggregate_accuracy(white_accs), 1),
        accuracy_black=round(aggregate_accuracy(black_accs), 1),
        all_moves=all_my_moves,
        mistakes=mistakes,
        current_index=0,
    )
    return session


def _fen_after(before: chess.Board, move: chess.Move) -> str:
    b = before.copy(stack=False)
    b.push(move)
    return b.fen()
