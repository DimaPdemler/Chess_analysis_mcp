"""Idle watchdog: self-terminate the server process after a stretch of inactivity.

The MCP server (and its in-process web board) is long-lived — Claude Code spawns it and it
otherwise runs until the machine reboots, so abandoned sessions can pile up as stray processes.
This module tracks a last-activity timestamp that the MCP tools and the web layer `touch()` on
every call, and a background thread that exits the process once it's been idle for
`config.SESSION_TTL_SECONDS`. Activity resets the timer, so an in-use session is never killed.

Exit is via `os._exit` after `engine.shutdown()`: the engine pool runs non-daemon threads, so a
plain return/`sys.exit` could hang — `os._exit` guarantees the process actually goes away.
"""
from __future__ import annotations

import os
import sys
import threading
import time

from server import config
from server.core import engine

_lock = threading.Lock()
_last_activity = time.monotonic()
_started = False
_stop = threading.Event()
_thread: threading.Thread | None = None


def touch() -> None:
    """Mark the session as active right now (resets the idle timer)."""
    global _last_activity
    with _lock:
        _last_activity = time.monotonic()


def _idle_seconds() -> float:
    with _lock:
        return time.monotonic() - _last_activity


def _run(ttl: int) -> None:
    # Wake often enough to notice the deadline promptly, but never busy-loop. `_stop.wait`
    # returns True the instant we're asked to stop (clean shutdown / tests), ending the loop
    # without exiting the process.
    interval = max(1, min(ttl, 600))
    while not _stop.wait(interval):
        if _idle_seconds() >= ttl:
            print(
                f"[chess] no activity for {ttl}s — shutting the session down to free the process.",
                file=sys.stderr,
                flush=True,
            )
            try:
                engine.shutdown()
            finally:
                os._exit(0)


def start_watchdog() -> None:
    """Start the idle watchdog once. No-op if disabled (TTL <= 0) or already running."""
    global _started, _thread
    ttl = config.SESSION_TTL_SECONDS
    if ttl <= 0:
        return
    with _lock:
        if _started:
            return
        _started = True
    _stop.clear()
    touch()  # start the clock from "now"
    _thread = threading.Thread(target=_run, args=(ttl,), name="chess-watchdog", daemon=True)
    _thread.start()


def stop_watchdog() -> None:
    """Stop the watchdog thread without exiting the process (clean shutdown / tests)."""
    global _started
    _stop.set()
    with _lock:
        _started = False
