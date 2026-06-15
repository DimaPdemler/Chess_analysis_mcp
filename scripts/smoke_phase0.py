"""Phase 0 smoke test: open Stockfish, evaluate the start position, quit cleanly.

Run with the conda interpreter:
    /opt/miniconda3/envs/chess-review/bin/python scripts/smoke_phase0.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script (no package install needed).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chess
import chess.engine

from server import config


def main() -> int:
    print(f"Stockfish path: {config.STOCKFISH_PATH}")
    engine = chess.engine.SimpleEngine.popen_uci(config.STOCKFISH_PATH)
    try:
        engine.configure({"Threads": config.ENGINE_THREADS, "Hash": config.ENGINE_HASH_MB})
        board = chess.Board()  # start position
        depth = config.DEFAULT_DEPTH
        info = engine.analyse(board, chess.engine.Limit(depth=depth))
        score = info["score"]  # PovScore, white-relative by default for white-to-move
        pv = info.get("pv", [])
        best = pv[0] if pv else None
        print(f"Depth {depth} eval (side-to-move relative): {score.relative}")
        print(f"Best move: {board.san(best) if best else 'n/a'}")
        print(f"PV: {' '.join(m.uci() for m in pv[:6])}")
    finally:
        engine.quit()
    print("Engine quit cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
