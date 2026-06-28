"""In-browser chat route (Phase 6): POST /api/chat -> headless Claude Code.

Also hosts POST /api/coach: the opt-in, Claude-written end-of-game summary (the free templated
blurb rides on /api/session instead).
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from server import claude_bridge, config
from server.core import analysis_cache, chat_store
from server.core import session as session_mod

router = APIRouter()


class ChatBody(BaseModel):
    question: str
    fen: str | None = None  # the board the user is viewing
    last_move: str | None = None  # the move in question
    move_fen: str | None = None  # the position that move was played from
    session_id: str | None = None
    use_profile: bool = False  # inject the player's cross-game coaching profile


class CoachBody(BaseModel):
    force: bool = False  # regenerate even if a summary already exists (the ⟳ refresh)


@router.post("/chat")
def chat(body: ChatBody) -> JSONResponse:
    """Answer a position-aware 'why?' / 'what now?' question on the user's Claude subscription."""
    if not body.question.strip():
        return JSONResponse({"error": "Empty question."}, status_code=400)
    sess = session_mod.get_session()
    # If the frontend didn't carry a session id (e.g. just switched back to this game), thread
    # onto the one we stored for it so the conversation stays continuous.
    session_id = body.session_id
    if sess is not None and not session_id:
        session_id = chat_store.get(sess).get("session_id")
    try:
        res = claude_bridge.ask(
            body.question,
            fen=body.fen,
            last_move=body.last_move,
            move_fen=body.move_fen,
            session_id=session_id,
            use_profile=body.use_profile,
        )
    except claude_bridge.ChatError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    # Remember the exchange in-memory for this game so switching games and back restores it
    # (cleared when the app closes — never written to disk).
    if sess is not None:
        chat_store.record(sess, body.question, res.get("answer", ""), res.get("session_id"))
    return JSONResponse(res)


@router.get("/chat-history")
def chat_history() -> JSONResponse:
    """The in-memory Q&A transcript for the current game (empty if none / app just opened)."""
    sess = session_mod.get_session()
    if sess is None:
        return JSONResponse({"messages": [], "session_id": None})
    return JSONResponse(chat_store.get(sess))


@router.post("/chat-reset")
def chat_reset() -> dict:
    """Drop all in-memory chat transcripts — called by the frontend on a fresh app session.

    The chat store is process-local, so a server that restarts already starts clean. This covers
    the case where the *same* server is reused across app launches (e.g. a long-lived board that
    didn't exit on close): a brand-new browser session wipes the old Snowie conversation so reopening
    the app shows an empty chat. A refresh keeps its sessionStorage flag and never calls this, so it
    preserves the conversation.
    """
    chat_store.clear()
    return {"ok": True}


@router.post("/coach")
def coach(body: CoachBody | None = None) -> JSONResponse:
    """Generate (once, then cache) the on-demand Claude-written summary for the current game.

    Ungated: this is only ever called by an explicit user action (the AI-summary button, the
    auto-press when the user has turned that on, or the ⟳ refresh which passes ``force``), so it
    spends Claude only when asked. ``force`` regenerates even if a summary already exists.
    """
    force = bool(body and body.force)
    sess = session_mod.get_session()
    if sess is None:
        return JSONResponse({"error": "No game analysed yet."}, status_code=400)
    if sess.coach_ai_text and not force:  # already written — reuse, no second Claude call
        return JSONResponse({"summary": sess.coach_ai_text, "cached": True})
    try:
        text = claude_bridge.coach_summary_ai(sess)
    except claude_bridge.ChatError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    sess.coach_ai_text = text
    # Persist the summary alongside the cached game so reopening it (even after a restart) shows
    # the saved text instead of regenerating — unless the user opted out of remembering summaries.
    if config.COACH_AI_PERSIST:
        analysis_cache.store(sess)
    return JSONResponse({"summary": text})
