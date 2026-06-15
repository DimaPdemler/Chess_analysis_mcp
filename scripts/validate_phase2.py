"""Phase 2 validation: analyse the sample PGNs and print the mistake lists.

Usage:
    /opt/miniconda3/envs/chess-review/bin/python scripts/validate_phase2.py example_pgns/game1.pgn white
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.core import engine
from server.core.game_analysis import analyze_game


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "example_pgns/game1.pgn"
    player = sys.argv[2] if len(sys.argv) > 2 else "auto"
    pgn = Path(path).read_text()

    t = time.time()
    session = analyze_game(pgn, player=player)
    dt = time.time() - t

    print(f"=== {path} (player={session.player}) analysed in {dt:.1f}s ===")
    print(f"Result: {session.result}")
    print(f"Accuracy  white={session.accuracy_white}  black={session.accuracy_black}")
    print(f"My moves analysed: {len(session.all_moves)}  mistakes: {len(session.mistakes)}")
    print()
    print(f"{'move':>8}  {'class':<11} {'swing':>6}  {'eval_b':>7} {'eval_a':>7}  best")
    for m in session.mistakes:
        tag = f"{m.move_number}{'.' if m.color=='white' else '...'}{m.move_san}"
        print(
            f"{tag:>8}  {m.classification:<11} {m.win_swing:>6} "
            f"{m.eval_before:>7} {m.eval_after:>7}  {m.best_move_san} "
            f"({' '.join(m.best_line_san[:4])})"
        )
    engine.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
