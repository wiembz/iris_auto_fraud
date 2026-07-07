"""
etl/utils/runtime.py
====================
Shared runtime utilities for every pipeline layer (staging, dwh, mart,
preprocessing): logging and PostgreSQL engine construction.

Layer-specific helpers stay in their own modules (etl/dwh/dwh_utils.py,
etl/staging_area/sa_utils.py); this module only holds the pieces that were
previously copy-pasted between them.

Functions:
  setup_logging — UTF-8 file handler + console handler, parameterized namespace,
                  with automatic log retention (default: keep the 5 most recent
                  logs per log_name; override with IRIS_LOG_RETENTION)
  build_engine  — SQLAlchemy engine from .env (multi-encoding-safe parser)
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from sqlalchemy import URL, create_engine

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = BASE_DIR / "logs"

LOGS_DIR.mkdir(parents=True, exist_ok=True)

# How many log files to keep per log_name (the newest ones). Run IDs are
# UTC timestamps, so lexicographic filename order is chronological order.
DEFAULT_LOG_RETENTION = 5


def _prune_old_logs(log_name: str, keep: int) -> None:
    """Delete the oldest logs of this log_name family beyond `keep` files.

    Best-effort housekeeping: any error (locked file, permissions) is ignored
    so retention can never break a pipeline run.
    """
    try:
        candidates = sorted(LOGS_DIR.glob(f"{log_name}_*.log"))
        for old in candidates[:-keep] if keep > 0 else []:
            old.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging(
    run_id: str,
    log_name: str = "etl",
    namespace: str = "etl",
) -> logging.Logger:
    """Configure un logger avec handler fichier UTF-8 et handler console."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    log_file = LOGS_DIR / f"{log_name}_{run_id}.log"
    logger = logging.getLogger(f"{namespace}.{run_id}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)

    try:
        retention = int(os.environ.get("IRIS_LOG_RETENTION", DEFAULT_LOG_RETENTION))
    except ValueError:
        retention = DEFAULT_LOG_RETENTION
    _prune_old_logs(log_name, retention)

    logger.info(f"Logger initialise | run_id={run_id} | log={log_file}")
    return logger


# ---------------------------------------------------------------------------
# PostgreSQL connection
# ---------------------------------------------------------------------------
def _parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse .env file directly, trying UTF-8 then cp1252/latin-1."""
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            text = env_path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return {}
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        result[key] = val
    return result


def build_engine(logger: logging.Logger | None = None):
    """Charge .env et construit l'engine SQLAlchemy avec URL.create."""
    env_path = BASE_DIR / ".env"
    file_vars = _parse_env_file(env_path) if env_path.exists() else {}

    def _get(key: str, default: str = "") -> str:
        return file_vars.get(key) or os.environ.get(key, default)

    host = _get("DB_HOST", "localhost")
    port = int(_get("DB_PORT", "5432"))
    database = _get("DB_NAME")
    username = _get("DB_USER")
    password = _get("DB_PASSWORD")

    url = URL.create(
        drivername="postgresql+psycopg2",
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
    )
    engine = create_engine(url, pool_pre_ping=True)
    if logger:
        logger.info(f"Engine PostgreSQL : {host}:{port}/{database}")
    return engine
