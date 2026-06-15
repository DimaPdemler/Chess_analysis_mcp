"""Process-wide review session state shared between the MCP tools and (later) the web layer.

The MCP `analyze_game` tool *writes* the session; `goto_mistake` mutates `current_index`;
the future FastAPI board will *read* it. Keeping this a single in-memory singleton is the
explicit design choice from the plan (one process, one session)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from server.core.evaluation import Classification


class MoveReview(BaseModel):
    """Full review of a single one of *my* moves."""

    ply: int  # 1-based half-move number in the game
    move_number: int  # full-move number (e.g. 4 for "4. Nf3")
    color: str  # "white" | "black" (whose move this is)
    move_san: str
    move_uci: str
    fen_before: str
    fen_after: str
    eval_before: float  # centipawns from my perspective (best available), mate -> +/-MATE
    eval_after: float  # centipawns from my perspective after my move
    win_before: float  # win% from my perspective (best available)
    win_after: float  # win% from my perspective after my move
    win_swing: float  # win_before - win_after (>=0 means I lost ground)
    classification: Classification
    best_move_san: str
    best_line_uci: list[str] = Field(default_factory=list)
    best_line_san: list[str] = Field(default_factory=list)
    accuracy: float


class ReviewSession(BaseModel):
    """Everything about one analysed game."""

    pgn: str
    player: str  # "white" | "black" — whose mistakes we reviewed
    headers: dict[str, str] = Field(default_factory=dict)
    result: str = "*"
    accuracy_white: float = 100.0
    accuracy_black: float = 100.0
    all_moves: list[MoveReview] = Field(default_factory=list)  # every move by `player`
    mistakes: list[MoveReview] = Field(default_factory=list)  # inaccuracy/mistake/blunder
    current_index: int = 0  # index into `mistakes`
    explore_fen: Optional[str] = None


# Module-level singleton.
_SESSION: Optional[ReviewSession] = None


def set_session(session: ReviewSession) -> None:
    global _SESSION
    _SESSION = session


def get_session() -> Optional[ReviewSession]:
    return _SESSION


def clear_session() -> None:
    global _SESSION
    _SESSION = None
