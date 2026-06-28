"""Disk cache of fully-analysed games so reopening a past game is instant.

A full :class:`ReviewSession` (timeline + per-mistake comments + mistakes) is expensive to
compute — a ~20-45s Stockfish sweep — but cheap to store (~tens of KB of JSON). We persist
each analysed session to ``<DATA_DIR>/analysis-cache/<game_id>_<side>.json`` keyed by the same
``(game_id, reviewed_side)`` pair the history layer dedupes on, so reopening any game already
analysed on this machine — *even in a previous app session* — loads from disk instead of
re-running the engine.

The cache key is derived from the move list alone (``game_id = sha1(all UCI moves)[:16]``), so
``load`` can compute it straight from a PGN, before any analysis, and short-circuit the sweep.

Everything here is best-effort and engine-free: any failure (corrupt file, schema bump, disk
error) is swallowed and the caller falls back to a fresh sweep. ``CHESS_ANALYSIS_CACHE=0``
disables it; the entry count is bounded (oldest-by-access pruned) so disk use stays in check.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
from typing import Optional

import chess.pgn

from server import config
from server.core.game_analysis import resolve_player
from server.core.session import ReviewSession

# Bump when the on-disk payload shape (or ReviewSession schema) changes incompatibly, so stale
# files are ignored rather than mis-parsed.
CACHE_VERSION = 1


# --------------------------------------------------------------------------------------
# Paths / keys
# --------------------------------------------------------------------------------------
def _cache_dir() -> str:
    return os.path.join(config.DATA_DIR, "analysis-cache")


def _safe(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", part or "").strip("_") or "x"


def _path(game_id: str, side: str) -> str:
    return os.path.join(_cache_dir(), f"{_safe(game_id)}_{_safe(side)}.json")


def _game_id(ucis: list[str]) -> str:
    """sha1 of the concatenated UCI move list — identical to ``history._game_id``."""
    return hashlib.sha1("".join(ucis).encode("utf-8")).hexdigest()[:16]


def _sess_ucis(sess: ReviewSession) -> list[str]:
    """Every move (both sides) of the session, mirroring ``history._full_move_ucis`` so the
    game_id computed here matches the one history records under."""
    ucis = [n["move_uci"] for n in sess.timeline if n.get("move_uci")]
    return ucis or [m.move_uci for m in sess.all_moves]


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------
def store(sess: ReviewSession) -> None:
    """Persist a fully-analysed session to disk. Best-effort: never raises."""
    if not config.ANALYSIS_CACHE_ENABLED:
        return
    try:
        ucis = _sess_ucis(sess)
        if not ucis:  # nothing to key on (empty/illegal game)
            return
        path = _path(_game_id(ucis), sess.player)
        os.makedirs(_cache_dir(), exist_ok=True)
        payload = {
            "version": CACHE_VERSION,
            "side": sess.player,
            "sweep_depth": sess.sweep_depth,
            "session": json.loads(sess.model_dump_json()),
        }
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)  # atomic
        _prune()
    except Exception:  # pragma: no cover - caching must never break a review
        pass


def load(pgn: str, player: str = "auto") -> Optional[ReviewSession]:
    """Return a cached session for this PGN+side, or None if not cached / unreadable.

    The reviewed side is resolved the same way the analysis path resolves it (``resolve_player``),
    so ``player="auto"`` finds the entry stored under the auto-detected colour.
    """
    if not config.ANALYSIS_CACHE_ENABLED:
        return None
    try:
        game = chess.pgn.read_game(io.StringIO(pgn or ""))
        if game is None:
            return None
        side = resolve_player(dict(game.headers), player)
        ucis = [m.uci() for m in game.mainline_moves()]
        if not ucis:
            return None
        path = _path(_game_id(ucis), side)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if payload.get("version") != CACHE_VERSION:
            return None
        sess = ReviewSession.model_validate(payload["session"])
        # Fresh open: drop any saved navigation state.
        sess.current_index = 0
        sess.explore_fen = None
        # The AI coach summary is persisted inside this payload, but only honoured when the user
        # has opted to remember summaries between sessions. Off -> drop it so it regenerates.
        if not config.COACH_AI_PERSIST:
            sess.coach_ai_text = None
        os.utime(path, None)  # mark as recently used for LRU pruning
        return sess
    except Exception:  # pragma: no cover - a bad cache file just means "miss"
        return None


def _prune() -> None:
    """Keep at most ``config.ANALYSIS_CACHE_MAX`` entries, dropping least-recently-used first."""
    cap = config.ANALYSIS_CACHE_MAX
    if cap <= 0:
        return
    try:
        entries = [
            os.path.join(_cache_dir(), n)
            for n in os.listdir(_cache_dir())
            if n.endswith(".json")
        ]
        if len(entries) <= cap:
            return
        entries.sort(key=lambda p: os.path.getmtime(p))  # oldest access first
        for p in entries[: len(entries) - cap]:
            try:
                os.remove(p)
            except OSError:
                pass
    except OSError:
        pass
