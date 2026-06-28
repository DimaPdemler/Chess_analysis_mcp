#!/usr/bin/env python3
"""Collect GitHub traffic/download stats and append them to CSVs (idempotent).

Designed to run daily (locally or, preferably, from a scheduled GitHub Action —
see .github/workflows/traffic-stats.yml). GitHub only keeps 14 days of
clone/view history, so running daily and *upserting by date* guarantees no day
is ever lost and re-runs never double-count.

Output (one row per day, keyed/deduped by date so it's safe to re-run):
  traffic_daily.csv      date, clones, clone_uniques, views, view_uniques
  downloads_daily.csv    snapshot_date, tag, asset, download_count   (cumulative)
  referrers_daily.csv    snapshot_date, referrer, views, uniques

Requires the `gh` CLI, authenticated with a token that has PUSH access to the
repo (the /traffic endpoints are owner-only). Pass the token via GH_TOKEN.

Usage:
  python scripts/collect_traffic_stats.py --out-dir <dir> [--repo owner/name]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import subprocess
import sys

REPO_DEFAULT = "Chess-analysis-mcp/tintins-chess-analysis"


def gh_api(path: str) -> object:
    """Call `gh api <path>` and return parsed JSON (or None on failure)."""
    try:
        out = subprocess.run(
            ["gh", "api", path],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return json.loads(out)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"gh api {path} failed: {e.stderr.strip()}\n")
        return None


def upsert_csv(path: str, fieldnames: list[str], key: list[str], rows: list[dict]) -> int:
    """Merge `rows` into the CSV at `path`, replacing any existing row whose
    `key` columns match. Returns the number of rows in the final file."""
    existing: dict[tuple, dict] = {}
    if os.path.exists(path):
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                existing[tuple(r[k] for k in key)] = r
    for r in rows:
        existing[tuple(str(r[k]) for k in key)] = r
    ordered = sorted(existing.values(), key=lambda r: tuple(str(r[k]) for k in key))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(ordered)
    return len(ordered)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True, help="Directory to write the CSVs into")
    ap.add_argument("--repo", default=REPO_DEFAULT)
    args = ap.parse_args()

    today = dt.date.today().isoformat()
    out = args.out_dir

    # --- Traffic: one row per day (clones + views), keyed by date ---
    clones = gh_api(f"repos/{args.repo}/traffic/clones") or {"clones": []}
    views = gh_api(f"repos/{args.repo}/traffic/views") or {"views": []}
    by_date: dict[str, dict] = {}
    for c in clones.get("clones", []):
        d = c["timestamp"][:10]
        by_date.setdefault(d, {"date": d, "clones": 0, "clone_uniques": 0,
                               "views": 0, "view_uniques": 0})
        by_date[d]["clones"] = c["count"]
        by_date[d]["clone_uniques"] = c["uniques"]
    for v in views.get("views", []):
        d = v["timestamp"][:10]
        by_date.setdefault(d, {"date": d, "clones": 0, "clone_uniques": 0,
                               "views": 0, "view_uniques": 0})
        by_date[d]["views"] = v["count"]
        by_date[d]["view_uniques"] = v["uniques"]
    n_traffic = upsert_csv(
        os.path.join(out, "traffic_daily.csv"),
        ["date", "clones", "clone_uniques", "views", "view_uniques"],
        ["date"],
        list(by_date.values()),
    )

    # --- Downloads: cumulative snapshot per (day, tag, asset) ---
    releases = gh_api(f"repos/{args.repo}/releases") or []
    dl_rows = [
        {"snapshot_date": today, "tag": rel["tag_name"],
         "asset": a["name"], "download_count": a["download_count"]}
        for rel in releases for a in rel.get("assets", [])
    ]
    n_dl = upsert_csv(
        os.path.join(out, "downloads_daily.csv"),
        ["snapshot_date", "tag", "asset", "download_count"],
        ["snapshot_date", "tag", "asset"],
        dl_rows,
    )

    # --- Referrers: snapshot per (day, referrer) ---
    refs = gh_api(f"repos/{args.repo}/traffic/popular/referrers") or []
    ref_rows = [
        {"snapshot_date": today, "referrer": r["referrer"],
         "views": r["count"], "uniques": r["uniques"]}
        for r in refs
    ]
    n_ref = upsert_csv(
        os.path.join(out, "referrers_daily.csv"),
        ["snapshot_date", "referrer", "views", "uniques"],
        ["snapshot_date", "referrer"],
        ref_rows,
    )

    print(f"OK {today}: traffic={n_traffic} rows, downloads={n_dl} rows, "
          f"referrers={n_ref} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
