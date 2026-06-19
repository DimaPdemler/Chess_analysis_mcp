"""Configuration for the chess review server.

All tunables live here so the engine, analysis, and MCP layers agree on defaults.
Values can be overridden via environment variables.
"""
from __future__ import annotations

import os

# Repo root (this file is <repo>/server/config.py), used for repo-relative defaults.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Path to the Stockfish binary. Defaults to "stockfish" on PATH; the .mcp.json
# registration sets this explicitly to /usr/local/bin/stockfish.
STOCKFISH_PATH: str = os.environ.get("STOCKFISH_PATH", "stockfish")

# Depth used for on-demand single-position analysis (get_engine_line, REPL checks).
# Fixed depth keeps evals reproducible and cacheable.
DEFAULT_DEPTH: int = int(os.environ.get("CHESS_DEFAULT_DEPTH", "18"))

# Depth used when sweeping every ply of a full game. Lower than DEFAULT_DEPTH so a
# full-game review finishes in reasonable time; positions can be re-deepened on
# demand via get_engine_line.
SWEEP_DEPTH: int = int(os.environ.get("CHESS_SWEEP_DEPTH", "16"))

DEFAULT_MULTIPV: int = int(os.environ.get("CHESS_DEFAULT_MULTIPV", "1"))

# Engine process pool size. 1-2 is plenty for a single-user local tool. Default 2 so the
# web /evaluate route and a concurrent MCP call don't serialise behind one engine.
ENGINE_POOL_SIZE: int = int(os.environ.get("CHESS_ENGINE_POOL_SIZE", "2"))

# Per-engine UCI options.
ENGINE_THREADS: int = int(os.environ.get("CHESS_ENGINE_THREADS", "2"))
ENGINE_HASH_MB: int = int(os.environ.get("CHESS_ENGINE_HASH_MB", "128"))

# Centipawn magnitude treated as "mate-equivalent" when converting mate scores.
MATE_SCORE_CP: int = 10000

# Used by analyze_game(player="auto") to pick which side is "me" from PGN headers.
USERNAME: str = os.environ.get("CHESS_USERNAME", "thedarktintin")


def _parse_aliases(raw: str) -> list[tuple[str | None, str]]:
    """Parse CHESS_ALIASES into (platform|None, handle_lower) pairs.

    Just a comma-separated list of your other handles, e.g. "my_chesscom_name, my_other_name".
    Each item normally matches on any site; advanced users can pin one to a single platform with
    "platform:handle" ("chesscom:dpdemler"). All of them resolve to CHESS_USERNAME as the canonical
    player_id, so several accounts fold into one coaching profile (and into player="auto" detection).
    """
    pairs: list[tuple[str | None, str]] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if ":" in tok:
            plat, name = tok.split(":", 1)
            pairs.append((plat.strip().lower() or None, name.strip().lower()))
        else:
            pairs.append((None, tok.lower()))
    return pairs


# Extra account handles that are also "me" (folded into CHESS_USERNAME's profile). Set in
# .mcp.json's env, e.g. CHESS_ALIASES="chesscom:dpdemler, my_other_lichess".
USERNAME_ALIASES: list[tuple[str | None, str]] = _parse_aliases(os.environ.get("CHESS_ALIASES", ""))

# Game history (personalised coaching). Each analysed game is appended as one line to
# <DATA_DIR>/history/games.jsonl, deduped by (game_id, reviewed_side). Identity aliases
# (one person, several lichess/chess.com accounts) live in <DATA_DIR>/identities.json, and
# a rebuildable per-player profile is cached in <DATA_DIR>/profiles/<player_id>.json.
# Defaults to <repo>/.chess-review (gitignored, so it stays local but out of version control).
# CHESS_DATA_DIR overrides the location; CHESS_HISTORY=0 disables recording entirely.
DATA_DIR: str = os.environ.get("CHESS_DATA_DIR", os.path.join(_REPO_ROOT, ".chess-review"))
HISTORY_ENABLED: bool = os.environ.get("CHESS_HISTORY", "1") != "0"

# Self-terminate the server process after this many seconds of inactivity (no MCP tool call
# and no board request), so an abandoned session doesn't linger as a process forever. Activity
# resets the timer. Default 24h; CHESS_SESSION_TTL=0 disables the watchdog.
SESSION_TTL_SECONDS: int = int(os.environ.get("CHESS_SESSION_TTL", str(24 * 60 * 60)))


def _parse_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


# Coaching profile is a HYBRID of two views so it adapts as a player improves:
#   - "recent form" = the last CHESS_PROFILE_RECENT games (a sliding window; <=0 means all games).
#   - "lifetime"    = CHESS_PROFILE_LIFETIME: unset/"all" -> all history (default); a positive N ->
#                     the last N games; "0" -> DISABLED, leaving only the recent window (i.e. a pure
#                     sliding window). Both are recomputed from the full games.jsonl, so widening a
#                     window later loses nothing.
PROFILE_RECENT_WINDOW: int = _parse_int("CHESS_PROFILE_RECENT", 25)


def _parse_lifetime(raw: str | None) -> int | None:
    raw = (raw or "").strip().lower()
    if raw in ("", "all"):
        return None  # all history
    try:
        return max(int(raw), 0)  # 0 disables the lifetime view; positive caps it
    except ValueError:
        return None


PROFILE_LIFETIME: int | None = _parse_lifetime(os.environ.get("CHESS_PROFILE_LIFETIME"))

# Web board (Phase 4). The FastAPI server runs in the same process as the MCP server,
# sharing the one engine pool and ReviewSession. WEB_AUTOSTART=0 disables the autostart
# (e.g. when driving the web server standalone via scripts/run_web.py).
WEB_HOST: str = os.environ.get("CHESS_WEB_HOST", "127.0.0.1")
WEB_PORT: int = int(os.environ.get("CHESS_WEB_PORT", "8765"))
WEB_AUTOSTART: bool = os.environ.get("CHESS_WEB_AUTOSTART", "1") != "0"
# Auto-open the board in the default browser the first time a game is analysed, so a
# first-time user never has to be told the URL. Set CHESS_WEB_OPEN=0 to disable.
WEB_OPEN: bool = os.environ.get("CHESS_WEB_OPEN", "1") != "0"
