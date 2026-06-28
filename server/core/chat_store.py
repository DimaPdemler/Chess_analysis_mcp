"""In-memory, per-game chat transcripts for the in-browser "why?" coach.

Unlike the AI coach *summary* (which is persisted to the analysis cache so it survives restarts),
the chat Q&A is deliberately **process-local and ephemeral**: it lives only as long as the running
app. Keying by ``(game_id, reviewed_side)`` means switching to another game and back restores that
game's prior conversation within the session, but closing the app wipes everything — no disk writes.

The Claude ``--resume`` session id is stored alongside the messages so a restored conversation keeps
threading into the same headless ``claude -p`` session.
"""
from __future__ import annotations

import threading
from typing import Optional

from server.core import analysis_cache
from server.core.session import ReviewSession

# {(game_id, side): {"messages": [{"role": "user"|"bot", "text": str}], "session_id": str|None}}
_STORE: dict[tuple[str, str], dict] = {}
_LOCK = threading.Lock()


def game_key(sess: ReviewSession) -> Optional[tuple[str, str]]:
    """The (game_id, side) key for a session, or None if it has no moves to key on.

    Reuses the analysis-cache id derivation so the chat key matches the game's cache/history id.
    """
    ucis = analysis_cache._sess_ucis(sess)
    if not ucis:
        return None
    return (analysis_cache._game_id(ucis), sess.player)


def get(sess: ReviewSession) -> dict:
    """Return ``{"messages": [...], "session_id": ...}`` for this game (empty if none yet)."""
    key = game_key(sess)
    if key is None:
        return {"messages": [], "session_id": None}
    with _LOCK:
        entry = _STORE.get(key)
        if entry is None:
            return {"messages": [], "session_id": None}
        # Copy so callers can't mutate the stored list.
        return {"messages": list(entry["messages"]), "session_id": entry.get("session_id")}


def record(
    sess: ReviewSession, question: str, answer: str, session_id: Optional[str]
) -> None:
    """Append one Q/A exchange for this game and remember the latest Claude session id."""
    key = game_key(sess)
    if key is None:
        return
    with _LOCK:
        entry = _STORE.setdefault(key, {"messages": [], "session_id": None})
        entry["messages"].append({"role": "user", "text": question})
        entry["messages"].append({"role": "bot", "text": answer})
        if session_id:
            entry["session_id"] = session_id


def clear() -> None:
    """Drop all stored transcripts (used by tests)."""
    with _LOCK:
        _STORE.clear()
