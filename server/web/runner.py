"""Start the FastAPI web server in a background daemon thread.

Called from `mcp_server.main()` so the board shares the MCP process's engine pool and
session. Idempotent and best-effort: a port collision (a stale instance still bound) logs
to stderr and never crashes the MCP server, since stdout is owned by the MCP protocol.
"""
from __future__ import annotations

import sys
import threading
import webbrowser

import uvicorn

from server import config
from server.web.app import create_app

_thread: threading.Thread | None = None
_lock = threading.Lock()
_opened = False
_open_lock = threading.Lock()


def open_board_once() -> None:
    """Open the board in the default browser, at most once per process.

    Called when a game is analysed (not at server boot) so the tab only appears once
    there is actually a game to look at. Best-effort: a headless box or a missing
    browser just logs to stderr and never raises. Disable with CHESS_WEB_OPEN=0.
    """
    global _opened
    if not config.WEB_OPEN:
        return
    with _open_lock:
        if _opened:
            return
        _opened = True
    url = f"http://{config.WEB_HOST}:{config.WEB_PORT}"
    try:
        if webbrowser.open(url):
            print(f"[chess-web] opened board in browser: {url}", file=sys.stderr, flush=True)
        else:
            print(
                f"[chess-web] no browser to open; board is at {url}",
                file=sys.stderr,
                flush=True,
            )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[chess-web] could not open browser ({exc}); board is at {url}",
              file=sys.stderr, flush=True)


def _serve() -> None:
    try:
        cfg = uvicorn.Config(
            create_app(),
            host=config.WEB_HOST,
            port=config.WEB_PORT,
            log_level="warning",
            access_log=False,
        )
        uvicorn.Server(cfg).run()  # blocks (runs its own event loop)
    except OSError as exc:
        print(
            f"[chess-web] could not bind {config.WEB_HOST}:{config.WEB_PORT} ({exc}); "
            "board disabled for this process.",
            file=sys.stderr,
            flush=True,
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[chess-web] web server stopped: {exc}", file=sys.stderr, flush=True)


def start_in_thread() -> None:
    """Start the web server once. Safe to call multiple times."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_serve, name="chess-web", daemon=True)
        _thread.start()
        print(
            f"[chess-web] serving board at http://{config.WEB_HOST}:{config.WEB_PORT}",
            file=sys.stderr,
            flush=True,
        )
