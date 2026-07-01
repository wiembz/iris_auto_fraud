"""
etl/staging_area/sa_utils.py
============================
Utilitaires communs pour le chargement Staging Area PostgreSQL.

Fonctions :
  setup_logging        — logger fichier UTF-8 + console
  build_engine         — SQLAlchemy engine via URL.create + .env
  create_schemas       — CREATE SCHEMA IF NOT EXISTS staging / audit
  normalize_column_name — nettoyage nom de colonne PostgreSQL-compatible
  make_unique_columns  — deduplication apres normalisation
  standardize_df_columns — applique make_unique_columns sur un DataFrame
  add_technical_columns  — sa_load_run_id / sa_loaded_at / sa_source_file
  write_to_postgres    — to_sql mode replace avec chunksize
  write_audit_row      — INSERT dans audit.etl_table_load
"""
from __future__ import annotations

import logging
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, text

# ---------------------------------------------------------------------------
# Chemins projet
# ---------------------------------------------------------------------------
BASE_DIR  = Path(__file__).resolve().parent.parent.parent
LOGS_DIR  = BASE_DIR / "logs"
DATA_PROC = BASE_DIR / "data" / "processed"

LOGS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging(run_id: str, log_name: str = "load_all_sa") -> logging.Logger:
    """Configure un logger avec handler fichier UTF-8 et handler console."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    log_file = LOGS_DIR / f"{log_name}_{run_id}.log"
    logger = logging.getLogger(f"sa.{run_id}")
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
def build_engine(logger: logging.Logger | None = None):
    """Charge .env et construit l'engine SQLAlchemy avec URL.create."""
    load_dotenv(BASE_DIR / ".env", encoding="utf-8")
    url = URL.create(
        drivername="postgresql+psycopg2",
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        database=os.environ["DB_NAME"],
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
    engine = create_engine(url, pool_pre_ping=True)
    if logger:
        logger.info(
            f"Engine PostgreSQL : {os.environ['DB_HOST']}:"
            f"{os.environ.get('DB_PORT', 5432)}/{os.environ['DB_NAME']}"
        )
    return engine


def create_schemas(engine, logger: logging.Logger | None = None) -> None:
    """
    Cree les schemas staging et audit si absents, puis recrée
    audit.etl_table_load avec la structure attendue (DROP + CREATE).
    """
    with engine.begin() as conn:
        for schema in ("staging", "audit"):
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
            if logger:
                logger.info(f"Schema '{schema}' : OK")
        # Recréation propre de la table d'audit (phase développement)
        conn.execute(text("DROP TABLE IF EXISTS audit.etl_table_load"))
        conn.execute(text("""
            CREATE TABLE audit.etl_table_load (
                audit_id        BIGSERIAL PRIMARY KEY,
                run_id          TEXT        NOT NULL,
                table_name      TEXT        NOT NULL,
                source_file     TEXT,
                n_rows          BIGINT,
                n_cols          BIGINT,
                elapsed_seconds NUMERIC,
                loaded_at       TIMESTAMP   DEFAULT NOW(),
                status          TEXT,
                error_msg       TEXT
            )
        """))
        if logger:
            logger.info("audit.etl_table_load : recreee (DROP + CREATE)")


# ---------------------------------------------------------------------------
# Normalisation noms de colonnes
# ---------------------------------------------------------------------------
def normalize_column_name(col: str, max_len: int = 55) -> str:
    """
    Nettoyage PostgreSQL-compatible :
    lowercase, sans accents, car. speciaux -> '_', tronque a max_len.
    """
    col = str(col).strip()
    col = unicodedata.normalize("NFKD", col)
    col = "".join(c for c in col if not unicodedata.combining(c))
    col = col.lower()
    col = re.sub(r"[^a-z0-9]+", "_", col)
    col = re.sub(r"_+", "_", col).strip("_")
    return (col or "col")[:max_len]


def make_unique_columns(columns: list[str], max_len: int = 55) -> list[str]:
    """Normalise et deduplique une liste de noms de colonnes."""
    seen: dict[str, int] = {}
    result: list[str] = []
    for original in columns:
        base = normalize_column_name(str(original), max_len=max_len)
        candidate = base
        if candidate in seen:
            seen[candidate] += 1
            suffix = f"_{seen[candidate]}"
            candidate = f"{base[:max_len - len(suffix)]}{suffix}"
        else:
            seen[candidate] = 0
        result.append(candidate)
    return result


def standardize_df_columns(
    df: pd.DataFrame,
    table_name: str,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """
    Applique make_unique_columns sur une copie du DataFrame.
    Leve ValueError si des doublons subsistent apres normalisation.
    """
    original_cols = list(df.columns)
    new_cols = make_unique_columns(original_cols)
    df = df.copy()
    df.columns = new_cols
    changed = sum(a != b for a, b in zip(original_cols, new_cols))
    if changed and logger:
        logger.info(f"{table_name} : {changed} colonnes renommees pour compatibilite PostgreSQL")
    dups = [c for c in new_cols if new_cols.count(c) > 1]
    if dups:
        raise ValueError(
            f"Colonnes dupliquees apres standardisation dans {table_name} : {set(dups)}"
        )
    return df


# ---------------------------------------------------------------------------
# Colonnes techniques
# ---------------------------------------------------------------------------
def add_technical_columns(
    df: pd.DataFrame,
    source_file: str,
    run_id: str,
) -> pd.DataFrame:
    """Ajoute les colonnes de tracabilite sur une copie du DataFrame."""
    df = df.copy()
    df["sa_load_run_id"] = run_id
    df["sa_loaded_at"]   = datetime.now(timezone.utc).isoformat()
    df["sa_source_file"] = source_file
    return df


# ---------------------------------------------------------------------------
# Chargement PostgreSQL
# ---------------------------------------------------------------------------
def write_to_postgres(
    df: pd.DataFrame,
    engine,
    schema: str,
    table_name: str,
    logger: logging.Logger,
    chunksize: int = 5000,
) -> tuple[int, float]:
    """
    Charge df dans schema.table_name (mode replace).
    Retourne (n_rows, elapsed_seconds).
    """
    full_name = f"{schema}.{table_name}"
    df_pg = standardize_df_columns(df, full_name, logger)
    t0 = datetime.now(timezone.utc)
    df_pg.to_sql(
        table_name,
        engine,
        schema=schema,
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=chunksize,
    )
    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    n = len(df_pg)
    logger.info(
        f"[LOAD] {full_name} : {n} lignes x {df_pg.shape[1]} cols "
        f"en {elapsed:.1f}s"
    )
    return n, elapsed


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
_AUDIT_INSERT = text("""
    INSERT INTO audit.etl_table_load
        (run_id, table_name, source_file, n_rows, n_cols,
         elapsed_seconds, loaded_at, status, error_msg)
    VALUES
        (:run_id, :table_name, :source_file, :n_rows, :n_cols,
         :elapsed, NOW(), :status, :error_msg)
""")


def write_audit_row(
    engine,
    run_id: str,
    table_name: str,
    source_file: str,
    n_rows: int,
    n_cols: int,
    elapsed: float,
    status: str,
    logger: logging.Logger,
    error_msg: str | None = None,
) -> None:
    """
    Insere une ligne de tracabilite dans audit.etl_table_load.
    La table est garantie d'exister apres create_schemas().
    """
    try:
        with engine.begin() as conn:
            conn.execute(_AUDIT_INSERT, {
                "run_id":      run_id,
                "table_name":  table_name,
                "source_file": source_file,
                "n_rows":      n_rows,
                "n_cols":      n_cols,
                "elapsed":     round(elapsed, 2),
                "status":      status,
                "error_msg":   error_msg,
            })
        logger.info(f"[AUDIT] {table_name} -> audit.etl_table_load OK")
    except Exception as exc:
        logger.warning(f"[AUDIT] Echec ecriture audit pour {table_name} : {exc}")
