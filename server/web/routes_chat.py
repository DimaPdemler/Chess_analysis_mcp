"""In-browser chat route (Phase 6): POST /api/chat -> headless Claude Code.

Also hosts POST /api/coach: the opt-in, Claude-written end-of-game summary (the free templated
blurb rides on /api/session instead).
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from server import claude_bridge
from server.core import session as session_mod

router = APIRouter()


class ChatBody(BaseModel):
    question: str
    fen: str | None = None  # the board the user is viewing
    last_move: str | None = None  # the move in question
    move_fen: str | None = None  # the position that move was played from
    session_id: str | None = None
    use_profile: bool = False  # inject the player's cross-game coaching profile


@router.post("/chat")
def chat(body: ChatBody) -> JSONResponse:
    """Answer a position-aware 'why?' / 'what now?' question on the user's Claude subscription."""
    if not body.question.strip():
        return JSONResponse({"error": "Empty question."}, status_code=400)
    try:
        res = claude_bridge.ask(
            body.question,
            fen=body.fen,
            last_move=body.last_move,
            move_fen=body.move_fen,
            session_id=body.session_id,
            use_profile=body.use_profile,
        )
    except claude_bridge.ChatError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    return JSONResponse(res)


@router.post("/coach")
def coach() -> JSONResponse:
    """Generate (once, then cache) the on-demand Claude-written summary for the current game.

    Ungated: this is only ever called by an explicit user action (the AI-summary button, or the
    auto-press when the user has turned that on in Settings), so it spends Claude only when asked.
    """
    sess = session_mod.get_session()
    if sess is None:
        return JSONResponse({"error": "No game analysed yet."}, status_code=400)
    if sess.coach_ai_text:  # already written for this game — reuse, no second Claude call
        return JSONResponse({"summary": sess.coach_ai_text, "cached": True})
    try:
        text = claude_bridge.coach_summary_ai(sess)
    except claude_bridge.ChatError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    sess.coach_ai_text = text
    return JSONResponse({"summary": text})
