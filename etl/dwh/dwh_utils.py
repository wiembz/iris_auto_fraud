"""
etl/dwh/dwh_utils.py
=====================
Utilitaires communs pour le chargement Data Warehouse PostgreSQL.

Fonctions :
  setup_logging    â€” logger fichier UTF-8 + console
  build_engine     â€” SQLAlchemy engine via URL.create + .env
  create_dwh_schema â€” CREATE SCHEMA IF NOT EXISTS dwh
  write_to_dwh     â€” to_sql mode replace avec chunksize
"""
from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import URL, create_engine, text

# ---------------------------------------------------------------------------
# Chemins projet
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = BASE_DIR / "logs"

LOGS_DIR.mkdir(parents=True, exist_ok=True)



# ---------------------------------------------------------------------------
# Shared business-key normalization
# ---------------------------------------------------------------------------
def normalize_numcnt(value) -> str | None:
    """
    Normalize contract identifiers without destroying business information.

    Rules:
    - preserve identifiers as strings;
    - trim and uppercase;
    - remove Excel numeric artifacts only when safe, e.g. 123.0 -> 123;
    - preserve historical slash formats such as 20161.0000002/1;
    - return None for empty / NULL / NAN / UNKNOWN-like values.
    """
    if value is None or pd.isna(value):
        return None

    text = str(value).strip().upper()
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*/\s*", "/", text)

    invalid = {
        "",
        "NULL",
        "NAN",
        "NONE",
        "UNKNOWN",
        "INCONNU",
        "INCONNUE",
        "NON RENSEIGNE",
        "NON RENSEIGNEE",
        "N/A",
        "NA",
        "#N/A",
        "0",
        "0.0",
        "0,0",
    }
    if text in invalid:
        return None

    # Numeric Python/Excel values are safe to shorten only when truly integral.
    if not isinstance(value, str):
        try:
            number = float(value)
            if number.is_integer():
                return str(int(number))
        except (TypeError, ValueError):
            pass

    # Safe textual Excel artifacts: 123.0 / 123,0 / 123.000 -> 123.
    # Do not apply to slash-based or non-zero decimal identifiers.
    if "/" not in text:
        match = re.fullmatch(r"([A-Z0-9]+)[\.,]0+", text)
        if match:
            return match.group(1)

    return text or None
# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging(run_id: str, log_name: str = "load_dwh") -> logging.Logger:
    """Configure un logger avec handler fichier UTF-8 et handler console."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    log_file = LOGS_DIR / f"{log_name}_{run_id}.log"
    logger = logging.getLogger(f"dwh.{run_id}")
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

    logger.info(f"Logger initialise | run_id={run_id} | log={log_file}")
    return logger


# ---------------------------------------------------------------------------
# Connexion PostgreSQL
# ---------------------------------------------------------------------------
def _parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse .env file directly, trying UTF-8 then latin-1/cp1252."""
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


# ---------------------------------------------------------------------------
# Schema DWH
# ---------------------------------------------------------------------------
def create_dwh_schema(engine, logger: logging.Logger | None = None) -> None:
    """Cree le schema dwh s'il n'existe pas."""
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS dwh"))
    if logger:
        logger.info("Schema 'dwh' : OK")


# ---------------------------------------------------------------------------
# Chargement PostgreSQL
# ---------------------------------------------------------------------------
def write_to_dwh(
    df: pd.DataFrame,
    engine,
    table_name: str,
    logger: logging.Logger,
    chunksize: int = 5000,
) -> tuple[int, float]:
    """
    Charge df dans dwh.<table_name> en mode replace.
    Retourne (n_rows, elapsed_seconds).
    """
    full_name = f"dwh.{table_name}"
    t0 = datetime.now(timezone.utc)
    df.to_sql(
        table_name,
        engine,
        schema="dwh",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=chunksize,
    )
    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    n = len(df)
    logger.info(
        f"[LOAD] {full_name} : {n} lignes x {df.shape[1]} cols en {elapsed:.1f}s"
    )
    return n, elapsed


