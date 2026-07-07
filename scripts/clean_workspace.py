"""
scripts/clean_workspace.py
==========================
Purge local runtime debris so the working directory stays as clean as the
git repository. Never touches tracked files, reference data, generated
quality reports, or the Nominatim API cache.

Removed always:
  - every __pycache__/ directory
  - .pytest_cache/

Removed with --logs:
  - all logs/*.log except the newest N per log family
    (same retention rule as etl/utils/runtime.py, default 5,
     override with --keep or IRIS_LOG_RETENTION)

Usage:
  python scripts/clean_workspace.py            # caches only
  python scripts/clean_workspace.py --logs     # caches + log retention
  python scripts/clean_workspace.py --logs --keep 1
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"

# Suffix appended to a log stem by etl/utils/runtime.py: _<YYYYMMDD_HHMMSS>.log
_RUN_ID_SUFFIX = re.compile(r"_\d{8}_\d{6}$")


def clean_caches() -> int:
    removed = 0
    for cache_dir in BASE_DIR.rglob("__pycache__"):
        if ".git" in cache_dir.parts:
            continue
        shutil.rmtree(cache_dir, ignore_errors=True)
        removed += 1
    pytest_cache = BASE_DIR / ".pytest_cache"
    if pytest_cache.exists():
        shutil.rmtree(pytest_cache, ignore_errors=True)
        removed += 1
    return removed


def clean_logs(keep: int) -> int:
    if not LOGS_DIR.exists():
        return 0
    families: dict[str, list[Path]] = defaultdict(list)
    for log in LOGS_DIR.glob("*.log"):
        family = _RUN_ID_SUFFIX.sub("", log.stem)
        families[family].append(log)
    removed = 0
    for logs in families.values():
        # Run IDs are UTC timestamps: filename order == chronological order.
        for old in sorted(logs)[:-keep] if keep > 0 else sorted(logs):
            old.unlink(missing_ok=True)
            removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge local runtime debris.")
    parser.add_argument(
        "--logs", action="store_true",
        help="Also apply log retention (keep newest N per log family).",
    )
    parser.add_argument(
        "--keep", type=int,
        default=int(os.environ.get("IRIS_LOG_RETENTION", 5)),
        help="Logs to keep per family when --logs is set (default 5).",
    )
    args = parser.parse_args()

    n_caches = clean_caches()
    print(f"cache directories removed : {n_caches}")
    if args.logs:
        n_logs = clean_logs(args.keep)
        print(f"old log files removed     : {n_logs} (kept newest {args.keep} per family)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
