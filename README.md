# Chess Review MCP

Analyse a chess game (PGN) with Stockfish, find where you went wrong, and — unlike
Lichess — get the mistakes **explained in words**, grounded in real engine lines. This is
phases 0–3 of the build: a fully terminal-drivable tool you run from Claude Code. The
interactive browser board and in-browser chat (phases 4–7) come later.

## What works now

- `analyze_game(pgn, player)` — full-game analysis → ordered mistake list + per-side accuracy.
- `get_engine_line(fen, move?, depth, multipv)` — evaluate a position or a candidate move;
  returns the best line and, for a given move, its classification and the engine's
  **refutation** (why it's bad).
- `goto_mistake(index)` — anchor the review to a specific mistake.

Mistake classification mirrors Lichess (win% drop thresholds 5/10/15), validated against
`example_pgns/game1.pgn` where it reproduces Lichess's own labels.

## Setup

Uses the existing conda env — **do not** use `conda activate`; call the interpreter directly.

- Python: `/opt/miniconda3/envs/chess-review/bin/python`
- Stockfish: `/usr/local/bin/stockfish` (set `STOCKFISH_PATH` to override)

Dependencies are already installed in that env. If you ever need to reinstall:

```bash
/opt/miniconda3/envs/chess-review/bin/pip install -e ".[dev]"
```

## Use it from Claude Code

The server is registered in `.mcp.json` as **`chess`**. Reload Claude Code in this directory
so it picks up the server, then:

1. Paste a PGN and say *"analyse this game"* → Claude calls `mcp__chess__analyze_game`.
2. Ask *"why was move 8 bad?"* → Claude calls `mcp__chess__get_engine_line` and explains
   using the returned best line + refutation.

## Run the tests / smoke checks

```bash
# unit + engine + game-analysis tests
STOCKFISH_PATH=/usr/local/bin/stockfish \
  /opt/miniconda3/envs/chess-review/bin/python -m pytest

# Phase 0 engine smoke test
/opt/miniconda3/envs/chess-review/bin/python scripts/smoke_phase0.py

# Phase 2 validation against a real game (prints the mistake list)
/opt/miniconda3/envs/chess-review/bin/python scripts/validate_phase2.py example_pgns/game1.pgn white
```

## Layout

```
server/
  config.py            # STOCKFISH_PATH, depths, username for player="auto"
  core/
    engine.py          # Stockfish pool, cached fixed-depth analyse()
    evaluation.py      # cp -> win%, Lichess-style classify(), accuracy
    game_analysis.py   # PGN -> [MoveReview] -> ReviewSession
    session.py         # shared in-memory ReviewSession singleton
  mcp_server.py        # FastMCP server: analyze_game / get_engine_line / goto_mistake
scripts/               # smoke + validation scripts
tests/                 # pytest suite
example_pgns/          # sample games (ground truth)
```

## Notes

- **Reproducible evals:** analysis is at fixed depth and cached by `(fen, depth, multipv)`.
  Full-game sweeps use `SWEEP_DEPTH` (16); single-position lookups use `DEFAULT_DEPTH` (18).
- **One process, one engine pool, one session** — the design that lets the future web board
  share state with the MCP tools.
