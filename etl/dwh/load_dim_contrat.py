
"""
etl/dwh/load_dim_contrat.py
===========================
Charge staging.stg_production -> dwh.dim_contrat.

Grain      : une ligne par contrat unique
Cle metier : contrat_key = normalize_numcnt(NUMCNT)
ClÃ© tech   : contrat_sk, entier sÃ©quentiel gÃ©nÃ©rÃ© par le DWH

Important :
  Production contient souvent plusieurs lignes pour un mÃªme contrat :
    NUMCNT + NUMAVT + NUMMAJ

  Ici, dim_contrat garde une seule ligne par NUMCNT.
  On conserve l'avenant et la mise Ã  jour de rÃ©fÃ©rence les plus rÃ©cents
  disponibles pour dÃ©crire le contrat.

Usage :
  python etl/dwh/load_dim_contrat.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwh_utils


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
TABLE_NAME = "dim_contrat"
SOURCE_TABLE = "staging.stg_production"
SOURCE_SYSTEM = "BNA_ASSURANCES"
TODAY = datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Helpers gÃ©nÃ©riques
# ---------------------------------------------------------------------------
def _first_existing_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """
    Retourne le premier nom de colonne existant parmi les candidats.
    """
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _clean_code(value) -> str | None:
    """
    Nettoie un code ou identifiant.

    Exemples :
      501.0 -> '501'
      ' 005 ' -> '005'
      NaN -> None
    """
    if value is None or pd.isna(value):
        return None

    text = str(value).strip().upper()

    if text in {"", "NAN", "NONE", "NULL", "0", "0.0"}:
        return None

    try:
        number = float(text)
        if number.is_integer():
            return str(int(number))
    except ValueError:
        pass

    if text.endswith(".0"):
        text = text[:-2]

    return text if text else None


def _clean_text(value) -> str | None:
    """
    Nettoie un libellÃ© texte.
    """
    if value is None or pd.isna(value):
        return None

    text = str(value).strip().upper()

    if text in {"", "NAN", "NONE", "NULL", "UNKNOWN"}:
        return None

    text = " ".join(text.split())

    return text if text else None


def _to_numeric_sort(value) -> float:
    """
    Convertit un champ de tri en nombre.
    Les valeurs non numÃ©riques deviennent -1.
    """
    if value is None or pd.isna(value):
        return -1

    try:
        return float(str(value).strip())
    except ValueError:
        return -1


def _parse_date_series(series: pd.Series | None, index) -> pd.Series:
    """
    Parse une sÃ©rie date avec robustesse.
    """
    if series is None:
        return pd.Series(pd.NaT, index=index)

    return pd.to_datetime(series, errors="coerce", dayfirst=True)


# ---------------------------------------------------------------------------
# Construction des colonnes mÃ©tier
# ---------------------------------------------------------------------------
def _build_numero_contrat(df: pd.DataFrame) -> pd.Series:
    col = _first_existing_col(
        df,
        [
            "numcnt",
            "NUMCNT",
            "numcnt_norm",
            "numero_contrat",
            "contrat",
        ],
    )

    if col is None:
        return pd.Series(pd.NA, index=df.index, dtype=object)

    return df[col].map(dwh_utils.normalize_numcnt)


def _build_numero_avenant(df: pd.DataFrame) -> pd.Series:
    col = _first_existing_col(
        df,
        [
            "numavt_norm",
            "numavt",
            "NUMAVT",
            "numero_avenant",
        ],
    )

    if col is None:
        return pd.Series(pd.NA, index=df.index, dtype=object)

    return df[col].map(_clean_code)


def _build_numero_maj(df: pd.DataFrame) -> pd.Series:
    col = _first_existing_col(
        df,
        [
            "nummaj_norm",
            "nummaj",
            "NUMMAJ",
            "numero_maj",
            "numero_mise_a_jour",
        ],
    )

    if col is None:
        return pd.Series(pd.NA, index=df.index, dtype=object)

    return df[col].map(_clean_code)


def _build_code_produit(df: pd.DataFrame) -> pd.Series:
    col = _first_existing_col(
        df,
        [
            "codprod_norm",
            "codprod",
            "CODPROD",
            "code_produit",
        ],
    )

    if col is None:
        return pd.Series(pd.NA, index=df.index, dtype=object)

    return df[col].map(_clean_code)


def _build_libelle_produit(df: pd.DataFrame) -> pd.Series:
    col = _first_existing_col(
        df,
        [
            "product_label",
            "libelle_produit",
            "libprod",
            "libprdt",
            "produit_label",
        ],
    )

    if col is None:
        return pd.Series("NON RENSEIGNÃ‰", index=df.index, dtype=object)

    cleaned = df[col].map(_clean_text)

    return cleaned.fillna("NON RENSEIGNÃ‰")


def _build_idclt(df: pd.DataFrame) -> pd.Series:
    """
    Construit la clÃ© mÃ©tier client liÃ©e au contrat.

    Elle est gardÃ©e comme clÃ© mÃ©tier de rattachement.
    La jointure avec dim_client se fera plus tard dans les facts.
    """
    col = _first_existing_col(
        df,
        [
            "client_key",
            "idclt",
            "id_client",
        ],
    )

    if col is not None:
        return df[col].map(_clean_code)

    cnat_col = _first_existing_col(df, ["cnat_norm", "cnat", "CNAT"])
    numpers_col = _first_existing_col(df, ["numpers_norm", "numpers", "NUMPERS"])

    if cnat_col is None or numpers_col is None:
        return pd.Series(pd.NA, index=df.index, dtype=object)

    cnat = df[cnat_col].map(_clean_code).fillna("")
    numpers = df[numpers_col].map(_clean_code).fillna("")

    key = cnat + "|" + numpers

    return key.where((cnat != "") | (numpers != ""))


def _build_code_intermediaire(df: pd.DataFrame) -> pd.Series:
    """
    Construit la clÃ© mÃ©tier intermÃ©diaire liÃ©e au contrat.

    code_intermediaire = NATINT|IDINT
    """
    nat_col = _first_existing_col(
        df,
        [
            "natint_norm",
            "natint",
            "NATINT",
            "nature_intermediaire",
        ],
    )

    id_col = _first_existing_col(
        df,
        [
            "idint_norm",
            "idint",
            "IDINT",
            "id_intermediaire",
        ],
    )

    if nat_col is None or id_col is None:
        return pd.Series(pd.NA, index=df.index, dtype=object)

    nat = df[nat_col].map(_clean_code).fillna("")
    iid = df[id_col].map(_clean_code).fillna("")

    key = nat + "|" + iid

    return key.where((nat != "") & (iid != ""))


def _build_date_debut_contrat(df: pd.DataFrame) -> pd.Series:
    col = _first_existing_col(
        df,
        [
            "debcnt",
            "DEBCNT",
            "date_debut_contrat",
            "date_debut",
            "debut_contrat",
        ],
    )

    if col is None:
        return pd.Series(pd.NaT, index=df.index)

    return _parse_date_series(df[col], df.index)


def _build_date_fin_contrat(df: pd.DataFrame) -> pd.Series:
    col = _first_existing_col(
        df,
        [
            "fincnt",
            "FINCNT",
            "date_fin_contrat",
            "date_fin",
            "fin_contrat",
            "date_echeance",
        ],
    )

    if col is None:
        return pd.Series(pd.NaT, index=df.index)

    return _parse_date_series(df[col], df.index)


def _build_date_debut_effet(df: pd.DataFrame) -> pd.Series:
    col = _first_existing_col(
        df,
        [
            "debeffet",
            "DEBEFFET",
            "date_debut_effet",
            "date_effet",
        ],
    )

    if col is None:
        return pd.Series(pd.NaT, index=df.index)

    return _parse_date_series(df[col], df.index)


def _build_date_fin_effet(df: pd.DataFrame) -> pd.Series:
    col = _first_existing_col(
        df,
        [
            "fineffet",
            "FINEFFET",
            "date_fin_effet",
            "date_fin_effet_contrat",
        ],
    )

    if col is None:
        return pd.Series(pd.NaT, index=df.index)

    return _parse_date_series(df[col], df.index)


def _build_date_derniere_operation(df: pd.DataFrame) -> pd.Series:
    col = _first_existing_col(
        df,
        [
            "dateprec",
            "DATEPREC",
            "date_derniere_operation",
            "date_mouvement",
        ],
    )

    if col is None:
        return pd.Series(pd.NaT, index=df.index)

    return _parse_date_series(df[col], df.index)


def _build_statut_contrat(df: pd.DataFrame) -> pd.Series:
    """
    Construit un statut mÃ©tier simple du contrat.

    PrioritÃ© :
      1. rÃ©siliation explicite via typeresil / lib_resil
      2. situation source situat
      3. date_fin_contrat
      4. UNKNOWN
    """
    result = pd.Series("UNKNOWN", index=df.index, dtype=object)

    # 1. RÃ©siliation explicite
    typeresil_col = _first_existing_col(df, ["typeresil", "TYPERESIL"])
    lib_resil_col = _first_existing_col(df, ["lib_resil", "LIB_RESIL"])

    if typeresil_col is not None:
        typeresil = df[typeresil_col].map(_clean_code)
        result[typeresil.notna()] = "RESILIE"

    if lib_resil_col is not None:
        lib_resil = df[lib_resil_col].map(_clean_text)
        result[lib_resil.notna()] = "RESILIE"

    # 2. Situation source
    situat_col = _first_existing_col(df, ["situat", "SITUAT", "statut", "etat"])

    if situat_col is not None:
        situat = df[situat_col].map(_clean_code)

        mapping_situat = {
            "A": "ACTIF",       "ACTIF": "ACTIF",
            "V": "ACTIF",       "VALIDE": "ACTIF",
            "E": "EXPIRE",      "EXPIRE": "EXPIRE",
            "R": "RESILIE",     "RESILIE": "RESILIE",
            "S": "SUSPENDU",    "SUSPENDU": "SUSPENDU",
        }

        mapped = situat.map(mapping_situat)
        mask_unknown = result.eq("UNKNOWN")
        result[mask_unknown & mapped.notna()] = mapped[mask_unknown & mapped.notna()]

    # 3. Fallback date fin
    date_fin = _build_date_fin_contrat(df)
    today = pd.Timestamp(TODAY.date())

    mask_unknown = result.eq("UNKNOWN")
    result[mask_unknown & date_fin.notna() & (date_fin >= today)] = "ACTIF"
    result[mask_unknown & date_fin.notna() & (date_fin < today)] = "EXPIRE"

    return result


def _build_type_resiliation(df: pd.DataFrame) -> pd.Series:
    col = _first_existing_col(df, ["typeresil", "TYPERESIL", "type_resiliation"])
    if col is None:
        return pd.Series(pd.NA, index=df.index, dtype=object)
    return df[col].map(_clean_code)


def _build_libelle_resiliation(df: pd.DataFrame) -> pd.Series:
    col = _first_existing_col(df, ["lib_resil", "LIB_RESIL", "libelle_resiliation"])
    if col is None:
        return pd.Series(pd.NA, index=df.index, dtype=object)
    return df[col].map(_clean_text)


# ---------------------------------------------------------------------------
# Transformation
# ---------------------------------------------------------------------------
def transform_dim_contrat(
    df_raw: pd.DataFrame,
    logger,
) -> tuple[pd.DataFrame, dict]:
    """
    Transforme staging.stg_production en dwh.dim_contrat.
    """
    n_raw = len(df_raw)

    logger.info(f"  Lignes lues depuis {SOURCE_TABLE} : {n_raw}")

    df = df_raw.copy()

    # ------------------------------------------------------------------
    # 1. Construction des colonnes mÃ©tier
    # ------------------------------------------------------------------
    logger.info("  [STEP] Construction clÃ©s contrat")

    df["numero_contrat"] = _build_numero_contrat(df)
    df["contrat_key"] = df["numero_contrat"]
    df["numero_avenant_ref"] = _build_numero_avenant(df)
    df["numero_maj_ref"] = _build_numero_maj(df)

    df["code_produit"] = _build_code_produit(df)
    df["libelle_produit"] = _build_libelle_produit(df)

    df["idclt"] = _build_idclt(df)
    df["code_intermediaire"] = _build_code_intermediaire(df)

    logger.info("  [STEP] Construction dates et statut contrat")

    df["date_debut_contrat"] = _build_date_debut_contrat(df)
    df["date_fin_contrat"] = _build_date_fin_contrat(df)
    df["date_debut_effet"] = _build_date_debut_effet(df)
    df["date_fin_effet"] = _build_date_fin_effet(df)
    df["date_derniere_operation"] = _build_date_derniere_operation(df)
    df["statut_contrat"] = _build_statut_contrat(df)
    df["type_resiliation"] = _build_type_resiliation(df)
    df["libelle_resiliation"] = _build_libelle_resiliation(df)

    # ------------------------------------------------------------------
    # 2. Suppression lignes sans clÃ© contrat
    # ------------------------------------------------------------------
    n_before_key_filter = len(df)

    df = df[df["contrat_key"].notna()].copy()

    n_null_key = n_before_key_filter - len(df)

    if n_null_key:
        logger.warning(f"  Lignes sans numero_contrat supprimÃ©es : {n_null_key}")

    # ------------------------------------------------------------------
    # 3. Controle perimetre automobile sans exclusion
    # ------------------------------------------------------------------
    logger.info("  [STEP] Controle perimetre automobile sans exclusion")

    mask_auto = df["code_produit"].notna() & df["code_produit"].astype(str).str.startswith("5", na=False)
    n_hors_auto = int((~mask_auto).sum())

    if n_hors_auto:
        logger.info(
            "  Contrats production hors code produit 5xx conserves pour couverture fact_sinistre : "
            f"{n_hors_auto}"
        )

    # ------------------------------------------------------------------
    # 4. Choix de la ligne de reference par contrat
    # ------------------------------------------------------------------
    logger.info("  [STEP] DÃ©duplication contrats")

    n_before_dedup = len(df)

    df["_numavt_sort"] = df["numero_avenant_ref"].map(_to_numeric_sort)
    df["_nummaj_sort"] = df["numero_maj_ref"].map(_to_numeric_sort)

    # Score de complÃ©tude uniquement sur les colonnes utiles.
    completeness_cols = [
        "contrat_key",
        "numero_contrat",
        "numero_avenant_ref",
        "numero_maj_ref",
        "code_produit",
        "libelle_produit",
        "idclt",
        "code_intermediaire",
        "date_debut_contrat",
        "date_fin_contrat",
        "date_debut_effet",
        "date_fin_effet",
        "date_derniere_operation",
        "statut_contrat",
    ]

    df["_completeness"] = df[completeness_cols].notna().sum(axis=1)

    # RÃ¨gle :
    #   Pour un mÃªme NUMCNT, garder la version la plus rÃ©cente :
    #     NUMAVT max, puis NUMMAJ max, puis ligne la plus complÃ¨te.
    df = (
        df.sort_values(
            by=[
                "contrat_key",
                "_numavt_sort",
                "_nummaj_sort",
                "_completeness",
            ],
            ascending=[True, False, False, False],
        )
        .drop_duplicates(subset=["contrat_key"], keep="first")
        .drop(columns=["_numavt_sort", "_nummaj_sort", "_completeness"])
        .reset_index(drop=True)
    )

    n_dupes = n_before_dedup - len(df)

    logger.info(f"  Contrats distincts chargÃ©s : {len(df)}")
    logger.info(f"  Doublons / versions supprimÃ©s : {n_dupes}")

    # ------------------------------------------------------------------
    # 5. Colonnes techniques
    # ------------------------------------------------------------------
    df["source_system"] = SOURCE_SYSTEM
    df["created_at"] = TODAY

    # ------------------------------------------------------------------
    # 6. ClÃ© substitut
    # ------------------------------------------------------------------
    df.insert(0, "contrat_sk", range(1, len(df) + 1))

    # ------------------------------------------------------------------
    # 7. Colonnes finales
    # ------------------------------------------------------------------
    final_cols = [
        "contrat_sk",
        "contrat_key",
        "numero_contrat",
        "date_debut_contrat",
        "date_fin_contrat",
        "date_debut_effet",
        "date_fin_effet",
        "statut_contrat",
        "type_resiliation",
        "libelle_resiliation",
        "source_system",
        "created_at",
    ]

    for col in final_cols:
        if col not in df.columns:
            df[col] = None

    df_final = df[final_cols].copy()

    unknown_row = pd.DataFrame([{"contrat_sk": 0, "contrat_key": "UNKNOWN", "numero_contrat": "UNKNOWN", "date_debut_contrat": pd.NaT, "date_fin_contrat": pd.NaT, "date_debut_effet": pd.NaT, "date_fin_effet": pd.NaT, "statut_contrat": "UNKNOWN", "type_resiliation": "UNKNOWN", "libelle_resiliation": "UNKNOWN", "source_system": SOURCE_SYSTEM, "created_at": TODAY}])
    df_final = pd.concat([unknown_row, df_final], ignore_index=True)

    # ------------------------------------------------------------------
    # 8. MÃ©triques DQ
    # ------------------------------------------------------------------
    n_date_debut_null = int(df_final["date_debut_contrat"].isna().sum())
    n_date_fin_null = int(df_final["date_fin_contrat"].isna().sum())
    n_date_debut_effet_null = int(df_final["date_debut_effet"].isna().sum())
    n_date_fin_effet_null = int(df_final["date_fin_effet"].isna().sum())
    n_statut_unknown = int((df_final["statut_contrat"] == "UNKNOWN").sum())
    n_type_resil_null = int(df_final["type_resiliation"].isna().sum())

    top_statuts = (
        df_final["statut_contrat"]
        .value_counts(dropna=False)
        .head(20)
        .to_dict()
    )

    metrics = {
        "n_raw": n_raw,
        "n_null_key": n_null_key,
        "n_hors_auto": n_hors_auto,
        "n_dupes": n_dupes,
        "n_loaded": len(df_final),
        "n_date_debut_null": n_date_debut_null,
        "n_date_fin_null": n_date_fin_null,
        "n_date_debut_effet_null": n_date_debut_effet_null,
        "n_date_fin_effet_null": n_date_fin_effet_null,
        "n_statut_unknown": n_statut_unknown,
        "n_type_resil_null": n_type_resil_null,
        "top_statuts": top_statuts,
    }

    return df_final, metrics


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------
def load_dim_contrat(run_id: str, engine, logger) -> dict:
    """
    Lit staging.stg_production, transforme et charge dwh.dim_contrat.
    """
    logger.info(f"[READ] {SOURCE_TABLE}")

    query = """
        SELECT *
        FROM staging.stg_production
    """

    df_raw = pd.read_sql(query, engine)

    df_final, metrics = transform_dim_contrat(df_raw, logger)

    logger.info("  [STEP] Chargement PostgreSQL dwh.dim_contrat")

    _, elapsed = dwh_utils.write_to_dwh(
        df_final,
        engine,
        TABLE_NAME,
        logger,
    )

    metrics["elapsed"] = elapsed

    return metrics


# ---------------------------------------------------------------------------
# Point d'entrÃ©e
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    logger = dwh_utils.setup_logging(run_id, log_name="load_dim_contrat")
    engine = dwh_utils.build_engine(logger)

    dwh_utils.create_dwh_schema(engine, logger)

    m = load_dim_contrat(run_id, engine, logger)

    logger.info("=" * 60)
    logger.info("dwh.dim_contrat chargÃ©e avec succÃ¨s")
    logger.info(f"  lignes staging lues              : {m['n_raw']}")
    logger.info(f"  contrats chargÃ©s DWH             : {m['n_loaded']}")
    logger.info(f"  lignes sans numero_contrat       : {m['n_null_key']}")
    logger.info(f"  contrats hors code produit 5xx conserves : {m['n_hors_auto']}")
    logger.info(f"  doublons / versions supprimÃ©s    : {m['n_dupes']}")

    logger.info("  -- qualitÃ© des attributs --")
    logger.info(f"  date_debut_contrat NULL          : {m['n_date_debut_null']}")
    logger.info(f"  date_fin_contrat NULL            : {m['n_date_fin_null']}")
    logger.info(f"  date_debut_effet NULL            : {m['n_date_debut_effet_null']}")
    logger.info(f"  date_fin_effet NULL              : {m['n_date_fin_effet_null']}")
    logger.info(f"  statut_contrat UNKNOWN           : {m['n_statut_unknown']}")
    logger.info(f"  type_resiliation NULL            : {m['n_type_resil_null']}")

    if m["top_statuts"]:
        logger.info("  -- statuts contrat --")
        for statut, count in m["top_statuts"].items():
            logger.info(f"    {statut} : {count}")

    logger.info(f"  durÃ©e                            : {m['elapsed']:.1f}s")
    logger.info("=" * 60)




