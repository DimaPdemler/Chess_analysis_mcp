"""Tests for the idle watchdog (server self-terminates after inactivity).

Each test that starts the real thread stops it in a `finally` *before* monkeypatch tears the
mocks down, so a live watchdog can never call the real os._exit and kill the test runner.
"""
from __future__ import annotations

import time

from server.core import lifecycle


def _drain():
    lifecycle.stop_watchdog()
    if lifecycle._thread is not None:
        lifecycle._thread.join(timeout=3)


def test_touch_resets_idle():
    lifecycle.touch()
    assert lifecycle._idle_seconds() < 0.5


def test_watchdog_disabled_when_ttl_zero(monkeypatch):
    monkeypatch.setattr(lifecycle.config, "SESSION_TTL_SECONDS", 0)
    monkeypatch.setattr(lifecycle, "_started", False)
    lifecycle.start_watchdog()
    assert lifecycle._started is False  # no thread started


def test_watchdog_exits_after_idle(monkeypatch):
    calls: dict = {}

    def fake_exit(code):
        calls["exited"] = code
        lifecycle._stop.set()  # let the loop end on its next wait instead of killing the process

    monkeypatch.setattr(lifecycle.engine, "shutdown", lambda: calls.__setitem__("shutdown", True))
    monkeypatch.setattr(lifecycle.os, "_exit", fake_exit)
    monkeypatch.setattr(lifecycle.config, "SESSION_TTL_SECONDS", 1)
    monkeypatch.setattr(lifecycle, "_started", False)
    try:
        lifecycle.start_watchdog()  # touches once, then we never touch again -> idles out
        for _ in range(50):  # up to ~5s
            if "exited" in calls:
                break
            time.sleep(0.1)
        assert calls.get("exited") == 0
        assert calls.get("shutdown") is True
    finally:
        _drain()


def test_activity_keeps_watchdog_alive(monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(lifecycle.engine, "shutdown", lambda: None)
    monkeypatch.setattr(lifecycle.os, "_exit", lambda code: calls.__setitem__("exited", code))
    monkeypatch.setattr(lifecycle.config, "SESSION_TTL_SECONDS", 2)
    monkeypatch.setattr(lifecycle, "_started", False)
    try:
        lifecycle.start_watchdog()
        # Keep touching for longer than the TTL: it must NOT exit while active.
        for _ in range(15):  # ~3s > TTL
            lifecycle.touch()
            time.sleep(0.2)
        assert "exited" not in calls
    finally:
        _drain()
