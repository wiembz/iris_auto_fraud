"""
etl/dwh/load_fact_sinistre.py
==============================
Build dwh.fact_sinistre from staging.stg_sinistres.

Grain: one row per NUMSNT + GRNTSINI.
Business key: sinistre_garantie_key = NUMSNT || '|' || GRNTSINI.

This loader does not add fraud scoring or AI logic. It only builds the central
claim-guarantee fact table with clean foreign keys, dates, measures and simple
business indicators.
"""
from __future__ import annotations

import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwh_utils
import load_dim_geo

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TABLE_NAME = "fact_sinistre"
SOURCE_TABLE = "staging.stg_sinistres"
SOURCE_SYSTEM = "BNA_ASSURANCES"
TODAY = datetime.now(timezone.utc).replace(tzinfo=None)

REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "fact_sinistre"
UNMATCHED_DIMS_PATH = REPORT_DIR / "fact_sinistre_unmatched_dimensions.csv"
UNMATCHED_CONTRATS_PATH = REPORT_DIR / "fact_sinistre_unmatched_contrats.csv"
DATE_ANOMALIES_PATH = REPORT_DIR / "fact_sinistre_date_anomalies.csv"
DUPLICATE_GRAIN_PATH = REPORT_DIR / "fact_sinistre_duplicate_grain.csv"
AMOUNT_ANOMALIES_PATH = REPORT_DIR / "fact_sinistre_amount_anomalies.csv"
LOAD_SUMMARY_PATH = REPORT_DIR / "fact_sinistre_load_summary.csv"
GEO_MAPPING_PATH = BASE_DIR / "data" / "quality_reports" / "dim_geo" / "dim_geo_source_to_resolved_mapping.csv"

FINAL_COLS = [
    "fact_sinistre_sk", "numero_sinistre", "code_garantie", "sinistre_garantie_key",
    "sinistre_sk", "garantie_sk", "client_sk", "contrat_sk", "vehicule_sk",
    "conducteur_sk", "tiers_sk", "camtier_sk", "geo_sinistre_sk",
    "date_survenance_sk", "date_declaration_sk", "date_ouverture_sk", "date_cloture_sk",
    "montant_evaluation", "montant_reglement", "montant_reserve", "montant_recours",
    "montant_charge_sinistre", "delai_survenance_declaration_jours",
    "delai_declaration_ouverture_jours", "delai_ouverture_cloture_jours",
    "est_cloture", "est_corporel", "est_materiel", "est_ida", "est_transaction",
    "est_forcage", "est_coassurance", "est_reassurance",
    "motif_cloture_garantie", "etat_garantie_sinistre", "source_system", "created_at",
]

SOURCE_COLUMNS = [
    "numsnt", "numsnt_norm", "grntsini", "grntsini_norm", "codprod", "codprod_from_contract",
    "idclt", "numcnt", "numcnt_norm", "immat", "nomconduc", "datnaicon", "numpermis",
    "categperm", "datepermi", "nomtiers", "imvehtier", "numcnttie", "numsnttie",
    "natcamtie", "idcamtier", "regsini", "gouvsini", "citesini", "cpostsini",
    "dtsurv", "dtdecsnt", "dtouvsnt", "dtcltsnt", "eval_init", "mntpaigrn",
    "mntprovis", "mntrecour", "mnttotal", "code_etat", "natsini", "cas_ida",
    "ddetransa", "indforcag", "coassur", "reassur", "motifclot", "etatgrnt",
]

INVALID_TEXT = frozenset({"", "NULL", "NAN", "NONE", "UNKNOWN", "INCONNU", "INCONNUE", "NON RENSEIGNE", "NON RENSEIGNEE", "N/A", "NA", "#N/A", "ND", "NR", "/", "-", "--", "---", ".", ".."})
OUI_VALUES = frozenset({"O", "OUI", "YES", "Y", "TRUE", "1", "S", "SI", "R"})
NON_VALUES = frozenset({"N", "NON", "NO", "FALSE", "0"})
CIVILITES = re.compile(r"^\s*(MR\.?|M\.?|MME\.?|MONSIEUR|MADAME|DR\.?|DOCTEUR|STE\.?|SA\b|SARL\b)\s+", re.IGNORECASE)
INVALID_NOM_TIERS = INVALID_TEXT | frozenset({"SANS TIERS", "PAS DE TIERS", "NEANT", "SANS", "AUCUN", "AUCUNE", "DERAPAGE", "DIVERS CHOCS", "BRIS DE GLASS", "BG", "B.G"})
INVALID_IMMAT_TIERS = INVALID_TEXT | frozenset({"0", "00", "000", "0000", "00000", "000000", "SANS TIERS", "PAS DE TIERS", "NEANT", "INCONNU", "NON RENSEIGNE", "#", "#MOBYLETTE", "#PIETON", "MOBYLETTE", "PIETON", "NON ASSURE"})
INVALID_ID = INVALID_TEXT | frozenset({"NF", "NF.", "N", "N.D", "RAS", "0", "00", "0000", "00000", "000000"})
VALID_CAMTIER_NATURE = re.compile(r"^[A-Z]{2,3}$")
VALID_CAMTIER_ID = re.compile(r"^[0-9]+$")


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value)


def _clean_code(value: object) -> str | None:
    if _is_missing(value):
        return None
    s = str(value).strip().upper()
    if s in INVALID_TEXT or s in {"0", "0.0"}:
        return None
    try:
        number = float(s)
        if number.is_integer():
            return str(int(number))
    except ValueError:
        pass
    if s.endswith(".0"):
        s = s[:-2]
    return s if s and s not in INVALID_TEXT else None


def _clean_text(value: object) -> str | None:
    if _is_missing(value):
        return None
    s = re.sub(r"\s+", " ", str(value).strip()).upper()
    return None if s in INVALID_TEXT else s


def _clean_nom(value: object) -> str | None:
    if _is_missing(value):
        return None
    s = CIVILITES.sub("", str(value).strip())
    s = re.sub(r"\s+", " ", s).strip().upper()
    return None if s in INVALID_TEXT else s


def _clean_nom_tiers(value: object) -> str | None:
    s = _clean_nom(value)
    return None if s in INVALID_NOM_TIERS else s


def _clean_immat(value: object) -> str | None:
    if _is_missing(value):
        return None
    s = re.sub(r"\s+", "", str(value).strip()).upper()
    return None if s in INVALID_TEXT or s in {"0", "00", "0000"} else s


def _clean_immat_tiers(value: object) -> str | None:
    s = _clean_immat(value)
    return None if s in INVALID_IMMAT_TIERS else s


def _clean_id(value: object) -> str | None:
    s = _clean_code(value)
    return None if s in INVALID_ID else s


def _clean_camtier_nature(value: object) -> str | None:
    s = _clean_text(value)
    return s if s and VALID_CAMTIER_NATURE.match(s) else None


def _clean_camtier_id(value: object) -> str | None:
    s = _clean_code(value)
    return s if s and VALID_CAMTIER_ID.match(s) else None


def _parse_date(value: object) -> pd.Timestamp | pd.NaT:
    if _is_missing(value):
        return pd.NaT
    return pd.to_datetime(value, errors="coerce", dayfirst=True)


def _date_part(value: object) -> str | None:
    ts = _parse_date(value)
    return None if pd.isna(ts) else pd.Timestamp(ts).strftime("%Y-%m-%d")


def _join_key(parts: list[object]) -> str | None:
    cleaned = []
    for value in parts:
        if _is_missing(value):
            cleaned.append("#")
        else:
            s = str(value).strip().upper()
            cleaned.append(s if s and s not in INVALID_TEXT else "#")
    return None if all(part == "#" for part in cleaned) else "|".join(cleaned)


def _series_key(parts: list[pd.Series]) -> pd.Series:
    frame = pd.concat([part.astype("object") for part in parts], axis=1)
    frame = frame.where(frame.notna(), "#")
    for col in frame.columns:
        frame[col] = frame[col].astype(str).str.strip().str.upper()
        frame[col] = frame[col].where(~frame[col].isin(INVALID_TEXT), "#")
        frame[col] = frame[col].where(frame[col].str.len() > 0, "#")
    keys = frame.agg("|".join, axis=1)
    return keys.mask(frame.eq("#").all(axis=1))


def _date_part_series(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce", dayfirst=True)
    return parsed.dt.strftime("%Y-%m-%d").where(parsed.notna())

def _first_present(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    for col in candidates:
        if col in df.columns:
            return df[col]
    return pd.Series(pd.NA, index=df.index, dtype=object)


def _to_numeric_series(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    raw = series.astype(str).str.strip().str.replace(" ", "", regex=False).str.replace(",", ".", regex=False)
    raw = raw.mask(raw.str.upper().isin(INVALID_TEXT), pd.NA)
    numeric = pd.to_numeric(raw, errors="coerce").astype("Float64")
    invalid = series.notna() & numeric.isna()
    return numeric, invalid


def _days_between(end: pd.Series, start: pd.Series) -> pd.Series:
    return (pd.to_datetime(end, errors="coerce").dt.normalize() - pd.to_datetime(start, errors="coerce").dt.normalize()).dt.days.astype("Int64")


def _date_key(value: object, valid_date_keys: set[int]) -> int:
    ts = _parse_date(value)
    if pd.isna(ts):
        return 0
    key = int(pd.Timestamp(ts).strftime("%Y%m%d"))
    return key if key in valid_date_keys else 0


def _bool_from_yes_no(value: object) -> bool | pd.NA:
    if _is_missing(value):
        return pd.NA
    s = str(value).strip().upper()
    if s in OUI_VALUES:
        return True
    if s in NON_VALUES:
        return False
    return pd.NA


def _bool_ida(value: object) -> bool | pd.NA:
    if _is_missing(value):
        return pd.NA
    try:
        return int(float(str(value).strip())) != 0
    except ValueError:
        return pd.NA


def _bool_cloture(code_etat: object, etatgrnt: object, date_cloture: object) -> bool | pd.NA:
    if not pd.isna(_parse_date(date_cloture)):
        return True
    code = _clean_code(code_etat)
    etat = _clean_text(etatgrnt)
    if code == "2" or etat == "C":
        return True
    if code == "1" or etat == "O":
        return False
    return pd.NA


def _bool_corporel(value: object) -> bool | pd.NA:
    s = _clean_text(value)
    if s == "C":
        return True
    if s == "M":
        return False
    return pd.NA


def _bool_materiel(value: object) -> bool | pd.NA:
    s = _clean_text(value)
    if s == "M":
        return True
    if s == "C":
        return False
    return pd.NA


def _source_geo_key(row: pd.Series) -> str:
    geo_row = pd.Series({
        "regsini_hint": row.get("regsini"),
        "gouvernorat": row.get("gouvsini"),
        "localite": row.get("citesini"),
        "code_postal": row.get("cpostsini"),
    })
    source = load_dim_geo._source_values_from_row(geo_row)
    return load_dim_geo._source_geo_key_from_values(
        source.get("source_gouvernorat"),
        source.get("source_localite"),
        source.get("source_code_postal"),
    )


def _read_staging(engine, logger) -> pd.DataFrame:
    with engine.connect() as conn:
        available = set(row[0] for row in conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'staging' AND table_name = 'stg_sinistres'
        """)))
    select_cols = [col for col in SOURCE_COLUMNS if col in available]
    missing = [col for col in SOURCE_COLUMNS if col not in available]
    if missing:
        logger.warning(f"  Source columns absent from staging.stg_sinistres: {missing}")
    if not {"numsnt", "grntsini"}.issubset(set(select_cols)):
        raise RuntimeError("staging.stg_sinistres must contain numsnt and grntsini for fact_sinistre grain.")
    with engine.connect() as conn:
        df = pd.read_sql(text(f"SELECT {', '.join(select_cols)} FROM {SOURCE_TABLE}"), conn)
    logger.info(f"  source rows read from {SOURCE_TABLE}: {len(df)}")
    return df


def _read_table(engine, table_name: str, columns: list[str]) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(f"SELECT {', '.join(columns)} FROM dwh.{table_name}"), conn)


def _dimension_maps(engine, logger) -> dict[str, dict]:
    dims: dict[str, dict] = {}

    dim = _read_table(engine, "dim_sinistre", ["sinistre_sk", "numero_sinistre"])
    dim["_key"] = dim["numero_sinistre"].map(_clean_code)
    dims["sinistre"] = dim.dropna(subset=["_key"]).drop_duplicates("_key").set_index("_key")["sinistre_sk"].to_dict()

    dim = _read_table(engine, "dim_garantie", ["garantie_sk", "garantie_key", "code_produit", "code_garantie"])
    dim["_key"] = dim["garantie_key"].map(lambda v: _join_key(str(v).split("|")) if not _is_missing(v) else None)
    fallback_key = dim.apply(lambda r: _join_key([_clean_code(r["code_produit"]), _clean_code(r["code_garantie"])]), axis=1)
    dim["_key"] = dim["_key"].where(dim["_key"].notna(), fallback_key)
    dims["garantie"] = dim.dropna(subset=["_key"]).drop_duplicates("_key").set_index("_key")["garantie_sk"].to_dict()

    dim = _read_table(engine, "dim_client", ["client_sk", "idclt"])
    dim["_key"] = dim["idclt"].map(_clean_code)
    dims["client"] = dim.dropna(subset=["_key"]).drop_duplicates("_key").set_index("_key")["client_sk"].to_dict()

    dim = _read_table(engine, "dim_contrat", ["contrat_sk", "contrat_key", "numero_contrat"])
    dim["_key"] = dim["contrat_key"].map(dwh_utils.normalize_numcnt)
    dim["_raw_key"] = dim["numero_contrat"].map(dwh_utils.normalize_numcnt)
    dim["_key"] = dim["_key"].where(dim["_key"].notna(), dim["_raw_key"])
    dims["contrat"] = dim.dropna(subset=["_key"]).drop_duplicates("_key").set_index("_key")["contrat_sk"].to_dict()
    dims["dim_contrat_keys"] = set(dim["_key"].dropna())
    dims["dim_contrat_raw_keys"] = set(dim["_raw_key"].dropna())

    with engine.connect() as conn:
        prod_contracts = pd.read_sql(
            text("SELECT DISTINCT numcnt FROM staging.stg_production WHERE numcnt IS NOT NULL"),
            conn,
        )
    dims["production_contract_keys"] = set(prod_contracts["numcnt"].map(dwh_utils.normalize_numcnt).dropna())

    dim = _read_table(engine, "dim_vehicule", ["vehicule_sk", "immatriculation"])
    dim["_key"] = dim["immatriculation"].map(_clean_immat)
    dims["vehicule"] = dim.dropna(subset=["_key"]).drop_duplicates("_key").set_index("_key")["vehicule_sk"].to_dict()

    dim = _read_table(engine, "dim_conducteur", ["conducteur_sk", "nom_conducteur", "date_naissance_conducteur", "numero_permis", "categorie_permis", "date_permis"])
    dim["_key"] = dim.apply(lambda r: _join_key([
        _clean_nom(r["nom_conducteur"]), _date_part(r["date_naissance_conducteur"]),
        _clean_text(r["numero_permis"]), _clean_text(r["categorie_permis"]), _date_part(r["date_permis"]),
    ]), axis=1)
    dims["conducteur"] = dim.dropna(subset=["_key"]).drop_duplicates("_key").set_index("_key")["conducteur_sk"].to_dict()

    dim = _read_table(engine, "dim_tiers", ["tiers_sk", "nom_tiers", "immatriculation_vehicule_tiers", "numero_contrat_tiers", "numero_sinistre_tiers"])
    dim["_key"] = dim.apply(lambda r: _join_key([
        _clean_nom_tiers(r["nom_tiers"]), _clean_immat_tiers(r["immatriculation_vehicule_tiers"]),
        _clean_id(r["numero_contrat_tiers"]), _clean_id(r["numero_sinistre_tiers"]),
    ]), axis=1)
    dims["tiers"] = dim.dropna(subset=["_key"]).drop_duplicates("_key").set_index("_key")["tiers_sk"].to_dict()

    dim = _read_table(engine, "dim_camtier", ["camtier_sk", "code_camtier"])
    dim["_key"] = dim["code_camtier"].map(lambda v: _join_key(str(v).split("|")) if not _is_missing(v) else None)
    dims["camtier"] = dim.dropna(subset=["_key"]).drop_duplicates("_key").set_index("_key")["camtier_sk"].to_dict()

    dim = _read_table(engine, "dim_geo", ["geo_sk", "geo_key"])
    dims["geo"] = dim.drop_duplicates("geo_key").set_index("geo_key")["geo_sk"].to_dict()

    dim = _read_table(engine, "dim_date", ["date_sk"])
    dims["date_keys"] = set(pd.to_numeric(dim["date_sk"], errors="coerce").dropna().astype(int).tolist())

    logger.info("  dimension maps loaded: " + ", ".join(f"{k}={len(v)}" for k, v in dims.items()))
    return dims


def _load_geo_mapping(logger) -> pd.DataFrame:
    if not GEO_MAPPING_PATH.exists():
        logger.warning(f"  geo mapping not found: {GEO_MAPPING_PATH}; geo_sinistre_sk will fallback to 0")
        return pd.DataFrame(columns=["source_geo_key", "resolved_geo_key"])
    df = pd.read_csv(GEO_MAPPING_PATH, dtype=str, keep_default_na=False)
    required = {"source_geo_key", "resolved_geo_key"}
    missing = required.difference(df.columns)
    if missing:
        logger.warning(f"  geo mapping missing columns {sorted(missing)}; geo_sinistre_sk will fallback to 0")
        return pd.DataFrame(columns=["source_geo_key", "resolved_geo_key"])
    df = df[["source_geo_key", "resolved_geo_key"]].drop_duplicates(subset=["source_geo_key"], keep="first")
    logger.info(f"  geo source->resolved mapping loaded: {len(df)} keys")
    return df


def _write_duplicate_report(df: pd.DataFrame) -> int:
    cols = ["sinistre_garantie_key", "numero_sinistre", "code_garantie"]
    duplicated = df[df["sinistre_garantie_key"].duplicated(keep=False)].copy()
    if duplicated.empty:
        pd.DataFrame(columns=cols + ["duplicate_count"]).to_csv(DUPLICATE_GRAIN_PATH, index=False, encoding="utf-8-sig")
        return 0
    counts = duplicated.groupby("sinistre_garantie_key").size().rename("duplicate_count").reset_index()
    report = duplicated[cols].merge(counts, on="sinistre_garantie_key", how="left")
    report.to_csv(DUPLICATE_GRAIN_PATH, index=False, encoding="utf-8-sig")
    return len(report)


def _deduplicate_grain(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if not df["sinistre_garantie_key"].duplicated().any():
        return df, 0
    ranked = df.copy()
    ranked["_completeness"] = ranked.notna().sum(axis=1)
    ranked = ranked.sort_values(["sinistre_garantie_key", "_completeness"], ascending=[True, False])
    deduped = ranked.drop_duplicates("sinistre_garantie_key", keep="first").drop(columns=["_completeness"])
    return deduped, len(df) - len(deduped)


def _write_unmatched_dimensions_report(df: pd.DataFrame) -> dict[str, int]:
    fk_cols = ["sinistre_sk", "garantie_sk", "client_sk", "contrat_sk", "vehicule_sk", "conducteur_sk", "tiers_sk", "camtier_sk", "geo_sinistre_sk"]
    context_candidates = [
        "source_numcnt", "source_contrat_key", "client_key", "vehicule_key",
        "conducteur_key", "tiers_key", "camtier_key",
        "regsini", "gouvsini", "citesini", "cpostsini",
        "source_geo_key", "resolved_geo_key",
    ]
    context_cols = [col for col in context_candidates if col in df.columns]
    report = df[["sinistre_garantie_key", "numero_sinistre", "code_garantie", *context_cols, *fk_cols]].copy()
    metrics = {}
    for col in fk_cols:
        flag = f"missing_{col}"
        report[flag] = report[col].eq(0)
        metrics[flag] = int(report[flag].sum())
    flag_cols = [f"missing_{c}" for c in fk_cols]
    report["missing_dimension_count"] = report[flag_cols].sum(axis=1).astype(int)
    out_cols = [
        "sinistre_garantie_key", "numero_sinistre", "code_garantie",
        *context_cols, "missing_dimension_count", *flag_cols,
    ]
    report = report.loc[report[flag_cols].any(axis=1), out_cols]
    report.to_csv(UNMATCHED_DIMS_PATH, index=False, encoding="utf-8-sig")
    return metrics


def _write_unmatched_contrats_report(df: pd.DataFrame, dims: dict) -> dict[str, int]:
    columns = [
        "numero_sinistre",
        "code_garantie",
        "sinistre_garantie_key",
        "source_numcnt",
        "source_contrat_key",
        "diagnostic",
        "exists_in_staging_production",
        "exists_in_dim_contrat_raw",
        "exists_in_dim_contrat_key",
    ]
    missing = df.loc[df["contrat_sk"].eq(0), [
        "numero_sinistre",
        "code_garantie",
        "sinistre_garantie_key",
        "source_numcnt",
        "source_contrat_key",
    ]].copy()

    production_keys = dims.get("production_contract_keys", set())
    dim_raw_keys = dims.get("dim_contrat_raw_keys", set())
    dim_keys = dims.get("dim_contrat_keys", set())

    missing["exists_in_staging_production"] = missing["source_contrat_key"].map(lambda v: v in production_keys if pd.notna(v) else False)
    missing["exists_in_dim_contrat_raw"] = missing["source_contrat_key"].map(lambda v: v in dim_raw_keys if pd.notna(v) else False)
    missing["exists_in_dim_contrat_key"] = missing["source_contrat_key"].map(lambda v: v in dim_keys if pd.notna(v) else False)

    missing["diagnostic"] = "ABSENT_PRODUCTION"
    missing.loc[missing["source_contrat_key"].isna(), "diagnostic"] = "INVALID_NUMCNT"
    missing.loc[
        missing["source_contrat_key"].notna() & missing["exists_in_staging_production"],
        "diagnostic",
    ] = "EXISTS_IN_PRODUCTION_JOIN_PROBLEM"

    if missing.empty:
        pd.DataFrame(columns=columns).to_csv(UNMATCHED_CONTRATS_PATH, index=False, encoding="utf-8-sig")
        diagnostics = pd.Series(dtype="int64")
    else:
        missing = missing[columns]
        missing.to_csv(UNMATCHED_CONTRATS_PATH, index=False, encoding="utf-8-sig")
        diagnostics = missing["diagnostic"].value_counts()

    return {
        "unmatched_contrat_rows": int(len(missing)),
        "unmatched_contrat_invalid_numcnt": int(diagnostics.get("INVALID_NUMCNT", 0)),
        "unmatched_contrat_absent_production": int(diagnostics.get("ABSENT_PRODUCTION", 0)),
        "unmatched_contrat_join_problem": int(diagnostics.get("EXISTS_IN_PRODUCTION_JOIN_PROBLEM", 0)),
    }


def _write_date_anomalies_report(df: pd.DataFrame) -> dict[str, int]:
    report = df[[
        "sinistre_garantie_key", "numero_sinistre", "code_garantie",
        "date_survenance", "date_declaration", "date_ouverture", "date_cloture",
        "delai_survenance_declaration_jours", "delai_declaration_ouverture_jours", "delai_ouverture_cloture_jours",
    ]].copy()
    report["missing_date_survenance"] = report["date_survenance"].isna()
    report["missing_date_declaration"] = report["date_declaration"].isna()
    report["missing_date_ouverture"] = report["date_ouverture"].isna()
    report["missing_date_cloture"] = report["date_cloture"].isna()
    report["negative_surv_decl"] = report["delai_survenance_declaration_jours"] < 0
    report["negative_decl_ouv"] = report["delai_declaration_ouverture_jours"] < 0
    report["negative_ouv_clot"] = report["delai_ouverture_cloture_jours"] < 0
    flags = [c for c in report.columns if c.startswith("missing_") or c.startswith("negative_")]
    metrics = {flag: int(report[flag].sum()) for flag in flags}
    report = report.loc[report[flags].any(axis=1)]
    report.to_csv(DATE_ANOMALIES_PATH, index=False, encoding="utf-8-sig")
    return metrics


def _write_amount_anomalies_report(df: pd.DataFrame, invalid_casts: dict[str, pd.Series]) -> dict[str, int]:
    amount_cols = ["montant_evaluation", "montant_reglement", "montant_reserve", "montant_recours", "montant_charge_sinistre"]
    report = df[["sinistre_garantie_key", "numero_sinistre", "code_garantie", *amount_cols]].copy()
    metrics = {}
    flags = []
    for col in amount_cols:
        flag = f"negative_{col}"
        report[flag] = report[col] < 0
        metrics[flag] = int(report[flag].sum())
        flags.append(flag)
        invalid_flag = f"invalid_cast_{col}"
        raw_invalid = invalid_casts.get(col)
        report[invalid_flag] = raw_invalid.reindex(report.index).fillna(False).astype(bool) if raw_invalid is not None else False
        metrics[invalid_flag] = int(report[invalid_flag].sum())
        flags.append(invalid_flag)
    positive_charge = report.loc[report["montant_charge_sinistre"] > 0, "montant_charge_sinistre"].dropna()
    threshold = float(positive_charge.quantile(0.99)) if not positive_charge.empty else None
    report["very_high_montant_charge_sinistre"] = False if threshold is None else report["montant_charge_sinistre"] > threshold
    metrics["very_high_montant_charge_sinistre"] = int(report["very_high_montant_charge_sinistre"].sum())
    flags.append("very_high_montant_charge_sinistre")
    report = report.loc[report[flags].any(axis=1)]
    report.to_csv(AMOUNT_ANOMALIES_PATH, index=False, encoding="utf-8-sig")
    metrics["amount_anomaly_rows"] = len(report)
    return metrics


def _write_load_summary(metrics: dict) -> None:
    pd.DataFrame([{"metric": k, "value": v} for k, v in sorted(metrics.items())]).to_csv(
        LOAD_SUMMARY_PATH, index=False, encoding="utf-8-sig"
    )


def transform_fact_sinistre(df_raw: pd.DataFrame, dims: dict, geo_mapping: pd.DataFrame, logger) -> tuple[pd.DataFrame, dict]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    df = df_raw.copy()
    n_source = len(df)

    df["numero_sinistre"] = _first_present(df, ["numsnt_norm", "numsnt"]).map(_clean_code)
    df["code_garantie"] = _first_present(df, ["grntsini_norm", "grntsini"]).map(_clean_code)
    df["code_produit"] = _first_present(df, ["codprod", "codprod_from_contract"]).map(_clean_code)
    df["sinistre_garantie_key"] = _series_key([df["numero_sinistre"], df["code_garantie"]])

    n_duplicate_report_rows = _write_duplicate_report(df)
    df, n_duplicate_resolved = _deduplicate_grain(df)

    df["sinistre_sk"] = df["numero_sinistre"].map(dims["sinistre"]).fillna(0).astype("int64")
    df["garantie_key"] = _series_key([df["code_produit"], df["code_garantie"]])
    df["garantie_sk"] = df["garantie_key"].map(dims["garantie"]).fillna(0).astype("int64")
    df["client_key"] = _first_present(df, ["idclt"]).map(_clean_code)
    df["client_sk"] = df["client_key"].map(dims["client"]).fillna(0).astype("int64")
    df["source_numcnt"] = _first_present(df, ["numcnt", "numcnt_norm"])
    df["source_contrat_key"] = df["source_numcnt"].map(dwh_utils.normalize_numcnt)
    df["contrat_key"] = df["source_contrat_key"]
    df["contrat_sk"] = df["contrat_key"].map(dims["contrat"]).fillna(0).astype("int64")
    df["vehicule_key"] = _first_present(df, ["immat"]).map(_clean_immat)
    df["vehicule_sk"] = df["vehicule_key"].map(dims["vehicule"]).fillna(0).astype("int64")

    df["conducteur_key"] = _series_key([
        _first_present(df, ["nomconduc"]).map(_clean_nom),
        _date_part_series(_first_present(df, ["datnaicon"])),
        _first_present(df, ["numpermis"]).map(_clean_text),
        _first_present(df, ["categperm"]).map(_clean_text),
        _date_part_series(_first_present(df, ["datepermi"])),
    ])
    df["conducteur_sk"] = df["conducteur_key"].map(dims["conducteur"]).fillna(0).astype("int64")

    df["tiers_key"] = _series_key([
        _first_present(df, ["nomtiers"]).map(_clean_nom_tiers),
        _first_present(df, ["imvehtier"]).map(_clean_immat_tiers),
        _first_present(df, ["numcnttie"]).map(_clean_id),
        _first_present(df, ["numsnttie"]).map(_clean_id),
    ])
    df["tiers_sk"] = df["tiers_key"].map(dims["tiers"]).fillna(0).astype("int64")

    df["camtier_key"] = _series_key([_first_present(df, ["natcamtie"]).map(_clean_camtier_nature), _first_present(df, ["idcamtier"]).map(_clean_camtier_id)])
    df["camtier_sk"] = df["camtier_key"].map(dims["camtier"]).fillna(0).astype("int64")

    geo_lookup = geo_mapping.set_index("source_geo_key")["resolved_geo_key"].to_dict() if not geo_mapping.empty else {}
    geo_cols = ["regsini", "gouvsini", "citesini", "cpostsini"]
    geo_distinct = df[geo_cols].drop_duplicates().copy()
    geo_distinct["source_geo_key"] = geo_distinct.apply(_source_geo_key, axis=1)
    df = df.merge(geo_distinct, on=geo_cols, how="left")
    df["resolved_geo_key"] = df["source_geo_key"].map(geo_lookup)
    df["geo_sinistre_sk"] = df["resolved_geo_key"].map(dims["geo"]).fillna(0).astype("int64")

    df["date_survenance"] = pd.to_datetime(_first_present(df, ["dtsurv"]), errors="coerce", dayfirst=True)
    df["date_declaration"] = pd.to_datetime(_first_present(df, ["dtdecsnt"]), errors="coerce", dayfirst=True)
    df["date_ouverture"] = pd.to_datetime(_first_present(df, ["dtouvsnt"]), errors="coerce", dayfirst=True)
    df["date_cloture"] = pd.to_datetime(_first_present(df, ["dtcltsnt"]), errors="coerce", dayfirst=True)
    date_keys = dims["date_keys"]
    df["date_survenance_sk"] = df["date_survenance"].map(lambda v: _date_key(v, date_keys)).astype("int64")
    df["date_declaration_sk"] = df["date_declaration"].map(lambda v: _date_key(v, date_keys)).astype("int64")
    df["date_ouverture_sk"] = df["date_ouverture"].map(lambda v: _date_key(v, date_keys)).astype("int64")
    df["date_cloture_sk"] = df["date_cloture"].map(lambda v: _date_key(v, date_keys)).astype("int64")
    df["delai_survenance_declaration_jours"] = _days_between(df["date_declaration"], df["date_survenance"])
    df["delai_declaration_ouverture_jours"] = _days_between(df["date_ouverture"], df["date_declaration"])
    df["delai_ouverture_cloture_jours"] = _days_between(df["date_cloture"], df["date_ouverture"])

    amount_sources = {
        "montant_evaluation": "eval_init",
        "montant_reglement": "mntpaigrn",
        "montant_reserve": "mntprovis",
        "montant_recours": "mntrecour",
        "montant_charge_sinistre": "mnttotal",
    }
    invalid_casts: dict[str, pd.Series] = {}
    for target, source_col in amount_sources.items():
        if source_col in df.columns:
            df[target], invalid_casts[target] = _to_numeric_series(df[source_col])
        else:
            logger.warning(f"  amount source column missing: {source_col}; {target} set to NULL")
            df[target] = pd.Series(pd.NA, index=df.index, dtype="Float64")
            invalid_casts[target] = pd.Series(False, index=df.index)

    df["est_cloture"] = df.apply(lambda r: _bool_cloture(r.get("code_etat"), r.get("etatgrnt"), r.get("dtcltsnt")), axis=1).astype("boolean")
    df["est_corporel"] = df.get("natsini", pd.Series(pd.NA, index=df.index)).map(_bool_corporel).astype("boolean")
    df["est_materiel"] = df.get("natsini", pd.Series(pd.NA, index=df.index)).map(_bool_materiel).astype("boolean")
    df["est_ida"] = df.get("cas_ida", pd.Series(pd.NA, index=df.index)).map(_bool_ida).astype("boolean")
    df["est_transaction"] = df.get("ddetransa", pd.Series(pd.NA, index=df.index)).map(_bool_from_yes_no).astype("boolean")
    df["est_forcage"] = df.get("indforcag", pd.Series(pd.NA, index=df.index)).map(_bool_from_yes_no).astype("boolean")
    df["est_coassurance"] = df.get("coassur", pd.Series(pd.NA, index=df.index)).map(_bool_from_yes_no).astype("boolean")
    df["est_reassurance"] = df.get("reassur", pd.Series(pd.NA, index=df.index)).map(_bool_from_yes_no).astype("boolean")
    df["motif_cloture_garantie"] = df.get("motifclot", pd.Series(pd.NA, index=df.index)).map(_clean_text)
    df["etat_garantie_sinistre"] = df.get("etatgrnt", pd.Series(pd.NA, index=df.index)).map(_clean_text)
    df["source_system"] = SOURCE_SYSTEM
    df["created_at"] = TODAY

    unmatched_metrics = _write_unmatched_dimensions_report(df)
    contrat_metrics = _write_unmatched_contrats_report(df, dims)
    date_metrics = _write_date_anomalies_report(df)
    amount_metrics = _write_amount_anomalies_report(df, invalid_casts)

    df = df.sort_values(["numero_sinistre", "code_garantie"], na_position="last").reset_index(drop=True)
    df.insert(0, "fact_sinistre_sk", range(1, len(df) + 1))
    for col in FINAL_COLS:
        if col not in df.columns:
            df[col] = pd.NA
    df_final = df[FINAL_COLS].copy()
    fk_cols = [c for c in FINAL_COLS if c.endswith("_sk") and c != "fact_sinistre_sk"]
    for col in fk_cols:
        df_final[col] = pd.to_numeric(df_final[col], errors="coerce").fillna(0).astype("int64")

    metrics = {
        "source_rows": n_source,
        "final_fact_rows": len(df_final),
        "duplicate_grain_rows_detected": n_duplicate_report_rows,
        "duplicate_grain_rows_resolved": n_duplicate_resolved,
        "fact_sinistre_rows_loaded": len(df_final),
        "geo_mapping_rows": len(geo_mapping),
        **unmatched_metrics,
        **contrat_metrics,
        **date_metrics,
        **amount_metrics,
    }
    _write_load_summary(metrics)
    return df_final, metrics


def load_fact_sinistre(run_id: str, engine, logger) -> int:
    logger.info(f"[RUN {run_id}] {SOURCE_TABLE} -> dwh.{TABLE_NAME}")
    dwh_utils.create_dwh_schema(engine, logger)
    with engine.connect() as conn:
        source_exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'staging' AND table_name = 'stg_sinistres'
        """)).fetchone()
    if not source_exists:
        raise RuntimeError("Table source staging.stg_sinistres introuvable. Run staging load first.")

    df_raw = _read_staging(engine, logger)
    dims = _dimension_maps(engine, logger)
    geo_mapping = _load_geo_mapping(logger)
    df_final, metrics = transform_fact_sinistre(df_raw, dims, geo_mapping, logger)
    n_rows, elapsed = dwh_utils.write_to_dwh(df_final, engine, TABLE_NAME, logger, chunksize=1000)

    logger.info("=" * 72)
    logger.info(f"  source rows                         : {metrics['source_rows']}")
    logger.info(f"  final fact rows                     : {metrics['final_fact_rows']}")
    logger.info(f"  duplicate grain rows detected       : {metrics['duplicate_grain_rows_detected']}")
    logger.info(f"  duplicate grain rows resolved       : {metrics['duplicate_grain_rows_resolved']}")
    logger.info(f"  missing sinistre_sk                 : {metrics['missing_sinistre_sk']}")
    logger.info(f"  missing garantie_sk                 : {metrics['missing_garantie_sk']}")
    logger.info(f"  missing client_sk                   : {metrics['missing_client_sk']}")
    logger.info(f"  missing contrat_sk                  : {metrics['missing_contrat_sk']}")
    logger.info(f"    INVALID_NUMCNT                    : {metrics['unmatched_contrat_invalid_numcnt']}")
    logger.info(f"    ABSENT_PRODUCTION                 : {metrics['unmatched_contrat_absent_production']}")
    logger.info(f"    EXISTS_IN_PRODUCTION_JOIN_PROBLEM : {metrics['unmatched_contrat_join_problem']}")
    logger.info(f"  missing vehicule_sk                 : {metrics['missing_vehicule_sk']}")
    logger.info(f"  missing conducteur_sk               : {metrics['missing_conducteur_sk']}")
    logger.info(f"  missing tiers_sk                    : {metrics['missing_tiers_sk']}")
    logger.info(f"  missing camtier_sk                  : {metrics['missing_camtier_sk']}")
    logger.info(f"  missing geo_sinistre_sk             : {metrics['missing_geo_sinistre_sk']}")
    logger.info(f"  negative surv->decl delays          : {metrics['negative_surv_decl']}")
    logger.info(f"  negative decl->ouv delays           : {metrics['negative_decl_ouv']}")
    logger.info(f"  negative ouv->clot delays           : {metrics['negative_ouv_clot']}")
    logger.info(f"  amount anomaly rows                 : {metrics['amount_anomaly_rows']}")
    logger.info(f"  fact_sinistre rows loaded           : {n_rows}")
    logger.info(f"  unmatched dimensions report         : {UNMATCHED_DIMS_PATH}")
    logger.info(f"  unmatched contrats report           : {UNMATCHED_CONTRATS_PATH}")
    logger.info(f"  date anomalies report               : {DATE_ANOMALIES_PATH}")
    logger.info(f"  duplicate grain report              : {DUPLICATE_GRAIN_PATH}")
    logger.info(f"  amount anomalies report             : {AMOUNT_ANOMALIES_PATH}")
    logger.info(f"  load summary report                 : {LOAD_SUMMARY_PATH}")
    logger.info(f"  load duration                       : {elapsed:.1f}s")
    logger.info("=" * 72)
    logger.info("Validation SQL queries:")
    logger.info("""
SELECT COUNT(*) AS total_rows
FROM dwh.fact_sinistre;

SELECT sinistre_garantie_key, COUNT(*) AS nb
FROM dwh.fact_sinistre
GROUP BY sinistre_garantie_key
HAVING COUNT(*) > 1;

SELECT
    COUNT(*) FILTER (WHERE sinistre_sk = 0) AS missing_sinistre,
    COUNT(*) FILTER (WHERE garantie_sk = 0) AS missing_garantie,
    COUNT(*) FILTER (WHERE client_sk = 0) AS missing_client,
    COUNT(*) FILTER (WHERE contrat_sk = 0) AS missing_contrat,
    COUNT(*) FILTER (WHERE vehicule_sk = 0) AS missing_vehicule,
    COUNT(*) FILTER (WHERE conducteur_sk = 0) AS missing_conducteur,
    COUNT(*) FILTER (WHERE tiers_sk = 0) AS missing_tiers,
    COUNT(*) FILTER (WHERE camtier_sk = 0) AS missing_camtier,
    COUNT(*) FILTER (WHERE geo_sinistre_sk = 0) AS missing_geo
FROM dwh.fact_sinistre;

SELECT
    COUNT(*) FILTER (WHERE delai_survenance_declaration_jours < 0) AS negative_surv_decl,
    COUNT(*) FILTER (WHERE delai_declaration_ouverture_jours < 0) AS negative_decl_ouv,
    COUNT(*) FILTER (WHERE delai_ouverture_cloture_jours < 0) AS negative_ouv_clot
FROM dwh.fact_sinistre;

SELECT geo_sinistre_sk, COUNT(*) AS nb
FROM dwh.fact_sinistre
GROUP BY geo_sinistre_sk
ORDER BY nb DESC
LIMIT 20;
""")
    return n_rows


if __name__ == "__main__":
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger = dwh_utils.setup_logging(run_id, log_name="load_fact_sinistre")
    engine = dwh_utils.build_engine(logger)
    n = load_fact_sinistre(run_id, engine, logger)
    logger.info(f"Done: {n} rows -> dwh.{TABLE_NAME}")







