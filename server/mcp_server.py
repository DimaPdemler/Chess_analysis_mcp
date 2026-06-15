"""MCP server exposing the chess-review brains to Claude Code.

Tools:
  - analyze_game(pgn, player)      -> game summary + populates the shared ReviewSession
  - get_engine_line(fen, move, ..) -> grounded engine line / refutation for follow-ups
  - goto_mistake(index)            -> anchor terminal narration to a specific mistake

Run as the MCP stdio server:
    /opt/miniconda3/envs/chess-review/bin/python -m server.mcp_server
"""
from __future__ import annotations

from typing import Optional

import chess
from mcp.server.fastmcp import FastMCP

from server import config
from server.core import engine
from server.core.evaluation import classify, win_percent_from_score
from server.core.game_analysis import _signed_cp, analyze_game as _analyze_game
from server.core import session as session_mod

mcp = FastMCP("chess")


def _eval_str(cp: int | None, mate: int | None) -> str:
    """Human-readable eval from the side-to-move perspective."""
    if mate is not None:
        return f"#{mate}" if mate > 0 else f"#-{abs(mate)}"
    pawns = (cp or 0) / 100.0
    return f"{pawns:+.2f}"


def _eval_str_from_signed_cp(cp: int) -> str:
    """Like _eval_str but takes a signed cp that may be a mate-equivalent magnitude."""
    if abs(cp) >= config.MATE_SCORE_CP:
        return "#" if cp > 0 else "#-"
    return f"{cp / 100.0:+.2f}"


def _pv_to_san(board: chess.Board, pv_uci: list[str], max_plies: int = 12) -> list[str]:
    b = board.copy(stack=False)
    out: list[str] = []
    for uci in pv_uci[:max_plies]:
        try:
            mv = chess.Move.from_uci(uci)
            out.append(b.san(mv))
            b.push(mv)
        except (ValueError, AssertionError):
            break
    return out


def _parse_move(board: chess.Board, move: str) -> chess.Move:
    """Accept either UCI (e2e4) or SAN (e4, Nf3) for the move argument."""
    try:
        mv = chess.Move.from_uci(move)
        if mv in board.legal_moves:
            return mv
    except ValueError:
        pass
    return board.parse_san(move)  # raises ValueError if illegal/ambiguous


@mcp.tool()
def analyze_game(pgn: str, player: str = "auto") -> dict:
    """Analyse a full game from PGN and find the player's mistakes.

    Args:
        pgn: The game in PGN format (Lichess/Chess.com exports work; comments and
            variations are ignored).
        player: Which side to review: "white", "black", or "auto" (infer from headers).

    Returns a summary with per-side accuracy and an ordered list of the player's
    inaccuracies/mistakes/blunders. Each mistake has an `index` usable with
    `goto_mistake`, and a `fen_before` usable with `get_engine_line` for follow-ups.
    The full result is stored in a shared session that the (future) web board reads.
    """
    sess = _analyze_game(pgn, player=player)
    session_mod.set_session(sess)

    mistakes = [
        {
            "index": i,
            "ply": m.ply,
            "move_number": m.move_number,
            "color": m.color,
            "move_san": m.move_san,
            "classification": m.classification,
            "win_swing": m.win_swing,
            "eval_before": round(m.eval_before / 100.0, 2),
            "eval_after": round(m.eval_after / 100.0, 2),
            "best_move_san": m.best_move_san,
            "fen_before": m.fen_before,
        }
        for i, m in enumerate(sess.mistakes)
    ]

    return {
        "result": sess.result,
        "player": sess.player,
        "white": sess.headers.get("White", "?"),
        "black": sess.headers.get("Black", "?"),
        "opening": sess.headers.get("Opening", sess.headers.get("ECO", "")),
        "accuracy_white": sess.accuracy_white,
        "accuracy_black": sess.accuracy_black,
        "num_my_moves": len(sess.all_moves),
        "num_mistakes": len(sess.mistakes),
        "mistakes": mistakes,
        "board_url": None,
        "note": "Interactive web board arrives in Phase 4. For now, ask 'why was move N bad?' "
        "and I'll use get_engine_line to explain.",
    }


@mcp.tool()
def get_engine_line(
    fen: str,
    move: Optional[str] = None,
    depth: int = config.DEFAULT_DEPTH,
    multipv: int = 1,
) -> dict:
    """Evaluate a position (optionally after a candidate move) and return engine lines.

    This is the grounding for "why?" follow-ups. Without `move`, it returns the best
    move and principal variation for `fen`. With `move` (UCI like "g1f3" or SAN like
    "Nf3"), it also returns how that move is classified and the engine's refutation /
    expected continuation after it — i.e. concretely *why* it is good or bad.

    Args:
        fen: Position in FEN.
        move: Optional candidate move to evaluate (UCI or SAN).
        depth: Search depth (fixed for reproducibility). Defaults to 18.
        multipv: Number of alternative lines to return for `fen`.
    """
    board = chess.Board(fen)
    base = engine.analyse(fen, depth=depth, multipv=max(1, multipv))
    best = base.best
    best_line_san = _pv_to_san(board, best.pv_uci)

    result: dict = {
        "fen": fen,
        "side_to_move": "white" if board.turn == chess.WHITE else "black",
        "depth": depth,
        "eval": _eval_str(best.cp, best.mate),
        "eval_cp": round(_signed_cp(best.cp, best.mate)),
        "win_percent": round(best.win_percent, 1),
        "best_san": best_line_san[0] if best_line_san else None,
        "line_san": best_line_san,
        "line_uci": best.pv_uci[:12],
        "shapes": [],  # board annotations: deferred to Phase 7
    }

    if multipv > 1:
        result["lines"] = [
            {
                "eval": _eval_str(ln.cp, ln.mate),
                "win_percent": round(ln.win_percent, 1),
                "line_san": _pv_to_san(board, ln.pv_uci),
                "line_uci": ln.pv_uci[:12],
            }
            for ln in base.lines
        ]

    if move:
        try:
            mv = _parse_move(board, move)
        except ValueError as exc:
            result["error"] = f"Illegal or unparseable move '{move}': {exc}"
            return result

        move_san = board.san(mv)
        win_before = best.win_percent  # best available for the mover
        after_board = board.copy(stack=False)
        after_board.push(mv)

        if after_board.is_game_over(claim_draw=True):
            outcome = after_board.outcome(claim_draw=True)
            if outcome and outcome.winner is None:
                win_after = 50.0
            elif outcome and outcome.winner == board.turn:
                win_after = 100.0  # the mover delivered mate
            else:
                win_after = 0.0
            refutation_san: list[str] = []
            refutation_uci: list[str] = []
            after_eval_cp = 0 if (outcome and outcome.winner is None) else (
                config.MATE_SCORE_CP if (outcome and outcome.winner == board.turn) else -config.MATE_SCORE_CP
            )
        else:
            after = engine.analyse(after_board.fen(), depth=depth, multipv=1).best
            win_after = 100.0 - after.win_percent  # back to the mover's perspective
            refutation_uci = after.pv_uci[:12]
            refutation_san = _pv_to_san(after_board, after.pv_uci)
            after_eval_cp = -round(_signed_cp(after.cp, after.mate))

        is_best = best.pv_uci and mv.uci() == best.pv_uci[0]
        result["move"] = {
            "move_san": move_san,
            "move_uci": mv.uci(),
            "classification": classify(win_before, win_after, is_best=bool(is_best)),
            "win_before": round(win_before, 1),
            "win_after": round(win_after, 1),
            "win_swing": round(win_before - win_after, 1),
            "eval_after_cp": after_eval_cp,
            "eval_after": _eval_str_from_signed_cp(after_eval_cp),
            "is_engine_best": bool(is_best),
            "better_move_san": result["best_san"],
            "refutation_line_san": refutation_san,
            "refutation_line_uci": refutation_uci,
        }

    return result


@mcp.tool()
def goto_mistake(index: int) -> dict:
    """Move the review cursor to mistake #index and return the position before it.

    Use the `index` values from `analyze_game`'s mistake list. Returns the FEN one move
    before the mistake so narration (and, later, the web board) stays in sync.
    """
    sess = session_mod.get_session()
    if sess is None:
        return {"error": "No game analysed yet. Call analyze_game first."}
    if not sess.mistakes:
        return {"error": "The analysed game has no flagged mistakes."}
    if index < 0 or index >= len(sess.mistakes):
        return {"error": f"index out of range 0..{len(sess.mistakes) - 1}"}

    sess.current_index = index
    sess.explore_fen = None
    m = sess.mistakes[index]
    prompt = (
        f"Move {m.move_number} ({m.color}): you played {m.move_san} "
        f"({m.classification}, lost {m.win_swing}% win chance). "
        f"It's {m.color} to move — find something better."
    )
    return {
        "index": index,
        "ply": m.ply,
        "move_number": m.move_number,
        "color": m.color,
        "fen": m.fen_before,
        "move_played_san": m.move_san,
        "classification": m.classification,
        "best_move_san": m.best_move_san,
        "best_line_san": m.best_line_san,
        "prompt": prompt,
    }


def main() -> None:
    try:
        mcp.run()
    finally:
        engine.shutdown()


if __name__ == "__main__":
    main()
