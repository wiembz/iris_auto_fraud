"""
etl/dwh/load_dim_geo.py
=======================
Builds the final clean dwh.dim_geo dimension from claim geography only.

Business grain:
  One normalized claim geography identified by:
  pays, gouvernorat, region, localite, code_postal.

Business key:
  geo_key = pays|gouvernorat|region|localite|code_postal

Safe workflow:
  1. Read raw claim geography from staging.stg_sinistres.
  2. Normalize source labels.
  3. Resolve geography with data/reference/dim_geo/geo_tunisia_reference.csv.
  4. Apply only APPROVED geography corrections from
     data/reference/dim_geo/geo_dim_approved_corrections.csv.
  5. Resolve postal codes only when a real unique 4-digit code is trusted.
  6. Apply only APPROVED postal corrections from
     data/reference/dim_geo/geo_dim_postal_approved_corrections.csv.
  7. Recompute geo_key and geo_quality_level.
  8. Deduplicate and keep one technical UNKNOWN row.
  9. Load only clean business columns into dwh.dim_geo.

DWH contract:
  dwh.dim_geo keeps exactly the final business columns listed in FINAL_COLS.
  Audit and resolution diagnostics stay in data/quality_reports/dim_geo/.

Excluded by design:
  - client address geography
  - street/rue
  - type_geo
  - audit columns in dwh.dim_geo
"""
from __future__ import annotations

import math
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwh_utils

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TABLE_NAME    = "dim_geo"
SOURCE_TABLE  = "staging.stg_sinistres"
SOURCE_SYSTEM = "BNA_ASSURANCES"
SOURCE_CONTEXT = "SINISTRE"
TODAY         = datetime.now(timezone.utc).replace(tzinfo=None)
GEO_REFERENCE_PATH = BASE_DIR / "data" / "reference" / "dim_geo" / "geo_tunisia_reference.csv"
# Main canonical Tunisia locality/postal reference (DimRegion.csv)
GEO_POSTAL_REFERENCE_PATH = BASE_DIR / "data" / "reference" / "dim_geo" / "DimRegion.csv"
GEO_ALIAS_PATH = BASE_DIR / "data" / "reference" / "dim_geo" / "ref_geo_alias.csv"
APPROVED_CORRECTIONS_PATH = BASE_DIR / "data" / "reference" / "dim_geo" / "geo_dim_approved_corrections.csv"
POSTAL_APPROVED_CORRECTIONS_PATH = BASE_DIR / "data" / "reference" / "dim_geo" / "geo_dim_postal_approved_corrections.csv"
GEO_QUALITY_REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "dim_geo"
DIM_GEO_EXCLUDED_PATH  = GEO_QUALITY_REPORT_DIR / "dim_geo_excluded.csv"
RESOLUTION_REPORT_PATH = GEO_QUALITY_REPORT_DIR / "dim_geo_resolution_report.csv"
UNRESOLVED_REPORT_PATH = GEO_QUALITY_REPORT_DIR / "dim_geo_unresolved.csv"
CONFLICTS_AFTER_RESOLUTION_PATH = GEO_QUALITY_REPORT_DIR / "dim_geo_conflicts_after_resolution.csv"
MISSING_POSTAL_REPORT_PATH = GEO_QUALITY_REPORT_DIR / "dim_geo_missing_postal_codes.csv"
POSTAL_AMBIGUOUS_REPORT_PATH = GEO_QUALITY_REPORT_DIR / "dim_geo_postal_ambiguous.csv"
POSTAL_MISSING_REFERENCE_REPORT_PATH = GEO_QUALITY_REPORT_DIR / "dim_geo_postal_missing_reference.csv"
POSTAL_CONFLICTS_REPORT_PATH = GEO_QUALITY_REPORT_DIR / "dim_geo_postal_source_conflicts.csv"
POSTAL_ONLY_RESOLVED_PATH = GEO_QUALITY_REPORT_DIR / "dim_geo_postal_only_resolved.csv"
POSTAL_ONLY_UNRESOLVED_PATH = GEO_QUALITY_REPORT_DIR / "dim_geo_postal_only_unresolved.csv"
POSTAL_APPROVED_UNMATCHED_PATH = GEO_QUALITY_REPORT_DIR / "dim_geo_postal_approved_corrections_unmatched.csv"
GOV_LOCALITY_CONFLICTS_PATH = GEO_QUALITY_REPORT_DIR / "dim_geo_governorate_locality_conflicts.csv"
DEDUP_DECISIONS_PATH = GEO_QUALITY_REPORT_DIR / "dim_geo_deduplication_decisions.csv"
SOURCE_TO_RESOLVED_MAPPING_PATH = GEO_QUALITY_REPORT_DIR / "dim_geo_source_to_resolved_mapping.csv"

FINAL_COLS = [
    "geo_sk",
    "pays",
    "region",
    "gouvernorat",
    "localite",
    "adresse_fragment",
    "code_postal",
    "geo_entity_type",
    "geo_quality_level",
    "needs_review",
    "geo_key",
    "source_system",
    "source_context",
    "created_at",
]

# Staging column candidates, in priority order
COLUMN_CANDIDATES: dict[str, list[str]] = {
    # regsini_hint: REGSINI is free-text; used only as secondary localite/gouvernorat hint.
    "regsini_hint": ["regsini",  "reg_sini",  "region_sinistre"],
    "gouvernorat":  ["gouvsini", "gouv_sini", "gouvernorat_sinistre", "gouvernorat"],
    "localite":     ["citesini", "cite_sini", "localite_sinistre",    "localite", "cite"],
    "code_postal":  ["cpostsini", "cpost_sini", "cp_sini", "cpsini", "codpostsini", "code_postal_sinistre", "code_postal", "cpost"],
    # rue: street/address field — used as last-resort localite hint if it looks like a place name
    "rue":          ["rue", "adresse", "adresse_sinistre", "rue_sinistre", "adressesini"],
}

_KEY_UNKNOWN     = "UNKNOWN"
_GEO_KEY_UNKNOWN = "UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN"  # pays|gouvernorat|localite|code_postal

_INVALID_TEXT = frozenset({
    "", "NULL", "NAN", "NONE", "UNKNOWN",
    "INCONNU", "INCONNUE", "NON RENSEIGNE", "NON RENSEIGNEE",
    "N/A", "N A", "NA", "#N/A", "ND", "NR",
    "/", "-", "--", "---", ".", "..", "0", "00", "0000", "1",
})
_VALID_GOVERNORATS = frozenset({
    "TUNIS", "ARIANA", "BEN AROUS", "MANOUBA",
    "NABEUL", "ZAGHOUAN", "BIZERTE",
    "BEJA", "JENDOUBA", "KEF", "SILIANA",
    "SOUSSE", "MONASTIR", "MAHDIA", "SFAX",
    "KAIROUAN", "KASSERINE", "SIDI BOUZID",
    "GABES", "MEDENINE", "TATAOUINE",
    "GAFSA", "TOZEUR", "KEBILI",
})

# Authoritative gouvernorat → region mapping (24 Tunisian governorates).
# Region is ALWAYS derived from this table — never from REGSINI or reference CSV.
_REGION_FROM_GOUVERNORAT: dict[str, str] = {
    "ARIANA":      "GRAND TUNIS",
    "BEN AROUS":   "GRAND TUNIS",
    "MANOUBA":     "GRAND TUNIS",
    "TUNIS":       "GRAND TUNIS",
    "BIZERTE":     "NORD EST",
    "NABEUL":      "NORD EST",
    "ZAGHOUAN":    "NORD EST",
    "BEJA":        "NORD OUEST",
    "JENDOUBA":    "NORD OUEST",
    "KEF":         "NORD OUEST",
    "SILIANA":     "NORD OUEST",
    "MONASTIR":    "CENTRE EST",
    "MAHDIA":      "CENTRE EST",
    "SFAX":        "CENTRE EST",
    "SOUSSE":      "CENTRE EST",
    "KAIROUAN":    "CENTRE OUEST",
    "KASSERINE":   "CENTRE OUEST",
    "SIDI BOUZID": "CENTRE OUEST",
    "GABES":       "SUD EST",
    "MEDENINE":    "SUD EST",
    "TATAOUINE":   "SUD EST",
    "GAFSA":       "SUD OUEST",
    "KEBILI":      "SUD OUEST",
    "TOZEUR":      "SUD OUEST",
}

# Tunisian postal-code governorate prefixes. They are used only as a
# consistency guard; the loader never writes a prefix such as 20xx as a code.
_POSTAL_PREFIXES_BY_GOUVERNORAT = {
    "ARIANA": frozenset({"20"}),
    "BEJA": frozenset({"90"}),
    "BEN AROUS": frozenset({"20", "11"}),
    "BIZERTE": frozenset({"70"}),
    "GABES": frozenset({"60"}),
    "GAFSA": frozenset({"21"}),
    "JENDOUBA": frozenset({"81"}),
    "KAIROUAN": frozenset({"31"}),
    "KASSERINE": frozenset({"12"}),
    "KEBILI": frozenset({"42"}),
    "KEF": frozenset({"71"}),
    "MAHDIA": frozenset({"51"}),
    "MANOUBA": frozenset({"20", "11"}),
    "MEDENINE": frozenset({"41"}),
    "MONASTIR": frozenset({"50"}),
    "NABEUL": frozenset({"80"}),
    "SFAX": frozenset({"30"}),
    "SIDI BOUZID": frozenset({"91"}),
    "SILIANA": frozenset({"61"}),
    "SOUSSE": frozenset({"40"}),
    "TATAOUINE": frozenset({"32"}),
    "TOZEUR": frozenset({"22"}),
    "TUNIS": frozenset({"10", "20"}),
    "ZAGHOUAN": frozenset({"11"}),
}
_GOUVERNORAT_ALIASES: dict[str, str] = {
    "ARI": "ARIANA",
    "ARIA": "ARIANA",
    "ARIAN": "ARIANA",
    "ARIANA VILLE": "ARIANA",
    "AEN AROUS": "BEN AROUS",
    "BENAROUS": "BEN AROUS",
    "BENA ROUS": "BEN AROUS",
    "BEN AOUS": "BEN AROUS",
    "BEN AROU": "BEN AROUS",
    "BEN ARUS": "BEN AROUS",
    "BIZER": "BIZERTE",
    "BIZERT": "BIZERTE",
    "BIZERTA": "BIZERTE",
    "GAFES": "GAFSA",
    "GABES VILLE": "GABES",
    "JANDOUBA": "JENDOUBA",
    "KAIROUEN": "KAIROUAN",
    "KEROUAN": "KAIROUAN",
    "KASSERIEN": "KASSERINE",
    "KEBILLI": "KEBILI",
    "LE KEF": "KEF",
    "EL KEF": "KEF",
    "LA MANNOUBA": "MANOUBA",
    "MANNOUBA": "MANOUBA",
    "MANOUBA VILLE": "MANOUBA",
    "MEDNINE": "MEDENINE",
    "MEDNIN": "MEDENINE",
    "MONASTIR VILLE": "MONASTIR",
    "NABEL": "NABEUL",
    "NABEOUL": "NABEUL",
    "SAFX": "SFAX",
    "SFA": "SFAX",
    "SFX": "SFAX",
    "SFXA": "SFAX",
    "SFGAX": "SFAX",
    "SFAX VILLE": "SFAX",
    "SIDI BOUSID": "SIDI BOUZID",
    "SIDI BOUZAID": "SIDI BOUZID",
    "SOUSS": "SOUSSE",
    "SOUSSE VILLE": "SOUSSE",
    "STUNIS": "TUNIS",
    "TUNI": "TUNIS",
    "TUNID": "TUNIS",
    "TUINS": "TUNIS",
    "TUIS": "TUNIS",
    "TUNS": "TUNIS",
    "TUNIS VILLE": "TUNIS",
    "TUNISIE": "TUNIS",
    "TATAOUIEN": "TATAOUINE",
    "ZAGHOUANE": "ZAGHOUAN",
    # Suburbs / delegations → parent gouvernorat
    "MANNOUBA":      "MANOUBA",
    "B AROUS":       "BEN AROUS",
    "BAN AROUS":     "BEN AROUS",
    "JENDOUBAS":     "JENDOUBA",
    "BARDO":         "TUNIS",
    "LA MARSA":      "ARIANA",
    "RADES":         "BEN AROUS",
    "HAMMAM LIF":    "BEN AROUS",
    "MEGRINE":       "BEN AROUS",
    "MORNAG":        "BEN AROUS",
    "RAOUED":        "ARIANA",
    "LA SOUKRA":     "ARIANA",
    "ETTADHAMEN":    "ARIANA",
    "SIJOUMI":       "TUNIS",
    "EL MOUROUJ":    "BEN AROUS",
    "DENDEN":        "MANOUBA",
    "OUED ELLIL":    "MANOUBA",
}

_GENERIC_LOCALITE_TERMS = frozenset({
    "AVENUE",
    "AV",
    "BOULEVARD",
    "CENTRE",
    "CENTRE VILLE",
    "CITE",
    "EL",
    "LA",
    "LES",
    "RUE",
    "ROUTE",
    "RTE",
    "SID",
    "SIDI",
    "VILLE",
    "ZONE",
})

# Fuzzy matching thresholds (SequenceMatcher ratio)
_FUZZY_HIGH_THRESHOLD = 0.88   # → VALIDATED quality
_FUZZY_LOW_THRESHOLD  = 0.78   # → AMBIGUOUS quality; below this → no match

# geo_entity_type detection patterns (applied on normalized text)
_GEO_ENTITY_ADRESSE_PAT = re.compile(
    r'\b(AV|AVE|AVENUE|BD|BLVD|BOULEVARD|RUE|IMPASSE|ALLEE|PASSAGE|RUELLE|IMMEUBLE|IMM|N\s*\d+)\b'
)
_GEO_ENTITY_ROUTE_PAT = re.compile(
    r'\b(ROUTE|ROUTEX|RTE|AUTOROUTE|AUTOUROUTE|AUTROUTE|ATOROUTE|PEAGE|PONT|GP\s*\d*|GP\d+|RN\s*\d*|\d+\s*KM|KM\s*\d+|KM\d+|MC\s*\d+|ROCADE|CONTOURNEMENT)\b'
)
_GEO_ENTITY_INTERET_PAT = re.compile(
    r'\b(AEROPORT|GARE|PORT|HOPITAL|CLINIQUE|UNIVERSITE|STADE|TECHNOPOLE|FOIRE|MARCHE|SOUK|COMPLEXE)\b'
)
_GEO_ENTITY_ZONE_PAT = re.compile(
    r'\b(CITE|ZONE|ZI|ZA|ZIT|QUARTIER|QT|RESIDENCE|RES|LOTISSEMENT|LOT|BLOC|ENNASR|MONTPLAISIR)\b'
)

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_text(raw) -> str | None:
    """Normalize free text for matching while preserving business values."""
    if raw is None:
        return None
    if isinstance(raw, float) and math.isnan(raw):
        return None
    s = unicodedata.normalize("NFKD", str(raw))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s or s in _INVALID_TEXT:
        return None

    replacements = [
        (r"\bCITEE\b", "CITE"),
        (r"\bCTE\b", "CITE"),
        (r"\bEL\s+MANZEH\b", "EL MENZAH"),
        (r"\bEL\s+MENZEH\b", "EL MENZAH"),
        (r"\bMANZEH\b", "EL MENZAH"),
        (r"\bMENZEH\b", "EL MENZAH"),
        (r"\bENNASSER\b", "ENNASR"),
        (r"\bENNASER\b", "ENNASR"),
        (r"\bENNASSR\b", "ENNASR"),
        (r"\bLANDLOUS\b", "EL ANDALOUS"),
        (r"\bL ANDALOUS\b", "EL ANDALOUS"),
        (r"\bOUED\s+ELLILI\b", "OUED ELLIL"),
        (r"\bOUED\s+ELILI\b", "OUED ELLIL"),
        (r"\bELKRAM\b", "EL KRAM"),
    ]
    for pattern, replacement in replacements:
        s = re.sub(pattern, replacement, s)

    s = re.sub(r"\s+", " ", s).strip()
    return None if (not s or s in _INVALID_TEXT) else s

def normalize_cpost(raw) -> str | None:
    """Digits only, Tunisian range 0700-9999, zero-padded to 4 chars."""
    if raw is None:
        return None
    if isinstance(raw, float) and math.isnan(raw):
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    try:
        val = int(digits)
    except ValueError:
        return None
    return str(val).zfill(4) if 700 <= val <= 9999 else None


def postal_from_geo_label(raw) -> str | None:
    """Recover postal code from a geo label only when the signal is explicit."""
    if raw is None:
        return None
    if isinstance(raw, float) and math.isnan(raw):
        return None
    s = str(raw).strip().upper()
    if not s:
        return None

    if re.fullmatch(r"\d{3,4}", s):
        return normalize_cpost(s)

    explicit = re.search(r"\b(?:CP|CPOST|CODE POSTAL|POSTAL)\s*[:\-]?\s*(\d{3,4})\b", s)
    if explicit:
        return normalize_cpost(explicit.group(1))
    return None


def first_postal_candidate(code_postal_raw, *geo_values) -> str | None:
    """Find a valid postal code; non-postal geo labels must not be mined for digits."""
    code = normalize_cpost(code_postal_raw)
    if code:
        return code
    for value in geo_values:
        code = postal_from_geo_label(value)
        if code:
            return code
    return None

def clear_numeric_geo_label(value: str | None) -> str | None:
    """A pure number is not a readable region/governorate/locality label."""
    if value is None:
        return None
    return None if str(value).strip().isdigit() else value

def normalize_gouvernorat(raw) -> str | None:
    """Normalise et tente de valider un gouvernorat tunisien.
    Return the official name when recognized, otherwise keep normalized text
    (AMBIGUOUS quality is preferable to losing information).
    """
    s = normalize_text(raw)
    if s is None:
        return None
    if s in _VALID_GOVERNORATS:
        return s
    if s in _GOUVERNORAT_ALIASES:
        return _GOUVERNORAT_ALIASES[s]
    cleaned = re.sub(r"[\(\)\d]+$", "", s).strip()
    if cleaned in _VALID_GOVERNORATS:
        return cleaned
    if cleaned in _GOUVERNORAT_ALIASES:
        return _GOUVERNORAT_ALIASES[cleaned]
    return s  # not recognized; keep normalized source text


def _infer_pays(gouvernorat: str | None, code_postal: str | None) -> str | None:
    """Infer TUNISIE only when a reliable Tunisian signal exists."""
    if gouvernorat in _VALID_GOVERNORATS:
        return "TUNISIE"
    if code_postal is not None:
        try:
            if 700 <= int(code_postal) <= 9999:
                return "TUNISIE"
        except (ValueError, TypeError):
            pass
    return None


# ---------------------------------------------------------------------------
# Business key
# ---------------------------------------------------------------------------
def build_geo_key(
    pays:        str | None,
    gouvernorat: str | None,
    localite:    str | None,
    code_postal: str | None,
    _region_unused: str | None = None,  # backward-compat sentinel; ignored
) -> str:
    """pays|gouvernorat|localite|code_postal  (region excluded from key — derived column only)."""
    def _v(x) -> str:
        if x is None:
            return _KEY_UNKNOWN
        if isinstance(x, float) and math.isnan(x):
            return _KEY_UNKNOWN
        s = str(x).strip().upper()
        return s if s and s not in _INVALID_TEXT else _KEY_UNKNOWN

    return "|".join([_v(pays), _v(gouvernorat), _v(localite), _v(code_postal)])


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _discover_columns(engine, logger) -> dict[str, str | None]:
    """Discover available columns in stg_sinistres."""
    with engine.connect() as conn:
        available = set(
            row[0] for row in conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'staging'
                  AND table_name   = 'stg_sinistres'
            """)).fetchall()
        )
    result: dict[str, str | None] = {}
    for target, candidates in COLUMN_CANDIDATES.items():
        found = next((c for c in candidates if c in available), None)
        result[target] = found
        if found is None:
            logger.warning(f"  '{target}' not found in stg_sinistres (candidates: {candidates})")
        else:
            logger.info(f"  '{target}' -> {found}")
    return result


def _extract_sinistre(engine, logger) -> pd.DataFrame:
    """Lit les combinaisons geographicals distinctes depuis stg_sinistres."""
    col_map = _discover_columns(engine, logger)

    select_parts: list[str] = []
    for target, src in col_map.items():
        if src:
            select_parts.append(f"{src} AS {target}")
        else:
            select_parts.append(f"NULL::text AS {target}")

    sql = text(f"""
        SELECT DISTINCT {', '.join(select_parts)}
        FROM staging.stg_sinistres
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    logger.info(f"  {len(df)} combinaisons geo distinctes lues depuis {SOURCE_TABLE}")
    return df



# ---------------------------------------------------------------------------
# Business finalization
# ---------------------------------------------------------------------------

def to_unknown(value) -> str:
    """Convertit None/NaN/invalides vers UNKNOWN pour les colonnes metier finales."""
    if value is None:
        return _KEY_UNKNOWN
    if isinstance(value, float) and math.isnan(value):
        return _KEY_UNKNOWN
    s = str(value).strip().upper()
    return s if s and s not in _INVALID_TEXT else _KEY_UNKNOWN


def finalize_business_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Interdit les NULL dans les colonnes metier finales de dim_geo.
    Region is always derived from the resolved gouvernorat via _REGION_FROM_GOUVERNORAT —
    never from REGSINI or any reference CSV entry.
    """
    df = df.copy()
    for col in ["pays", "gouvernorat", "localite", "code_postal"]:
        df[col] = df[col].map(to_unknown)
    # Authoritative region derivation: gouvernorat → region (fixed table, 24 governorates)
    df["region"] = df["gouvernorat"].map(
        lambda g: _REGION_FROM_GOUVERNORAT.get(g, _KEY_UNKNOWN)
    )
    df["geo_key"] = df.apply(
        lambda r: build_geo_key(r["pays"], r["gouvernorat"], r["localite"], r["code_postal"]),
        axis=1,
    )
    return df


# ---------------------------------------------------------------------------
# Reference data and approved corrections
# ---------------------------------------------------------------------------

_APPROVED_STATUSES_TO_APPLY = frozenset({"APPROVED"})
_IGNORED_APPROVAL_STATUSES = frozenset({"REJECTED", "KEEP_SOURCE", "MANUAL_REVIEW", "PENDING"})


def _standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def _load_geo_reference(logger) -> tuple[pd.DataFrame, dict]:
    """Charge le referentiel tunisien pour tracabilite et validation de presence."""
    metrics = {"n_reference_rows": 0, "reference_available": False}
    if not GEO_REFERENCE_PATH.exists():
        logger.warning(f"  Referentiel geo absent : {GEO_REFERENCE_PATH}")
        return pd.DataFrame(), metrics

    df_ref = pd.read_csv(GEO_REFERENCE_PATH, dtype=str, keep_default_na=False)
    df_ref = _standardize_columns(df_ref)
    required = {"localite", "delegation", "gouvernorat", "region", "aliases", "confidence"}
    missing = sorted(required.difference(df_ref.columns))
    if missing:
        raise RuntimeError(f"Referentiel geo incomplet {GEO_REFERENCE_PATH} : colonnes manquantes {missing}")
    if "code_postal" not in df_ref.columns:
        df_ref["code_postal"] = ""

    metrics["n_reference_rows"] = len(df_ref)
    metrics["reference_available"] = True
    logger.info(f"  referentiel geo charge : {len(df_ref)} lignes ({GEO_REFERENCE_PATH})")
    return df_ref, metrics

def _load_geo_alias(logger) -> tuple[dict[str, dict], dict]:
    """Load ref_geo_alias.csv — manual typo/variant dictionary for ETL normalization."""
    metrics = {"n_geo_alias_entries": 0}
    if not GEO_ALIAS_PATH.exists():
        logger.warning(f"  Alias file absent: {GEO_ALIAS_PATH}")
        return {}, metrics
    df = pd.read_csv(GEO_ALIAS_PATH, dtype=str, keep_default_na=False)
    df.columns = [c.strip().lower() for c in df.columns]
    index: dict[str, dict] = {}
    for _, row in df.iterrows():
        if str(row.get("is_active", "1")).strip().upper() in ("0", "FALSE", "NO", "N"):
            continue
        key = normalize_text(row.get("alias_source", ""))
        if not key:
            continue
        try:
            score = float(str(row.get("confidence_score", "0.95")).replace(",", "."))
        except (ValueError, TypeError):
            score = 0.95
        index[key] = {
            "localite": normalize_text(row.get("localite_reference", "")) or "UNKNOWN",
            "gouvernorat": normalize_gouvernorat(row.get("gouvernorat_reference", "")) or "",
            "region": normalize_text(row.get("region_reference", "")) or "",
            "delegation": None,
            "code_postal": None,
            "confidence": max(0.0, min(1.0, score)),
        }
    metrics["n_geo_alias_entries"] = len(index)
    logger.info(f"  alias dictionary: {len(index)} active entries ({GEO_ALIAS_PATH.name})")
    return index, metrics


def _load_postal_reference(logger) -> tuple[pd.DataFrame, dict]:
    """Load the separate postal reference used to validate/fill postal codes."""
    metrics = {"n_postal_reference_rows": 0, "postal_reference_available": False}
    columns = [
        "code_postal",
        "bureau_postal",
        "localite",
        "delegation",
        "gouvernorat",
        "region",
        "aliases",
        "source",
        "confidence",
    ]
    if not GEO_POSTAL_REFERENCE_PATH.exists():
        GEO_POSTAL_REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=columns).to_csv(GEO_POSTAL_REFERENCE_PATH, index=False, encoding="utf-8-sig")
        logger.warning(f"  postal reference template created: {GEO_POSTAL_REFERENCE_PATH}")
        return pd.DataFrame(columns=columns), metrics

    # DimRegion.csv may be semicolon-separated and contains only:
    # Gouvernorat;Delegation;Localite;Code postal
    # We standardize it here to the internal postal-reference contract.
    df_ref = pd.read_csv(GEO_POSTAL_REFERENCE_PATH, dtype=str, keep_default_na=False, sep=None, engine="python")
    df_ref = df_ref.copy()
    df_ref.columns = [str(c).strip().lower().replace(" ", "_") for c in df_ref.columns]

    rename_map = {
        "code_postal": "code_postal",
        "code_post": "code_postal",
        "codepostal": "code_postal",
        "gouvernorat": "gouvernorat",
        "delegation": "delegation",
        "délégation": "delegation",
        "localite": "localite",
        "localité": "localite",
    }
    df_ref = df_ref.rename(columns={c: rename_map.get(c, c) for c in df_ref.columns})

    # If the user supplies raw DimRegion.csv, enrich missing internal columns.
    if {"gouvernorat", "delegation", "localite", "code_postal"}.issubset(df_ref.columns):
        df_ref["gouvernorat"] = df_ref["gouvernorat"].map(normalize_gouvernorat)
        df_ref["delegation"] = df_ref["delegation"].map(normalize_text)
        df_ref["localite"] = df_ref["localite"].map(normalize_text)
        df_ref["code_postal"] = df_ref["code_postal"].map(normalize_cpost)
        df_ref = df_ref.dropna(subset=["gouvernorat", "localite", "code_postal"])
        df_ref = df_ref[df_ref["gouvernorat"].isin(_VALID_GOVERNORATS)].copy()
        df_ref["region"] = df_ref["gouvernorat"].map(_REGION_FROM_GOUVERNORAT)
        if "bureau_postal" not in df_ref.columns:
            df_ref["bureau_postal"] = ""
        if "aliases" not in df_ref.columns:
            df_ref["aliases"] = ""
        if "source" not in df_ref.columns:
            df_ref["source"] = "DIMREGION"
        if "confidence" not in df_ref.columns:
            df_ref["confidence"] = "HIGH"
        df_ref = df_ref[columns].drop_duplicates().reset_index(drop=True)

    missing = sorted(set(columns).difference(df_ref.columns))
    if missing:
        raise RuntimeError(
            f"Postal reference incomplete {GEO_POSTAL_REFERENCE_PATH}: missing columns {missing}"
        )

    metrics["n_postal_reference_rows"] = len(df_ref)
    metrics["postal_reference_available"] = True
    logger.info(f"  postal reference loaded: {len(df_ref)} rows ({GEO_POSTAL_REFERENCE_PATH})")
    return df_ref, metrics

def _reference_confidence_value(raw) -> float:
    s = normalize_text(raw)
    if s is None:
        return 1.0
    if s == "HIGH":
        return 1.0
    if s == "MEDIUM":
        return 0.8
    if s == "LOW":
        return 0.6
    try:
        value = float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return 1.0
    if value > 1:
        value = value / 100
    return max(0.0, min(1.0, value))


def _reference_alias_terms(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, float) and math.isnan(raw):
        return []
    terms: list[str] = []
    for part in re.split(r"[|;]", str(raw)):
        term = normalize_text(part)
        if term and term not in terms:
            terms.append(term)
    return terms


def _generated_postal_alias_terms(raw) -> list[str]:
    """Conservative postal aliases from official locality labels only."""
    term = normalize_text(raw)
    if not term or _is_generic_localite(term):
        return []

    aliases: list[str] = []

    def add(value: str | None) -> None:
        value = normalize_text(value)
        if value and not _is_generic_localite(value) and value not in aliases:
            aliases.append(value)

    add(term)
    add(re.sub(r"\s+", "", term))

    if term.startswith("CITE "):
        base = term[5:].strip()
        add(base)
        add(re.sub(r"\s+", "", base))
    else:
        add(f"CITE {term}")
        add(re.sub(r"\s+", "", f"CITE {term}"))

    compact_number = re.match(r"(.+?)(\d+)$", term)
    if compact_number:
        spaced = f"{compact_number.group(1).strip()} {compact_number.group(2)}"
        add(spaced)
        add(re.sub(r"\s+", "", spaced))
        add(f"CITE {spaced}")
        add(re.sub(r"\s+", "", f"CITE {spaced}"))

    without_suffix = re.sub(r"\s+\d+$", "", term).strip()
    if without_suffix and without_suffix != term:
        add(without_suffix)
        add(re.sub(r"\s+", "", without_suffix))
        add(f"CITE {without_suffix}")
        add(re.sub(r"\s+", "", f"CITE {without_suffix}"))

    variant_rules = [
        ("MEJEZ", "MEDJEZ"),
        ("MEJEZ", "MJEZ"),
        ("EL BAB", "EL BEB"),
        ("EL BAB", "ELBEB"),
        ("BORJ", "BORDJ"),
        ("CEDRIA", "CEDIA"),
        ("BOU CHEMMA", "BOUCHEMMA"),
        ("CHATT", "CHOTT"),
        ("LA MANNOUBA", "LA MANOUBA"),
        ("MANNOUBA", "MANOUBA"),
        ("KHEZAMA", "KHEZEMA"),
        ("KALAA ESSGHIRA", "KALAA SGHIRA"),
        ("KALAA ESSGHIRA", "KALAA SOGHRA"),
        ("SIDI JEDIDI", "SIDI JEDID"),
        ("DENDEN", "DEN DEN"),
        ("ZERAMDINE", "ZRAMDINE"),
        ("OUESLATIA", "OUESSLATIA"),
    ]
    for source, replacement in variant_rules:
        if source in term:
            variant = term.replace(source, replacement)
            add(variant)
            add(re.sub(r"\s+", "", variant))
            if variant.startswith("CITE "):
                add(variant[5:].strip())
            else:
                add(f"CITE {variant}")

    return aliases

def _is_generic_localite(term: str | None) -> bool:
    if term is None:
        return True
    if term in _INVALID_TEXT or term in _GENERIC_LOCALITE_TERMS:
        return True
    if len(term) < 3:
        return True
    if term.isdigit():
        return True
    return False


def _classify_geo_entity_type(source_localite: str | None) -> str:
    """Classify a normalized localite string into a geo entity category."""
    if source_localite is None or _is_generic_localite(source_localite):
        return "UNKNOWN"
    s = source_localite.upper()
    if s in _VALID_GOVERNORATS:
        return "GOUVERNORAT"
    if _GEO_ENTITY_ADRESSE_PAT.search(s):
        return "ADRESSE_PARTIELLE"
    if _GEO_ENTITY_ROUTE_PAT.search(s):
        return "ROUTE_AUTOROUTE"
    if _GEO_ENTITY_INTERET_PAT.search(s):
        return "POINT_INTERET"
    if _GEO_ENTITY_ZONE_PAT.search(s):
        return "QUARTIER_ZONE"
    return "LOCALITE"


def _fuzzy_match_localite(
    term: str,
    gouvernorat: str | None,
    reference_indexes: dict,
) -> tuple[dict | None, float, str]:
    """Fuzzy-match term against reference localite/alias terms (difflib ratio).

    Returns (best_ref_collapsed, score, index_name) or (None, 0.0, "") when
    best score is below _FUZZY_LOW_THRESHOLD.

    Strategy:
      - Prefer matches within the same gouvernorat.
      - Cross-gouvernorat matches only accepted at _FUZZY_HIGH_THRESHOLD and
        only when the reference term resolves to a single location.
      - Generic or too-short terms are skipped on both sides.
    """
    from difflib import SequenceMatcher

    if not term or _is_generic_localite(term):
        return None, 0.0, ""

    best_score: float = _FUZZY_LOW_THRESHOLD - 0.001
    best_ref:   dict | None = None
    best_idx:   str = ""

    for idx_name in ("localite", "alias"):
        for ref_term, refs in reference_indexes[idx_name].items():
            if _is_generic_localite(ref_term):
                continue
            score = SequenceMatcher(None, term, ref_term).ratio()
            if score <= best_score:
                continue
            collapsed = _collapse_reference_candidates(refs)
            if not collapsed:
                continue
            if gouvernorat in _VALID_GOVERNORATS:
                gov_refs = [r for r in collapsed if r.get("gouvernorat") == gouvernorat]
                if gov_refs:
                    best_score = score
                    best_ref   = gov_refs[0]
                    best_idx   = idx_name
                elif score >= _FUZZY_HIGH_THRESHOLD and len(collapsed) == 1:
                    # Cross-governorate only when highly confident and unambiguous
                    best_score = score
                    best_ref   = collapsed[0]
                    best_idx   = idx_name
            elif len(collapsed) == 1:
                best_score = score
                best_ref   = collapsed[0]
                best_idx   = idx_name

    if best_score < _FUZZY_LOW_THRESHOLD or best_ref is None:
        return None, 0.0, ""
    return best_ref, best_score, best_idx


def _ref_base_key(ref: dict) -> tuple[str, str, str, str]:
    return (
        to_unknown(ref.get("region")),
        to_unknown(ref.get("gouvernorat")),
        to_unknown(ref.get("delegation")),
        to_unknown(ref.get("localite")),
    )


def _collapse_reference_candidates(candidates: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str, str], dict] = {}
    for ref in candidates:
        key = _ref_base_key(ref)
        current = grouped.get(key)
        code = normalize_cpost(ref.get("code_postal"))
        if current is None:
            current = {
                "region": ref.get("region"),
                "gouvernorat": ref.get("gouvernorat"),
                "delegation": ref.get("delegation"),
                "localite": ref.get("localite"),
                "code_postal_values": set(),
                "confidence": float(ref.get("confidence", 1.0)),
            }
            grouped[key] = current
        current["confidence"] = max(current["confidence"], float(ref.get("confidence", 1.0)))
        if code:
            current["code_postal_values"].add(code)

    collapsed: list[dict] = []
    for ref in grouped.values():
        codes = sorted(ref.pop("code_postal_values"))
        ref["code_postal"] = codes[0] if len(codes) == 1 else None
        collapsed.append(ref)
    return collapsed


def _build_reference_resolver_indexes(df_ref: pd.DataFrame) -> tuple[dict, dict]:
    """Build administrative geography indexes. Postal indexes are loaded separately."""
    metrics = {
        "n_reference_localite_terms": 0,
        "n_reference_alias_terms": 0,
        "n_reference_delegation_terms": 0,
        "n_reference_ambiguous_localite_terms": 0,
        "n_reference_governorate_regions": 0,
    }
    indexes = {
        "localite": {},
        "alias": {},
        "delegation": {},
        "postal": {},
        "postal_localite": {},
        "postal_alias": {},
        "postal_delegation": {},
        "governorate_region": {},
    }
    if df_ref is None or df_ref.empty:
        return indexes, metrics

    governorate_regions: dict[str, set[str]] = {}
    for idx, row in df_ref.iterrows():
        confidence = _reference_confidence_value(row.get("confidence"))
        if confidence < 0.95:
            continue

        aliases = _reference_alias_terms(row.get("aliases"))
        ref = {
            "reference_id": int(idx),
            "region": normalize_text(row.get("region")),
            "gouvernorat": normalize_gouvernorat(row.get("gouvernorat")),
            "delegation": normalize_text(row.get("delegation")),
            "localite": normalize_text(row.get("localite")),
            "code_postal": None,
            "confidence": confidence,
        }
        if ref["gouvernorat"] not in _VALID_GOVERNORATS:
            continue
        if not ref["localite"] and not ref["delegation"]:
            continue

        if ref["region"]:
            governorate_regions.setdefault(ref["gouvernorat"], set()).add(ref["region"])

        if ref["localite"] and not _is_generic_localite(ref["localite"]):
            indexes["localite"].setdefault(ref["localite"], []).append(ref)
        for alias in aliases:
            if not _is_generic_localite(alias):
                indexes["alias"].setdefault(alias, []).append(ref)
        if ref["delegation"] and not _is_generic_localite(ref["delegation"]):
            indexes["delegation"].setdefault(ref["delegation"], []).append(ref)

    indexes["governorate_region"] = {
        gov: sorted(regions)[0]
        for gov, regions in governorate_regions.items()
        if len(regions) == 1
    }
    metrics["n_reference_localite_terms"] = len(indexes["localite"])
    metrics["n_reference_alias_terms"] = len(indexes["alias"])
    metrics["n_reference_delegation_terms"] = len(indexes["delegation"])
    metrics["n_reference_governorate_regions"] = len(indexes["governorate_region"])
    metrics["n_reference_ambiguous_localite_terms"] = sum(
        1
        for refs in indexes["localite"].values()
        if len({_ref_base_key(ref) for ref in _collapse_reference_candidates(refs)}) > 1
    )
    return indexes, metrics


def _build_postal_resolver_indexes(df_postal: pd.DataFrame) -> tuple[dict, dict]:
    """Build postal-code indexes from the dedicated postal reference."""
    metrics = {
        "n_postal_reference_codes": 0,
        "n_postal_reference_localite_terms": 0,
        "n_postal_reference_delegation_terms": 0,
        "n_postal_reference_alias_terms": 0,
        "n_postal_reference_usable_rows": 0,
    }
    indexes = {
        "postal": {},
        "postal_localite": {},
        "postal_alias": {},
        "postal_delegation": {},
    }
    if df_postal is None or df_postal.empty:
        return indexes, metrics

    for idx, row in df_postal.iterrows():
        confidence = _reference_confidence_value(row.get("confidence"))
        if confidence < 0.95:
            continue
        ref = {
            "reference_id": int(idx),
            "region": normalize_text(row.get("region")),
            "gouvernorat": normalize_gouvernorat(row.get("gouvernorat")),
            "delegation": normalize_text(row.get("delegation")),
            "localite": normalize_text(row.get("localite")),
            "bureau_postal": normalize_text(row.get("bureau_postal")),
            "code_postal": normalize_cpost(row.get("code_postal")),
            "confidence": confidence,
            "source": normalize_text(row.get("source")),
        }
        if ref["code_postal"] is None:
            continue
        if ref["gouvernorat"] not in _VALID_GOVERNORATS:
            continue
        if _postal_prefix_conflict(ref["code_postal"], ref["gouvernorat"]):
            continue
        if not ref["localite"] and not ref["delegation"] and not ref["bureau_postal"]:
            continue

        metrics["n_postal_reference_usable_rows"] += 1
        indexes["postal"].setdefault(ref["code_postal"], []).append(ref)
        if ref["localite"] and not _is_generic_localite(ref["localite"]):
            indexes["postal_localite"].setdefault((ref["gouvernorat"], ref["localite"]), []).append(ref)
        if ref["delegation"] and not _is_generic_localite(ref["delegation"]):
            indexes["postal_delegation"].setdefault((ref["gouvernorat"], ref["delegation"]), []).append(ref)
        generated_aliases = []
        for source_term in [row.get("aliases"), ref.get("localite"), ref.get("bureau_postal")]:
            if source_term == row.get("aliases"):
                for alias in _reference_alias_terms(source_term):
                    if alias not in generated_aliases:
                        generated_aliases.append(alias)
            else:
                for alias in _generated_postal_alias_terms(source_term):
                    if alias not in generated_aliases:
                        generated_aliases.append(alias)
        for alias in generated_aliases:
            if not _is_generic_localite(alias) and alias != ref.get("localite"):
                indexes["postal_alias"].setdefault((ref["gouvernorat"], alias), []).append(ref)

    metrics["n_postal_reference_codes"] = len(indexes["postal"])
    metrics["n_postal_reference_localite_terms"] = len(indexes["postal_localite"])
    metrics["n_postal_reference_delegation_terms"] = len(indexes["postal_delegation"])
    metrics["n_postal_reference_alias_terms"] = len(indexes["postal_alias"])
    return indexes, metrics


def _merge_postal_indexes(reference_indexes: dict, postal_indexes: dict) -> dict:
    merged = {key: value.copy() if isinstance(value, dict) else value for key, value in reference_indexes.items()}
    for key in ["postal", "postal_localite", "postal_alias", "postal_delegation"]:
        merged[key] = postal_indexes.get(key, {})
    return merged

def _source_geo_key_from_values(
    source_gouvernorat: str | None,
    source_localite: str | None,
    source_code_postal: str | None,
) -> str:
    source_pays = _infer_pays(source_gouvernorat, source_code_postal)
    return build_geo_key(source_pays, source_gouvernorat, source_localite, source_code_postal)


def _source_values_from_row(row: pd.Series) -> dict:
    code_postal = first_postal_candidate(
        row.get("code_postal"),
        row.get("gouvernorat"),
        row.get("localite"),
    )
    return {
        "source_region":      clear_numeric_geo_label(normalize_text(row.get("regsini_hint"))),
        "source_gouvernorat": clear_numeric_geo_label(normalize_gouvernorat(row.get("gouvernorat"))),
        "source_localite":    clear_numeric_geo_label(normalize_text(row.get("localite"))),
        "source_code_postal": code_postal,
        "source_rue":         clear_numeric_geo_label(normalize_text(row.get("rue"))),
    }


def _candidate_summary(candidates: list[dict], limit: int = 4) -> str:
    parts = []
    for ref in candidates[:limit]:
        parts.append(
            f"{to_unknown(ref.get('region'))}/{to_unknown(ref.get('gouvernorat'))}/"
            f"{to_unknown(ref.get('delegation'))}/{to_unknown(ref.get('localite'))}/"
            f"{to_unknown(ref.get('code_postal'))}"
        )
    return " | ".join(parts)


def _unique_reference_postal_codes(refs: list[dict]) -> list[str]:
    return sorted({code for ref in refs if (code := normalize_cpost(ref.get("code_postal")))})


def _postal_reference_summary(refs: list[dict], limit: int = 5) -> str:
    parts = []
    for ref in refs[:limit]:
        parts.append(
            f"{to_unknown(ref.get('gouvernorat'))}/{to_unknown(ref.get('delegation'))}/"
            f"{to_unknown(ref.get('localite'))}/{to_unknown(ref.get('code_postal'))}"
        )
    return " | ".join(parts)


def _postal_prefix_conflict(code_postal: str | None, gouvernorat: str | None) -> bool:
    code = normalize_cpost(code_postal)
    if code is None or gouvernorat not in _POSTAL_PREFIXES_BY_GOUVERNORAT:
        return False
    return code[:2] not in _POSTAL_PREFIXES_BY_GOUVERNORAT[gouvernorat]


def _postal_conflict_result(code_postal: str, gouvernorat: str | None, method: str, summary: str = "") -> dict:
    expected = sorted(_POSTAL_PREFIXES_BY_GOUVERNORAT.get(gouvernorat, []))
    expected_text = ", ".join(expected) if expected else "UNKNOWN"
    return {
        "code_postal": None,
        "postal_code_status": "POSTAL_CONFLICT_GOVERNORATE_PREFIX",
        "postal_code_method": method,
        "postal_code_reason": (
            f"candidate postal code {code_postal} contradicts governorate {to_unknown(gouvernorat)} "
            f"expected prefixes {expected_text}"
        ),
        "postal_candidate_summary": summary,
    }

def _source_postal_status(
    source_code: str,
    final_gouvernorat: str | None,
    final_localite: str | None,
    final_delegation: str | None,
    reference_indexes: dict,
) -> tuple[str, str]:
    refs = reference_indexes.get("postal", {}).get(source_code, [])
    if not refs or final_gouvernorat not in _VALID_GOVERNORATS:
        return "POSTAL_SOURCE_UNCONFIRMED", "valid source postal code kept; no postal reference validation available"

    refs_same_gov = [ref for ref in refs if ref.get("gouvernorat") == final_gouvernorat]
    ref_governorates = {ref.get("gouvernorat") for ref in refs if ref.get("gouvernorat")}
    if refs_same_gov:
        expected_terms = [
            term
            for term in [final_localite, final_delegation]
            if term and not _is_generic_localite(term)
        ]
        if not expected_terms:
            return "POSTAL_SOURCE_PREFIX_ONLY", "source postal code is compatible with governorate, but not locality-confirmed"

        for ref in refs_same_gov:
            ref_terms = {
                term
                for term in [ref.get("localite"), ref.get("delegation"), ref.get("bureau_postal")]
                if term and not _is_generic_localite(term)
            }
            if any(term in ref_terms for term in expected_terms):
                return "POSTAL_SOURCE_CONFIRMED_REFERENCE", "source postal code confirmed by postal reference and resolved place"

        return "POSTAL_SOURCE_PREFIX_ONLY", "source postal code is compatible with governorate, but not resolved locality/delegation"
    if ref_governorates:
        return "POSTAL_AMBIGUOUS_SOURCE_CONFLICT", "source postal code exists in reference under another governorate"
    return "POSTAL_SOURCE_UNCONFIRMED", "valid source postal code kept"


def _postal_lookup_result(reference_indexes: dict, index_name: str, key: tuple[str, str], status_name: str) -> dict | None:
    refs = reference_indexes.get(index_name, {}).get(key, [])
    if not refs:
        return None
    codes = _unique_reference_postal_codes(refs)
    if len(codes) == 1:
        gouvernorat = key[0]
        summary = _postal_reference_summary(refs)
        if _postal_prefix_conflict(codes[0], gouvernorat):
            return _postal_conflict_result(codes[0], gouvernorat, status_name, summary)
        return {
            "code_postal": codes[0],
            "postal_code_status": f"POSTAL_{status_name}",
            "postal_code_method": status_name,
            "postal_code_reason": "unique trusted postal code found in dedicated postal reference",
            "postal_candidate_summary": summary,
        }
    if len(codes) > 1:
        return {
            "code_postal": None,
            "postal_code_status": f"POSTAL_AMBIGUOUS_{status_name}",
            "postal_code_method": status_name,
            "postal_code_reason": f"multiple trusted postal codes found: {', '.join(codes)}",
            "postal_candidate_summary": _postal_reference_summary(refs),
        }
    return None


def _resolve_postal_code(
    source: dict,
    reference_indexes: dict,
    final_gouvernorat: str | None,
    final_localite: str | None,
    final_delegation: str | None = None,
    approved_code: str | None = None,
    allow_reference: bool = True,
) -> dict:
    source_code = normalize_cpost(source.get("source_code_postal"))
    if source_code:
        if _postal_prefix_conflict(source_code, final_gouvernorat):
            return _postal_conflict_result(source_code, final_gouvernorat, "SOURCE_CPOSTSINI")
        status, reason = _source_postal_status(
            source_code,
            final_gouvernorat,
            final_localite,
            final_delegation,
            reference_indexes,
        )
        return {
            "code_postal": source_code,
            "postal_code_status": status,
            "postal_code_method": "SOURCE_CPOSTSINI",
            "postal_code_reason": reason,
            "postal_candidate_summary": "",
        }

    approved = normalize_cpost(approved_code)
    if approved:
        if _postal_prefix_conflict(approved, final_gouvernorat):
            return _postal_conflict_result(approved, final_gouvernorat, "APPROVED_CORRECTIONS", "approved correction")
        return {
            "code_postal": approved,
            "postal_code_status": "POSTAL_APPROVED_CORRECTION",
            "postal_code_method": "APPROVED_CORRECTIONS",
            "postal_code_reason": "approved correction contains a real 4-digit postal code",
            "postal_candidate_summary": "approved correction",
        }

    if not allow_reference:
        return {
            "code_postal": None,
            "postal_code_status": "POSTAL_AMBIGUOUS_GEOGRAPHY",
            "postal_code_method": "REFERENCE_NOT_USED",
            "postal_code_reason": "geography is ambiguous, so postal code was not inferred",
            "postal_candidate_summary": "",
        }

    if final_gouvernorat not in _VALID_GOVERNORATS:
        return {
            "code_postal": None,
            "postal_code_status": "POSTAL_MISSING_REFERENCE",
            "postal_code_method": "NO_GOVERNORATE",
            "postal_code_reason": "no official governorate available for postal-code lookup",
            "postal_candidate_summary": "",
        }

    localite_terms = []
    for term in [final_localite, source.get("source_localite")]:
        if term and not _is_generic_localite(term) and term not in localite_terms:
            localite_terms.append(term)
    for term in localite_terms:
        result = _postal_lookup_result(
            reference_indexes,
            "postal_localite",
            (final_gouvernorat, term),
            "REFERENCE_EXACT_LOCALITE",
        )
        if result is not None:
            return result

    alias_terms = []
    for term in [source.get("source_localite"), source.get("source_region"), final_localite]:
        if term and not _is_generic_localite(term) and term not in alias_terms:
            alias_terms.append(term)
    for term in alias_terms:
        result = _postal_lookup_result(
            reference_indexes,
            "postal_alias",
            (final_gouvernorat, term),
            "REFERENCE_ALIAS",
        )
        if result is not None:
            return result

    delegation_terms = []
    for term in [final_delegation, source.get("source_region"), source.get("source_localite")]:
        if term and not _is_generic_localite(term) and term not in delegation_terms:
            delegation_terms.append(term)
    for term in delegation_terms:
        result = _postal_lookup_result(
            reference_indexes,
            "postal_delegation",
            (final_gouvernorat, term),
            "REFERENCE_DELEGATION",
        )
        if result is not None:
            return result

    return {
        "code_postal": None,
        "postal_code_status": "POSTAL_MISSING_REFERENCE",
        "postal_code_method": "REFERENCE_LOOKUP",
        "postal_code_reason": "no unique trusted postal code found for governorate/locality/delegation/alias",
        "postal_candidate_summary": "",
    }

def _select_reference_candidate(
    candidates: list[dict],
    source_gouvernorat: str | None,
    source_code_postal: str | None,
) -> tuple[dict | None, str, list[dict]]:
    collapsed = _collapse_reference_candidates(candidates)
    if not collapsed:
        return None, "NO_REFERENCE_CANDIDATE", []

    if source_code_postal:
        same_code = [ref for ref in collapsed if ref.get("code_postal") == source_code_postal]
        if len(same_code) == 1:
            return same_code[0], "DISAMBIGUATED_BY_POSTAL_CODE", collapsed

    if source_gouvernorat in _VALID_GOVERNORATS:
        same_gov = [ref for ref in collapsed if ref.get("gouvernorat") == source_gouvernorat]
        if len(same_gov) == 1:
            return same_gov[0], "DISAMBIGUATED_BY_SOURCE_GOUVERNORAT", collapsed
        if len(same_gov) > 1:
            return None, "AMBIGUOUS_WITHIN_SOURCE_GOUVERNORAT", collapsed

    if len(collapsed) == 1:
        if source_gouvernorat in _VALID_GOVERNORATS and collapsed[0].get("gouvernorat") != source_gouvernorat:
            return collapsed[0], "UNIQUE_REFERENCE_CONFLICTS_WITH_SOURCE_GOUVERNORAT", collapsed
        return collapsed[0], "UNIQUE_REFERENCE_MATCH", collapsed

    return None, "AMBIGUOUS_REFERENCE_MATCH", collapsed


def _find_reference_candidate(
    source: dict,
    reference_indexes: dict,
    alias_dict: dict | None = None,
) -> tuple[dict | None, str, str, list[dict]]:
    localite_terms = []
    source_localite = source.get("source_localite")
    source_region = source.get("source_region")
    if source_localite and not _is_generic_localite(source_localite):
        localite_terms.append(source_localite)
    elif source_region and not _is_generic_localite(source_region):
        # REGSINI is dirty and can contain a locality, but only use it as
        # locality when CITESINI does not provide a usable locality signal.
        localite_terms.append(source_region)

    for term in localite_terms:
        candidates = reference_indexes["localite"].get(term, [])
        if candidates:
            selected, status, collapsed = _select_reference_candidate(
                candidates, source.get("source_gouvernorat"), source.get("source_code_postal")
            )
            return selected, "EXACT_LOCALITE", status, collapsed

    for term in localite_terms:
        candidates = reference_indexes["alias"].get(term, [])
        if candidates:
            selected, status, collapsed = _select_reference_candidate(
                candidates, source.get("source_gouvernorat"), source.get("source_code_postal")
            )
            return selected, "ALIAS_LOCALITE", status, collapsed

    if alias_dict:
        for term in localite_terms:
            alias_match = alias_dict.get(term)
            if alias_match:
                return alias_match, "ALIAS_MANUEL", "ALIAS_MANUEL_MATCH", [alias_match]

    delegation_terms = []
    for term in [source.get("source_localite"), source.get("source_region")]:
        if term and not _is_generic_localite(term) and term not in delegation_terms:
            delegation_terms.append(term)
    for term in delegation_terms:
        candidates = reference_indexes["delegation"].get(term, [])
        if candidates:
            selected, status, collapsed = _select_reference_candidate(
                candidates, source.get("source_gouvernorat"), source.get("source_code_postal")
            )
            return selected, "EXACT_DELEGATION", status, collapsed

    source_code_postal = source.get("source_code_postal")
    if source_code_postal:
        candidates = reference_indexes["postal"].get(source_code_postal, [])
        if candidates:
            selected, status, collapsed = _select_reference_candidate(
                candidates, source.get("source_gouvernorat"), source_code_postal
            )
            return selected, "POSTAL_CODE", status, collapsed

    # Fuzzy matching — only for terms that look like actual locality names,
    # not addresses, routes, or other partial geographic labels.
    entity_type = _classify_geo_entity_type(source_localite or source_region)
    if entity_type in ("LOCALITE", "GOUVERNORAT", "UNKNOWN"):
        fuzzy_terms = [t for t in localite_terms if t]
        if not fuzzy_terms and source_region and not _is_generic_localite(source_region):
            fuzzy_terms = [source_region]
        source_gouvernorat = source.get("source_gouvernorat")
        for term in fuzzy_terms:
            best_ref, fuzzy_score, fuzzy_idx = _fuzzy_match_localite(
                term, source_gouvernorat, reference_indexes
            )
            if best_ref is not None:
                method_name = "FUZZY_LOCALITE" if fuzzy_idx == "localite" else "FUZZY_ALIAS"
                if fuzzy_score >= _FUZZY_HIGH_THRESHOLD:
                    # High confidence: try to resolve uniquely
                    selected, status, collapsed = _select_reference_candidate(
                        [best_ref],
                        source_gouvernorat,
                        source.get("source_code_postal"),
                    )
                    if selected is not None:
                        return selected, method_name, f"{status}|fuzzy_score={fuzzy_score:.3f}", [best_ref]
                # Low confidence or ambiguous high-confidence: return as candidate only
                # → caller will produce AMBIGUOUS_FUZZY_* status
                return None, method_name, f"FUZZY_AMBIGUOUS|fuzzy_score={fuzzy_score:.3f}", [best_ref]

    return None, "NO_REFERENCE", "NO_REFERENCE_MATCH", []


def _geo_quality_from_resolution(
    resolution_status: str,
    gouvernorat: str | None,
    localite: str | None,
    region: str | None = None,
    code_postal: str | None = None,
    pays: str | None = None,
    postal_code_status: str | None = None,
) -> str:
    if resolution_status == "UNKNOWN":
        return "UNKNOWN"
    if (resolution_status.startswith("AMBIGUOUS") or resolution_status.startswith("UNRESOLVED")
            or resolution_status == "CONFLICT_CORRECTED_REFERENCE"):
        return "AMBIGUOUS"
    if postal_code_status and postal_code_status.startswith("POSTAL_AMBIGUOUS"):
        return "AMBIGUOUS"
    if postal_code_status and postal_code_status.startswith("POSTAL_CONFLICT"):
        return "AMBIGUOUS"

    gov_valid = gouvernorat in _VALID_GOVERNORATS
    pays_valid = to_unknown(pays) == "TUNISIE" or gov_valid
    region_known = to_unknown(region) != _KEY_UNKNOWN
    localite_known = to_unknown(localite) != _KEY_UNKNOWN
    postal_valid = normalize_cpost(code_postal) is not None
    postal_confirmed = postal_code_status in {
        "POSTAL_SOURCE_CONFIRMED_REFERENCE",
        "POSTAL_APPROVED_CORRECTION",
        "POSTAL_REFERENCE_EXACT_LOCALITE",
        "POSTAL_REFERENCE_DELEGATION",
        "POSTAL_REFERENCE_ALIAS",
    }

    if pays_valid and gov_valid and region_known and localite_known and postal_valid and postal_confirmed:
        return "VALIDATED"
    if pays_valid and gov_valid and (region_known or localite_known):
        return "PARTIAL"
    if postal_valid:
        return "PARTIAL"
    if gov_valid or localite_known or region_known:
        return "AMBIGUOUS"
    return "UNKNOWN"

def _empty_resolution(source: dict, source_geo_key: str, status: str, reason: str) -> dict:
    final_gouvernorat = source.get("source_gouvernorat") if source.get("source_gouvernorat") in _VALID_GOVERNORATS else None
    final_localite = source.get("source_localite")
    final_region = None
    final_code_postal = None
    final_pays = _infer_pays(final_gouvernorat, final_code_postal)
    postal_status = "POSTAL_MISSING_REFERENCE" if final_gouvernorat or final_localite else "POSTAL_NOT_APPLICABLE"
    quality = _geo_quality_from_resolution(
        status,
        final_gouvernorat,
        final_localite,
        final_region,
        final_code_postal,
        final_pays,
        postal_status,
    )
    if status == "UNKNOWN":
        final_gouvernorat = None
        final_localite = None
        final_pays = None
    return {
        **source,
        "_source_geo_key": source_geo_key,
        "pays": final_pays,
        "region": final_region,
        "gouvernorat": final_gouvernorat,
        "localite": final_localite,
        "adresse_fragment": None,
        "code_postal": final_code_postal,
        "geo_entity_type": _classify_geo_entity_type(source.get("source_localite")),
        "geo_quality_level": quality,
        "needs_review": "NO",
        "resolution_status": status,
        "resolution_method": "SOURCE_FALLBACK",
        "resolution_reason": reason,
        "resolution_confidence": 0.0,
        "conflict_detected": "NO",
        "candidate_summary": "",
        "postal_code_status": postal_status,
        "postal_code_method": "NONE",
        "postal_code_reason": reason,
        "postal_candidate_summary": "",
    }

def _extract_localite_from_address(address: str, reference_indexes: dict) -> str | None:
    """Find an explicit known locality name within an address string (whole-word match only)."""
    if not address:
        return None
    known = sorted(
        (t for t in reference_indexes.get("localite", {}) if len(t) >= 4 and t not in _VALID_GOVERNORATS),
        key=len,
        reverse=True,
    )
    for term in known:
        if re.search(r'\b' + re.escape(term) + r'\b', address):
            return term
    return None


def _resolve_address_fragment(
    source: dict,
    source_geo_key: str,
    entity_type: str,
    reference_indexes: dict,
) -> dict:
    """Return a resolution dict for ADRESSE_PARTIELLE / ROUTE_AUTOROUTE rows.

    The raw address is preserved in adresse_fragment; localite is cleared to
    UNKNOWN unless an explicit known locality is safely extractable from the text.
    """
    source_localite = source.get("source_localite") or ""
    source_gouvernorat = source.get("source_gouvernorat")

    adresse_fragment = source_localite or None

    extracted_localite = _extract_localite_from_address(source_localite, reference_indexes)

    final_gouvernorat = source_gouvernorat if source_gouvernorat in _VALID_GOVERNORATS else None

    if extracted_localite and final_gouvernorat:
        refs = reference_indexes["localite"].get(extracted_localite, [])
        if refs and not any(r.get("gouvernorat") == final_gouvernorat for r in refs):
            extracted_localite = None

    final_region = (
        reference_indexes["governorate_region"].get(final_gouvernorat)
        if final_gouvernorat else None
    )
    final_localite = extracted_localite
    final_pays = "TUNISIE" if final_gouvernorat else None

    gov_known = final_gouvernorat is not None
    region_known = final_region is not None
    needs_review = "NO" if (gov_known or region_known) else "YES"
    geo_quality = "PARTIAL" if (gov_known or region_known) else "AMBIGUOUS"

    reason = "address/route fragment preserved; localite cleared"
    if extracted_localite:
        reason += f"; extracted '{extracted_localite}' from address text"

    return {
        **source,
        "_source_geo_key": source_geo_key,
        "pays": final_pays,
        "region": final_region,
        "gouvernorat": final_gouvernorat,
        "localite": final_localite,
        "adresse_fragment": adresse_fragment,
        "code_postal": None,
        "geo_entity_type": entity_type,
        "geo_quality_level": geo_quality,
        "needs_review": needs_review,
        "resolution_status": "ADDRESS_FRAGMENT",
        "resolution_method": "ADDRESS_FRAGMENT",
        "resolution_reason": reason,
        "resolution_confidence": 0.5 if gov_known else 0.2,
        "conflict_detected": "NO",
        "candidate_summary": "",
        "postal_code_status": "POSTAL_NOT_APPLICABLE",
        "postal_code_method": "NONE",
        "postal_code_reason": "address fragment: postal lookup skipped",
        "postal_candidate_summary": "",
    }


# ---------------------------------------------------------------------------
# Gouvernorat cascade — helpers
# ---------------------------------------------------------------------------

_UNUSABLE_GOUVSINI_PAT = re.compile(r'^\d+$|^\*+$')

def _is_unusable_gouvsini(raw) -> bool:
    """True if the raw gouvsini value cannot be a valid gouvernorat."""
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return True
    s = str(raw).strip()
    if not s or len(s) <= 1:
        return True
    if _UNUSABLE_GOUVSINI_PAT.match(s):
        return True
    if 'TUNISIE -' in s.upper():
        return True
    return False


def _normalize_gov_to_valid(raw) -> str | None:
    """Return canonical gouvernorat string if raw resolves to one, else None."""
    if _is_unusable_gouvsini(raw):
        return None
    s = normalize_text(raw)
    if s is None:
        return None
    if s in _VALID_GOVERNORATS:
        return s
    gov = _GOUVERNORAT_ALIASES.get(s)
    if gov and gov in _VALID_GOVERNORATS:
        return gov
    cleaned = re.sub(r'[\(\)\d]+$', '', s).strip()
    if cleaned != s:
        if cleaned in _VALID_GOVERNORATS:
            return cleaned
        gov = _GOUVERNORAT_ALIASES.get(cleaned)
        if gov and gov in _VALID_GOVERNORATS:
            return gov
    return None


_STREET_ADDRESS_PAT = re.compile(
    r'\b(RUE|AV|AVE|AVENUE|ROUTE|ROUTEX|RTE|KM|AUTOROUTE|AUTOUROUTE|AUTROUTE|ATOROUTE|GP\s*\d*|GP\d+|BOULEVARD|BD|CHEMIN|PEAGE|PONT)\b'
)

def _is_street_address_text(s: str | None) -> bool:
    return bool(s and _STREET_ADDRESS_PAT.search(s))


def _resolve_localite_priority(
    citesini: str | None,
    regsini: str | None,
    rue: str | None,
) -> str | None:
    """Priority: citesini (not gov) → regsini (not gov) → rue (not street) → None."""
    if citesini and _normalize_gov_to_valid(citesini) is None and not _is_generic_localite(citesini):
        return citesini
    if regsini and _normalize_gov_to_valid(regsini) is None and not _is_generic_localite(regsini):
        return regsini
    if rue and not _is_street_address_text(rue) and not _is_generic_localite(rue):
        return rue
    return None


# Only prefixes 3, 7, 8 are unambiguous enough for Step 4 inference.
_HIGH_CONF_POSTAL_PREFIX_GOV: dict[str, str] = {
    "3": "SFAX",
    "7": "BIZERTE",
    "8": "NABEUL",
}

def _resolve_gov_from_postal_prefix(cpostsini: str | None) -> str | None:
    cp = normalize_cpost(cpostsini)
    if not cp:
        return None
    return _HIGH_CONF_POSTAL_PREFIX_GOV.get(cp[0])


def _lookup_postal_code_simple(
    gouvernorat: str,
    localite: str | None,
    reference_indexes: dict,
) -> str | None:
    """Exact (gouvernorat, localite) lookup in postal reference. Returns unambiguous code or None."""
    if not localite:
        return None
    refs = reference_indexes.get("postal_localite", {}).get((gouvernorat, localite), [])
    if not refs:
        return None
    codes = _unique_reference_postal_codes(refs)
    return codes[0] if len(codes) == 1 else None


def _unique_ref_from_refs(refs: list[dict]) -> dict | None:
    """Return one canonical postal/locality reference if refs resolve to one target."""
    if not refs:
        return None
    targets = {}
    for ref in refs:
        gov = normalize_gouvernorat(ref.get("gouvernorat"))
        loc = normalize_text(ref.get("localite"))
        cp = normalize_cpost(ref.get("code_postal"))
        delegation = normalize_text(ref.get("delegation"))
        if gov and loc:
            targets[(gov, loc, cp or "")] = {
                "gouvernorat": gov,
                "localite": loc,
                "code_postal": cp,
                "delegation": delegation,
                "confidence": float(ref.get("confidence", 1.0)),
            }
    if len(targets) == 1:
        return next(iter(targets.values()))
    # Multiple postal codes for the same gov/localite: keep canonical localite, leave CP unresolved.
    gov_loc = {(k[0], k[1]) for k in targets}
    if len(gov_loc) == 1:
        gov, loc = next(iter(gov_loc))
        return {"gouvernorat": gov, "localite": loc, "code_postal": None, "delegation": None, "confidence": 0.9}
    return None


def _linguistic_key_for_localite(raw: str | None) -> str | None:
    """Conservative linguistic/transliteration key for Tunisian locality variants.

    This is NOT written to dim_geo. It is only used for matching a noisy source
    localite to a DimRegion canonical localite inside the same gouvernorat.

    Examples:
      ARIANA ESOGHRA / ESSOGHRA / SOGHRA / SOUGHRA -> ARIANA SOGRA
      BAB EL KHADHRA / BAB EL KHADRA               -> BAB HADRA
      MENZEH / MANZEH / MENZAH                     -> MENZAH-like key
    """
    s = normalize_text(raw)
    if not s:
        return None

    # Word-level variants frequently seen in Tunisian/French transliteration.
    phrase_rules = [
        (r"\bESS?O?UGH?RA\b", "SOGRA"),
        (r"\bSOUGHRA\b", "SOGRA"),
        (r"\bSOGHRA\b", "SOGRA"),
        (r"\bESS?GHIRA\b", "SGHIRA"),
        (r"\bSGHIRA\b", "SGHIRA"),
        (r"\bKHADHRA\b", "HADRA"),
        (r"\bKHADRA\b", "HADRA"),
        (r"\bEL\s+MENZAH\b", "MENZAH"),
        (r"\bEL\s+MENZEH\b", "MENZAH"),
        (r"\bMANZEH\b", "MENZAH"),
        (r"\bMENZEH\b", "MENZAH"),
        (r"\bOUED\s+ELLIL\b", "OUED LIL"),
        (r"\bOUED\s+ELIL\b", "OUED LIL"),
        (r"\bHAMMAM\s+LEFE\b", "HAMMAM LIF"),
        (r"\bHAMMEM\s+LIF\b", "HAMMAM LIF"),
        (r"\bBIR\s+BOURGBA\b", "BIR BOUREGBA"),
        (r"\bBOURAGBA\b", "BOUREGBA"),
        (r"\bMORNAG\b", "MORNEG"),
    ]
    for pattern, repl in phrase_rules:
        s = re.sub(pattern, repl, s)

    # Token normalization: articles and common transliteration letters.
    tokens: list[str] = []
    for token in s.split():
        if token in {"EL", "AL", "LE", "LA", "L", "DE", "DU", "DES", "BEN"}:
            continue

        token = token.replace("OU", "O")
        token = token.replace("EAU", "O")
        token = token.replace("PH", "F")
        token = token.replace("QU", "K")
        token = token.replace("Q", "K")
        token = token.replace("C", "K")
        token = token.replace("KH", "H")
        token = token.replace("GH", "G")
        token = token.replace("DH", "D")
        token = token.replace("TH", "T")
        token = token.replace("Y", "I")

        # Strip article-like prefixes inside a single token:
        # ESSOGHRA -> SOGRA, ELKHADRA -> HADRA, LARIANA -> ARIANA.
        token = re.sub(r"^(EL|AL|LE|LA|L)(?=[A-Z]{3,})", "", token)
        token = re.sub(r"^ESS(?=[A-Z]{3,})", "S", token)
        token = re.sub(r"^ES(?=[A-Z]{3,})", "S", token)

        # Collapse repeated letters for key only: SOUSSE -> SOSE, ESSOGHRA -> ESOGRA.
        token = re.sub(r"([A-Z])\1+", r"\1", token)

        if token and token not in {"E", "A", "D"}:
            tokens.append(token)

    key = " ".join(tokens)
    key = re.sub(r"\s+", " ", key).strip()
    return key or None


def _linguistic_ref_lookup(
    gouvernorat: str,
    localite: str | None,
    reference_indexes: dict,
) -> dict | None:
    """Return one DimRegion canonical reference by linguistic key inside the same governorate."""
    key = _linguistic_key_for_localite(localite)
    if not key or gouvernorat not in _VALID_GOVERNORATS:
        return None

    matches: list[dict] = []
    for (gov, ref_localite), refs in reference_indexes.get("postal_localite", {}).items():
        if gov != gouvernorat:
            continue
        if _is_generic_localite(ref_localite):
            continue
        if _classify_geo_entity_type(ref_localite) in ("ADRESSE_PARTIELLE", "ROUTE_AUTOROUTE"):
            continue
        if _linguistic_key_for_localite(ref_localite) == key:
            matches.extend(refs)

    return _unique_ref_from_refs(matches)


def _canonicalize_localite_with_dimregion(
    gouvernorat: str,
    localite: str | None,
    reference_indexes: dict,
    alias_dict: dict | None = None,
) -> tuple[str | None, str | None, str, float, str]:
    """Canonicalize source localite using DimRegion/postal reference before geo_key creation."""
    term = normalize_text(localite)
    if not term or gouvernorat not in _VALID_GOVERNORATS:
        return term, None, "NO_LOCALITE", 0.0, "no usable localite or governorate"

    entity_type = _classify_geo_entity_type(term)
    if entity_type in ("ADRESSE_PARTIELLE", "ROUTE_AUTOROUTE"):
        return None, None, "ADDRESS_FRAGMENT", 0.0, "street/route fragment is not a locality"

    # Manual ETL aliases first, but only when they do not contradict the resolved governorate.
    if alias_dict:
        alias = alias_dict.get(term)
        if alias:
            alias_gov = normalize_gouvernorat(alias.get("gouvernorat"))
            alias_loc = normalize_text(alias.get("localite"))
            if alias_gov == gouvernorat and alias_loc:
                cp = _lookup_postal_code_simple(alias_gov, alias_loc, reference_indexes)
                return alias_loc, cp, "ALIAS_MANUEL", float(alias.get("confidence", 0.95)), "manual alias canonical localite"
            if alias_gov in _VALID_GOVERNORATS and alias_gov != gouvernorat:
                return term, None, "ALIAS_GOV_CONFLICT", 0.2, f"alias governorate {alias_gov} conflicts with resolved governorate {gouvernorat}"

    refs = reference_indexes.get("postal_localite", {}).get((gouvernorat, term), [])
    ref = _unique_ref_from_refs(refs)
    if ref:
        return ref["localite"], ref.get("code_postal"), "DIMREGION_EXACT_LOCALITE", 1.0, "exact DimRegion locality match"

    refs = reference_indexes.get("postal_alias", {}).get((gouvernorat, term), [])
    ref = _unique_ref_from_refs(refs)
    if ref:
        return ref["localite"], ref.get("code_postal"), "DIMREGION_ALIAS_LOCALITE", 0.96, "DimRegion generated alias match"

    # Linguistic/transliteration agreement inside the same governorate.
    # This catches variants such as ESSOGHRA / ESOGHRA / SOGHRA / SOUGHRA
    # without maintaining every typo manually.
    ref = _linguistic_ref_lookup(gouvernorat, term, reference_indexes)
    if ref:
        return ref["localite"], ref.get("code_postal"), "DIMREGION_LINGUISTIC_LOCALITE", 0.94, "DimRegion linguistic/transliteration agreement match"

    # Fuzzy only inside the same governorate and only on canonical DimRegion localities.
    from difflib import SequenceMatcher
    best = (0.0, None, [])
    second = 0.0
    for (gov, ref_term), refs in reference_indexes.get("postal_localite", {}).items():
        if gov != gouvernorat or _is_generic_localite(ref_term):
            continue
        if _classify_geo_entity_type(ref_term) in ("ADRESSE_PARTIELLE", "ROUTE_AUTOROUTE"):
            continue
        score = SequenceMatcher(None, term, ref_term).ratio()
        if score > best[0]:
            second = best[0]
            best = (score, ref_term, refs)
        elif score > second:
            second = score
    if best[0] >= 0.86 and (best[0] - second) >= 0.025:
        ref = _unique_ref_from_refs(best[2])
        if ref:
            return ref["localite"], ref.get("code_postal"), "DIMREGION_FUZZY_LOCALITE", round(best[0], 4), f"fuzzy DimRegion match score={best[0]:.3f}"

    return term, _lookup_postal_code_simple(gouvernorat, term, reference_indexes), "SOURCE_LOCALITE", 0.5, "kept source localite; no canonical DimRegion match"


# ---------------------------------------------------------------------------
# Row resolver — 5-step cascade
# ---------------------------------------------------------------------------

def _resolve_one_geo_row(
    row: pd.Series,
    reference_indexes: dict,
    corrections_by_key: dict[str, dict],
    alias_dict: dict | None = None,
) -> dict:
    """5-step gouvernorat cascade + DimRegion canonical localite normalization."""
    raw_gouvsini  = row.get("gouvernorat")
    raw_citesini  = normalize_text(row.get("localite"))
    raw_regsini   = normalize_text(row.get("regsini_hint"))
    raw_cpostsini = normalize_cpost(row.get("code_postal"))
    raw_rue       = normalize_text(row.get("rue"))

    src_gov = None if _is_unusable_gouvsini(raw_gouvsini) else normalize_text(raw_gouvsini)
    _source_geo_key = _source_geo_key_from_values(src_gov, raw_citesini, raw_cpostsini)

    final_gouvernorat: str | None = None
    resolution_status: str = "STEP5_EXCLUDED"

    # Step 1 — gouvsini is a valid gouvernorat (after alias normalization)
    gov = _normalize_gov_to_valid(raw_gouvsini)
    if gov:
        final_gouvernorat = gov
        resolution_status = "STEP1_GOUVSINI"
    else:
        # Step 2 — citesini is a valid gouvernorat
        gov = _normalize_gov_to_valid(raw_citesini)
        if gov:
            final_gouvernorat = gov
            resolution_status = "STEP2_CITESINI"
        else:
            # Step 3 — regsini is a valid gouvernorat
            gov = _normalize_gov_to_valid(raw_regsini)
            if gov:
                final_gouvernorat = gov
                resolution_status = "STEP3_REGSINI"
            else:
                # Step 4 — postal prefix (only high-confidence: 3→SFAX, 7→BIZERTE, 8→NABEUL)
                gov = _resolve_gov_from_postal_prefix(raw_cpostsini)
                if gov:
                    final_gouvernorat = gov
                    resolution_status = "STEP4_POSTAL"

    # localite priority: citesini → regsini → rue (skipping whichever was used as gouvernorat)
    if resolution_status == "STEP2_CITESINI":
        source_localite_candidate = _resolve_localite_priority(None, raw_regsini, raw_rue)
    elif resolution_status == "STEP3_REGSINI":
        source_localite_candidate = _resolve_localite_priority(raw_citesini, None, raw_rue)
    else:
        source_localite_candidate = _resolve_localite_priority(raw_citesini, raw_regsini, raw_rue)

    base = {
        "source_region":      raw_regsini,
        "source_gouvernorat": src_gov,
        "source_localite":    raw_citesini,
        "source_code_postal": raw_cpostsini,
        "source_rue":         raw_rue,
        "_source_geo_key":    _source_geo_key,
        "conflict_detected":  "NO",
        "candidate_summary":  "",
        "postal_candidate_summary": "",
    }

    if final_gouvernorat is None:
        # Step 5 — excluded from final dim_geo; still written to quality reports.
        return {
            **base,
            "pays":               None,
            "region":             None,
            "gouvernorat":        None,
            "localite":           None,
            "adresse_fragment":   None,
            "code_postal":        None,
            "geo_entity_type":    _classify_geo_entity_type(raw_citesini or raw_regsini),
            "geo_quality_level":  "AMBIGUOUS",
            "needs_review":       "YES",
            "resolution_status":  "STEP5_EXCLUDED",
            "resolution_method":  "NONE",
            "resolution_reason":  "no gouvernorat resolved from gouvsini/citesini/regsini/postal",
            "resolution_confidence": 0.0,
            "postal_code_status": "POSTAL_NOT_APPLICABLE",
            "postal_code_method": "NONE",
            "postal_code_reason": "excluded: gouvernorat unknown",
        }

    pays = "TUNISIE"
    final_localite = source_localite_candidate
    adresse_fragment = None
    entity_type = _classify_geo_entity_type(final_localite or raw_citesini or raw_regsini)
    canonical_method = "NO_LOCALITE"
    canonical_confidence = 0.0
    canonical_reason = "no localite"

    # Routes/streets/avenues must not become localities.
    if entity_type in ("ADRESSE_PARTIELLE", "ROUTE_AUTOROUTE"):
        adresse_fragment = final_localite
        final_localite = None
        code_postal = None
        quality = "PARTIAL"
        needs_review = "NO" if final_gouvernorat in _VALID_GOVERNORATS else "YES"
        postal_status = "POSTAL_NOT_APPLICABLE"
        resolution_status_final = "ADDRESS_FRAGMENT"
        resolution_method = "ADDRESS_FRAGMENT"
        resolution_reason = "address/route fragment moved to adresse_fragment; localite cleared"
        resolution_confidence = 0.5
    else:
        # Canonicalize localite using DimRegion before postal lookup, geo_key, and deduplication.
        canonical_localite, canonical_cp, canonical_method, canonical_confidence, canonical_reason = _canonicalize_localite_with_dimregion(
            final_gouvernorat,
            final_localite,
            reference_indexes,
            alias_dict,
        )
        final_localite = canonical_localite
        code_postal = canonical_cp or _lookup_postal_code_simple(final_gouvernorat, final_localite, reference_indexes)
        postal_status = "POSTAL_REFERENCE_EXACT_LOCALITE" if code_postal else "POSTAL_MISSING_REFERENCE"
        entity_type = _classify_geo_entity_type(final_localite or raw_citesini or raw_regsini)

        if canonical_method in {"ALIAS_GOV_CONFLICT"}:
            quality = "AMBIGUOUS"
            needs_review = "YES"
        elif code_postal and final_localite:
            quality = "VALIDATED"
            needs_review = "NO"
        elif final_localite:
            quality = "PARTIAL"
            needs_review = "YES"
        else:
            quality = "PARTIAL"
            needs_review = "YES"

        resolution_status_final = resolution_status if canonical_method in {"NO_LOCALITE", "SOURCE_LOCALITE"} else f"{resolution_status}_{canonical_method}"
        resolution_method = canonical_method if canonical_method != "NO_LOCALITE" else resolution_status
        resolution_reason = f"gouvernorat resolved via {resolution_status.lower()}; {canonical_reason}"
        resolution_confidence = canonical_confidence if canonical_confidence else (1.0 if resolution_status == "STEP1_GOUVSINI" else 0.7)

    return {
        **base,
        "pays":               pays,
        "region":             None,  # derived from gouvernorat in finalize_business_fields
        "gouvernorat":        final_gouvernorat,
        "localite":           final_localite,
        "adresse_fragment":   adresse_fragment,
        "code_postal":        code_postal,
        "geo_entity_type":    entity_type,
        "geo_quality_level":  quality,
        "needs_review":       needs_review,
        "resolution_status":  resolution_status_final,
        "resolution_method":  resolution_method,
        "resolution_reason":  resolution_reason,
        "resolution_confidence": resolution_confidence,
        "postal_code_status": postal_status,
        "postal_code_method": "POSTAL_REFERENCE_LOCALITE" if code_postal else "NONE",
        "postal_code_reason": "gov+canonical localite exact match in DimRegion" if code_postal
                              else "no exact DimRegion postal code for this gouvernorat+localite pair",
    }


# Keep the old complex resolution paths below for reference (no longer called by transform_dim_geo)
def _resolve_one_geo_row_legacy(
    row: pd.Series,
    reference_indexes: dict,
    corrections_by_key: dict[str, dict],
    alias_dict: dict | None = None,
) -> dict:
    """Legacy resolver — kept for reference only; not called in production flow."""
    source = _source_values_from_row(row)
    source_geo_key = _source_geo_key_from_values(
        source.get("source_gouvernorat"),
        source.get("source_localite"),
        source.get("source_code_postal"),
    )
    entity_type = _classify_geo_entity_type(source.get("source_localite"))

    no_signal = not any(source.values())
    if no_signal or source_geo_key == _GEO_KEY_UNKNOWN:
        return _empty_resolution(source, source_geo_key, "UNKNOWN", "no usable source geography signal")

    correction = corrections_by_key.get(_normalize_existing_geo_key(source_geo_key) or "")
    if correction is not None:
        final_region = correction.get("region")
        final_gouvernorat = correction.get("gouvernorat")
        final_localite = correction.get("localite")
        final_delegation = correction.get("delegation")
        postal = _resolve_postal_code(
            source,
            reference_indexes,
            final_gouvernorat,
            final_localite,
            final_delegation,
            correction.get("code_postal"),
        )
        final_code_postal = postal["code_postal"]
        final_pays = _infer_pays(final_gouvernorat, final_code_postal) or (
            "TUNISIE" if final_gouvernorat in _VALID_GOVERNORATS else None
        )
        conflict = (
            source.get("source_gouvernorat") in _VALID_GOVERNORATS
            and final_gouvernorat in _VALID_GOVERNORATS
            and source.get("source_gouvernorat") != final_gouvernorat
        )
        return {
            **source,
            "_source_geo_key": source_geo_key,
            "pays": final_pays,
            "region": final_region,
            "gouvernorat": final_gouvernorat,
            "localite": final_localite,
            "adresse_fragment": None,
            "code_postal": final_code_postal,
            "geo_entity_type": entity_type,
            "geo_quality_level": _geo_quality_from_resolution(
                "APPROVED_CORRECTION",
                final_gouvernorat,
                final_localite,
                final_region,
                final_code_postal,
                final_pays,
                postal["postal_code_status"],
            ),
            "needs_review": "NO",
            "resolution_status": "APPROVED_CORRECTION",
            "resolution_method": "APPROVED_CORRECTIONS",
            "resolution_reason": "human-approved correction matched by source geo_key",
            "resolution_confidence": 1.0,
            "conflict_detected": "YES" if conflict else "NO",
            "candidate_summary": "approved correction",
            "matched_correction_id": correction.get("correction_id"),
            **postal,
        }

    if entity_type in ("ADRESSE_PARTIELLE", "ROUTE_AUTOROUTE"):
        return _resolve_address_fragment(source, source_geo_key, entity_type, reference_indexes)

    selected, method, selection_status, candidates = _find_reference_candidate(source, reference_indexes, alias_dict)
    if selected is not None:
        final_region = selected.get("region")
        final_gouvernorat = selected.get("gouvernorat")
        final_localite = selected.get("localite")
        final_delegation = selected.get("delegation")
        postal = _resolve_postal_code(
            source,
            reference_indexes,
            final_gouvernorat,
            final_localite,
            final_delegation,
            selected.get("code_postal"),
        )
        final_code_postal = postal["code_postal"]
        final_pays = "TUNISIE"
        conflict = (
            source.get("source_gouvernorat") in _VALID_GOVERNORATS
            and final_gouvernorat in _VALID_GOVERNORATS
            and source.get("source_gouvernorat") != final_gouvernorat
        )
        status = "CONFLICT_CORRECTED_REFERENCE" if conflict else f"RESOLVED_{method}"
        reason = f"{method.lower()} resolved by trusted reference ({selection_status})"
        if conflict:
            reason = (
                f"source gouvernorat {source.get('source_gouvernorat')} corrected to "
                f"{final_gouvernorat} by unique trusted {method.lower()} match"
            )
        return {
            **source,
            "_source_geo_key": source_geo_key,
            "pays": final_pays,
            "region": final_region,
            "gouvernorat": final_gouvernorat,
            "localite": final_localite,
            "adresse_fragment": None,
            "code_postal": final_code_postal,
            "geo_entity_type": entity_type,
            "geo_quality_level": _geo_quality_from_resolution(
                status,
                final_gouvernorat,
                final_localite,
                final_region,
                final_code_postal,
                final_pays,
                postal["postal_code_status"],
            ),
            "needs_review": "NO",
            "resolution_status": status,
            "resolution_method": method,
            "resolution_reason": reason,
            "resolution_confidence": round(float(selected.get("confidence", 1.0)), 4),
            "conflict_detected": "YES" if conflict else "NO",
            "candidate_summary": _candidate_summary(candidates),
            **postal,
        }

    if candidates and method == "POSTAL_CODE":
        has_non_postal_signal = bool(
            source.get("source_gouvernorat") in _VALID_GOVERNORATS
            or source.get("source_localite")
            or source.get("source_region")
        )
        if not has_non_postal_signal:
            return {
                **source,
                "_source_geo_key": source_geo_key,
                "pays": None,
                "region": None,
                "gouvernorat": None,
                "localite": None,
                "adresse_fragment": None,
                "code_postal": None,
                "geo_entity_type": entity_type,
                "geo_quality_level": "UNKNOWN",
                "needs_review": "NO",
                "resolution_status": "UNRESOLVED_POSTAL_ONLY",
                "resolution_method": "SOURCE_POSTAL_CODE",
                "resolution_reason": "postal code alone matches several official places and is not business-readable without locality/governorate",
                "resolution_confidence": 0.0,
                "conflict_detected": "NO",
                "candidate_summary": _candidate_summary(candidates),
                "postal_code_status": "POSTAL_ONLY_NO_GEOGRAPHY",
                "postal_code_method": "SOURCE_CPOSTSINI",
                "postal_code_reason": "source postal code was not loaded because official postal reference did not resolve it uniquely",
                "postal_candidate_summary": _candidate_summary(candidates),
            }

    if candidates:
        final_gouvernorat = source.get("source_gouvernorat") if source.get("source_gouvernorat") in _VALID_GOVERNORATS else None
        final_region = reference_indexes["governorate_region"].get(final_gouvernorat) if final_gouvernorat else None
        final_localite = source.get("source_localite")
        postal = _resolve_postal_code(
            source,
            reference_indexes,
            final_gouvernorat,
            final_localite,
            source.get("source_region"),
            None,
            allow_reference=True,
        )
        final_code_postal = postal["code_postal"]
        final_pays = _infer_pays(final_gouvernorat, final_code_postal)
        return {
            **source,
            "_source_geo_key": source_geo_key,
            "pays": final_pays,
            "region": final_region,
            "gouvernorat": final_gouvernorat,
            "localite": final_localite,
            "adresse_fragment": None,
            "code_postal": final_code_postal,
            "geo_entity_type": entity_type,
            "geo_quality_level": _geo_quality_from_resolution(
                f"AMBIGUOUS_{method}",
                final_gouvernorat,
                final_localite,
                final_region,
                final_code_postal,
                final_pays,
                postal["postal_code_status"],
            ),
            "needs_review": "NO",
            "resolution_status": f"AMBIGUOUS_{method}",
            "resolution_method": method,
            "resolution_reason": f"reference candidates are not unique ({selection_status})",
            "resolution_confidence": 0.0,
            "conflict_detected": "NO",
            "candidate_summary": _candidate_summary(candidates),
            **postal,
        }

    source_gouvernorat = source.get("source_gouvernorat")
    if source_gouvernorat in _VALID_GOVERNORATS:
        final_region = reference_indexes["governorate_region"].get(source_gouvernorat)
        final_localite = source.get("source_localite")
        postal = _resolve_postal_code(
            source,
            reference_indexes,
            source_gouvernorat,
            final_localite,
            source.get("source_region"),
        )
        final_code_postal = postal["code_postal"]
        final_pays = "TUNISIE"
        return {
            **source,
            "_source_geo_key": source_geo_key,
            "pays": final_pays,
            "region": final_region,
            "gouvernorat": source_gouvernorat,
            "localite": final_localite,
            "adresse_fragment": None,
            "code_postal": final_code_postal,
            "geo_entity_type": entity_type,
            "geo_quality_level": _geo_quality_from_resolution(
                "RESOLVED_GOVERNORATE_ONLY",
                source_gouvernorat,
                final_localite,
                final_region,
                final_code_postal,
                final_pays,
                postal["postal_code_status"],
            ),
            "needs_review": "NO",
            "resolution_status": "RESOLVED_GOVERNORATE_ONLY",
            "resolution_method": "SOURCE_GOUVERNORAT",
            "resolution_reason": "official source gouvernorat kept; localite was not confirmed by reference",
            "resolution_confidence": 0.55,
            "conflict_detected": "NO",
            "candidate_summary": "",
            **postal,
        }

    if source.get("source_code_postal"):
        return {
            **source,
            "_source_geo_key": source_geo_key,
            "pays": None,
            "region": None,
            "gouvernorat": None,
            "localite": None,
            "adresse_fragment": None,
            "code_postal": None,
            "geo_entity_type": entity_type,
            "geo_quality_level": "UNKNOWN",
            "needs_review": "NO",
            "resolution_status": "UNRESOLVED_POSTAL_ONLY",
            "resolution_method": "SOURCE_POSTAL_CODE",
            "resolution_reason": "postal code alone is not business-readable without trusted locality/governorate resolution",
            "resolution_confidence": 0.0,
            "conflict_detected": "NO",
            "candidate_summary": "",
            "postal_code_status": "POSTAL_ONLY_NO_GEOGRAPHY",
            "postal_code_method": "SOURCE_CPOSTSINI",
            "postal_code_reason": "valid source postal code was not loaded because no trusted geography was resolved",
            "postal_candidate_summary": "",
        }

    if source.get("source_localite") or source.get("source_region"):
        return _empty_resolution(
            source,
            source_geo_key,
            "UNRESOLVED_NO_REFERENCE",
            "source has text geography but no trusted reference match",
        )
    return _empty_resolution(source, source_geo_key, "UNKNOWN", "no usable source geography signal")

def _write_resolution_reports(df_resolution: pd.DataFrame, df_final: pd.DataFrame | None = None) -> None:
    GEO_QUALITY_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_cols = [
        "geo_sk",
        "source_region",
        "source_gouvernorat",
        "source_localite",
        "source_code_postal",
        "source_geo_key",
        "pays",
        "region",
        "gouvernorat",
        "localite",
        "adresse_fragment",
        "code_postal",
        "geo_entity_type",
        "geo_quality_level",
        "needs_review",
        "geo_key",
        "resolution_status",
        "resolution_method",
        "resolution_reason",
        "resolution_confidence",
        "conflict_detected",
        "candidate_summary",
        "postal_code_status",
        "postal_code_method",
        "postal_code_reason",
        "postal_candidate_summary",
        "matched_correction_id",
        "matched_postal_correction_id",
        "candidate_region",
        "candidate_gouvernorat",
        "candidate_localite",
        "candidate_code_postal",
        "conflict_reason",
    ]
    df_report = df_resolution.copy()
    if df_final is not None and "geo_key" in df_report.columns:
        final_lookup = df_final[["geo_key", "geo_sk"]].drop_duplicates(subset=["geo_key"])
        df_report = df_report.merge(final_lookup, on="geo_key", how="left", suffixes=("", "_final"))
    if "_source_geo_key" in df_report.columns:
        df_report["source_geo_key"] = df_report["_source_geo_key"]
    for col in report_cols:
        if col not in df_report.columns:
            df_report[col] = ""
    df_report[report_cols].to_csv(RESOLUTION_REPORT_PATH, index=False, encoding="utf-8-sig")

    unresolved_statuses = {
        "UNKNOWN",
        "UNRESOLVED_NO_REFERENCE",
        "UNRESOLVED_POSTAL_ONLY",
        "POSTAL_CODE_ONLY",
        "RESOLVED_GOVERNORATE_ONLY",
    }
    mask_unresolved = (
        df_report["resolution_status"].isin(unresolved_statuses)
        | df_report["resolution_status"].str.startswith("AMBIGUOUS", na=False)
    )
    df_report.loc[mask_unresolved, report_cols].to_csv(
        UNRESOLVED_REPORT_PATH, index=False, encoding="utf-8-sig"
    )
    df_report.loc[df_report["conflict_detected"].eq("YES"), report_cols].to_csv(
        CONFLICTS_AFTER_RESOLUTION_PATH, index=False, encoding="utf-8-sig"
    )

    gov_locality_conflict_cols = [
        "geo_sk",
        "source_region",
        "source_gouvernorat",
        "source_localite",
        "source_code_postal",
        "region",
        "gouvernorat",
        "localite",
        "candidate_gouvernorat",
        "candidate_localite",
        "candidate_code_postal",
        "conflict_reason",
        "resolution_status",
    ]
    for col in gov_locality_conflict_cols:
        if col not in df_report.columns:
            df_report[col] = ""
    df_report.loc[
        df_report["resolution_status"].eq("CONFLICT_GOV_LOCALITE"),
        gov_locality_conflict_cols,
    ].rename(
        columns={
            "region": "final_region",
            "gouvernorat": "final_gouvernorat",
            "localite": "final_localite",
        }
    ).to_csv(GOV_LOCALITY_CONFLICTS_PATH, index=False, encoding="utf-8-sig")

    postal_status = df_report["postal_code_status"].astype(str)
    postal_ambiguous_mask = (
        postal_status.str.startswith("POSTAL_AMBIGUOUS", na=False)
        | df_report["resolution_status"].str.startswith("AMBIGUOUS", na=False)
    )
    df_report.loc[postal_ambiguous_mask, report_cols].to_csv(
        POSTAL_AMBIGUOUS_REPORT_PATH, index=False, encoding="utf-8-sig"
    )

    postal_conflict_mask = postal_status.str.startswith("POSTAL_CONFLICT", na=False) | postal_status.str.contains("SOURCE_CONFLICT", na=False)
    df_report.loc[postal_conflict_mask, report_cols].to_csv(
        POSTAL_CONFLICTS_REPORT_PATH, index=False, encoding="utf-8-sig"
    )

    postal_missing_mask = (
        postal_status.eq("POSTAL_MISSING_REFERENCE")
        & df_report["pays"].eq("TUNISIE")
        & df_report["gouvernorat"].ne(_KEY_UNKNOWN)
        & df_report["localite"].ne(_KEY_UNKNOWN)
        & df_report["code_postal"].eq(_KEY_UNKNOWN)
    )
    df_report.loc[postal_missing_mask, report_cols].to_csv(
        POSTAL_MISSING_REFERENCE_REPORT_PATH, index=False, encoding="utf-8-sig"
    )

    missing_postal_mask = (
        df_report["pays"].eq("TUNISIE")
        & df_report["gouvernorat"].ne(_KEY_UNKNOWN)
        & df_report["code_postal"].eq(_KEY_UNKNOWN)
    )
    df_report.loc[missing_postal_mask, report_cols].to_csv(
        MISSING_POSTAL_REPORT_PATH, index=False, encoding="utf-8-sig"
    )

    postal_only_resolved_mask = (
        df_report["resolution_status"].eq("RESOLVED_POSTAL_CODE")
        & df_report["source_code_postal"].ne(_KEY_UNKNOWN)
    )
    df_report.loc[postal_only_resolved_mask, report_cols].to_csv(
        POSTAL_ONLY_RESOLVED_PATH, index=False, encoding="utf-8-sig"
    )

    postal_only_unresolved_mask = df_report["resolution_status"].eq("UNRESOLVED_POSTAL_ONLY")
    df_report.loc[postal_only_unresolved_mask, report_cols].to_csv(
        POSTAL_ONLY_UNRESOLVED_PATH, index=False, encoding="utf-8-sig"
    )
def _normalize_existing_geo_key(raw) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, float) and math.isnan(raw):
        return None
    value = str(raw).strip()
    if not value:
        return None

    parts = [part.strip() for part in value.split("|")]
    if len(parts) == 5:
        # Legacy 5-part key: pays|gouvernorat|region|localite|code_postal
        pays = normalize_text(parts[0])
        gouvernorat = normalize_gouvernorat(parts[1])
        localite = normalize_text(parts[3])
        code_postal = normalize_cpost(parts[4])
        geo_key = build_geo_key(pays, gouvernorat, localite, code_postal)
        return None if geo_key == _GEO_KEY_UNKNOWN else geo_key
    if len(parts) == 4:
        pays = normalize_text(parts[0])
        gouvernorat = normalize_gouvernorat(parts[1])
        localite = normalize_text(parts[2])
        code_postal = normalize_cpost(parts[3])
        geo_key = build_geo_key(pays, gouvernorat, localite, code_postal)
        return None if geo_key == _GEO_KEY_UNKNOWN else geo_key

    value = normalize_text(value)
    return value if value and value not in _INVALID_TEXT else None


def _build_source_geo_key_candidate(
    gouvernorat_raw,
    localite_raw,
    code_postal_raw,
) -> str | None:
    code_postal = first_postal_candidate(code_postal_raw, gouvernorat_raw, localite_raw)
    gouvernorat = clear_numeric_geo_label(normalize_gouvernorat(gouvernorat_raw))
    localite = clear_numeric_geo_label(normalize_text(localite_raw))
    pays = _infer_pays(gouvernorat, code_postal)
    geo_key = build_geo_key(pays, gouvernorat, localite, code_postal)
    return None if geo_key == _GEO_KEY_UNKNOWN else geo_key


def _load_approved_corrections(logger) -> tuple[dict[str, dict], dict]:
    """Load APPROVED corrections keyed only by stable business source keys."""
    metrics = {
        "n_correction_rows_loaded": 0,
        "n_approved_corrections_loaded": 0,
        "n_ignored_corrections": 0,
        "n_approved_corrections_by_geo_key": 0,
        "n_duplicate_correction_keys": 0,
        "n_unusable_approved_corrections": 0,
    }
    if not APPROVED_CORRECTIONS_PATH.exists():
        logger.warning(f"  fichier corrections approuvees absent : {APPROVED_CORRECTIONS_PATH}")
        return {}, metrics

    df_corr = pd.read_csv(APPROVED_CORRECTIONS_PATH, dtype=str, keep_default_na=False)
    df_corr = _standardize_columns(df_corr)
    metrics["n_correction_rows_loaded"] = len(df_corr)

    required = {
        "approval_status",
        "approved_region",
        "approved_gouvernorat",
        "approved_localite",
        "approved_code_postal",
    }
    missing = sorted(required.difference(df_corr.columns))
    if missing:
        raise RuntimeError(f"Fichier corrections approuvees incomplet {APPROVED_CORRECTIONS_PATH} : colonnes manquantes {missing}")

    df_corr["approval_status_norm"] = df_corr["approval_status"].map(lambda x: str(x).strip().upper())
    df_approved = df_corr[df_corr["approval_status_norm"].isin(_APPROVED_STATUSES_TO_APPLY)].copy()
    metrics["n_approved_corrections_loaded"] = len(df_approved)
    metrics["n_ignored_corrections"] = len(df_corr) - len(df_approved)

    by_key: dict[str, dict] = {}
    for idx, row in df_approved.iterrows():
        region = normalize_text(row.get("approved_region"))
        gouvernorat = normalize_gouvernorat(row.get("approved_gouvernorat"))
        localite = normalize_text(row.get("approved_localite")) or normalize_text(row.get("approved_delegation"))
        code_postal = normalize_cpost(row.get("approved_code_postal"))

        if not any([region, gouvernorat, localite, code_postal]):
            metrics["n_unusable_approved_corrections"] += 1
            continue

        correction = {
            "correction_id": int(idx),
            "region": region,
            "gouvernorat": gouvernorat,
            "delegation": normalize_text(row.get("approved_delegation")),
            "localite": localite,
            "code_postal": code_postal,
        }

        geo_key = _normalize_existing_geo_key(row.get("geo_key")) if "geo_key" in df_approved.columns else None
        current_geo_key = _build_source_geo_key_candidate(
            row.get("current_gouvernorat") if "current_gouvernorat" in df_approved.columns else None,
            row.get("current_localite") if "current_localite" in df_approved.columns else None,
            row.get("current_code_postal") if "current_code_postal" in df_approved.columns else None,
        )

        keys = []
        for key in (geo_key, current_geo_key):
            if key and key not in keys:
                keys.append(key)

        if not keys:
            metrics["n_unusable_approved_corrections"] += 1
            continue

        inserted = False
        for key in keys:
            existing = by_key.get(key)
            if existing is not None and existing["correction_id"] != correction["correction_id"]:
                metrics["n_duplicate_correction_keys"] += 1
                continue
            by_key[key] = correction
            inserted = True
        if not inserted:
            metrics["n_unusable_approved_corrections"] += 1

    metrics["n_approved_corrections_by_geo_key"] = len(by_key)
    logger.info(f"  corrections approuvees chargees : {metrics['n_approved_corrections_loaded']} APPROVED / {metrics['n_correction_rows_loaded']} lignes")
    logger.info(f"  corrections utilisables par geo_key/source_geo_key : {len(by_key)}")
    return by_key, metrics


def _load_postal_approved_corrections(logger) -> tuple[dict[str, dict], dict]:
    """Load human-approved postal fills keyed by final business geo_key."""
    metrics = {
        "n_postal_correction_rows_loaded": 0,
        "n_postal_approved_corrections_loaded": 0,
        "n_ignored_postal_corrections": 0,
        "n_postal_approved_corrections_by_geo_key": 0,
        "n_duplicate_postal_correction_keys": 0,
        "n_unusable_postal_approved_corrections": 0,
    }
    if not POSTAL_APPROVED_CORRECTIONS_PATH.exists():
        logger.warning(f"  fichier corrections postales approuvees absent : {POSTAL_APPROVED_CORRECTIONS_PATH}")
        return {}, metrics

    df_corr = pd.read_csv(POSTAL_APPROVED_CORRECTIONS_PATH, dtype=str, keep_default_na=False)
    df_corr = _standardize_columns(df_corr)
    metrics["n_postal_correction_rows_loaded"] = len(df_corr)

    required = {
        "geo_key",
        "approval_status",
        "approved_region",
        "approved_gouvernorat",
        "approved_localite",
        "approved_code_postal",
    }
    missing = sorted(required.difference(df_corr.columns))
    if missing:
        raise RuntimeError(
            f"Fichier corrections postales approuvees incomplet {POSTAL_APPROVED_CORRECTIONS_PATH} : "
            f"colonnes manquantes {missing}"
        )

    df_corr["approval_status_norm"] = df_corr["approval_status"].map(lambda x: str(x).strip().upper())
    df_approved = df_corr[df_corr["approval_status_norm"].isin(_APPROVED_STATUSES_TO_APPLY)].copy()
    metrics["n_postal_approved_corrections_loaded"] = len(df_approved)
    metrics["n_ignored_postal_corrections"] = len(df_corr) - len(df_approved)

    by_key: dict[str, dict] = {}
    for idx, row in df_approved.iterrows():
        key = _normalize_existing_geo_key(row.get("geo_key"))
        region = normalize_text(row.get("approved_region"))
        gouvernorat = normalize_gouvernorat(row.get("approved_gouvernorat"))
        localite = normalize_text(row.get("approved_localite"))
        code_postal = normalize_cpost(row.get("approved_code_postal"))

        if not key or not region or gouvernorat not in _VALID_GOVERNORATS or not localite or not code_postal:
            metrics["n_unusable_postal_approved_corrections"] += 1
            continue
        if _postal_prefix_conflict(code_postal, gouvernorat):
            metrics["n_unusable_postal_approved_corrections"] += 1
            continue

        correction = {
            "postal_correction_id": int(idx),
            "source_geo_key": key,
            "region": region,
            "gouvernorat": gouvernorat,
            "localite": localite,
            "code_postal": code_postal,
            "correction_type": str(row.get("correction_type", "")).strip(),
            "correction_reason": str(row.get("correction_reason", "")).strip(),
            "candidate_summary": str(row.get("candidate_summary", "")).strip(),
        }

        existing = by_key.get(key)
        if existing is not None and existing != correction:
            metrics["n_duplicate_postal_correction_keys"] += 1
            continue
        by_key[key] = correction

    metrics["n_postal_approved_corrections_by_geo_key"] = len(by_key)
    logger.info(
        "  corrections postales approuvees chargees : "
        f"{metrics['n_postal_approved_corrections_loaded']} APPROVED / "
        f"{metrics['n_postal_correction_rows_loaded']} lignes"
    )
    logger.info(f"  corrections postales utilisables par geo_key : {len(by_key)}")
    return by_key, metrics


def _unique_global_postal_corrections_by_localite(
    postal_corrections_by_key: dict[str, dict],
) -> dict[str, dict]:
    """Fallback index for approved global-locality postal corrections only."""
    grouped: dict[str, list[dict]] = {}
    for correction in postal_corrections_by_key.values():
        correction_type = str(correction.get("correction_type", "")).strip().upper()
        if correction_type != "APPROVED_FILL_GLOBAL_LOCALITE":
            continue
        source_key = str(correction.get("source_geo_key", "")).strip().upper()
        if not source_key.startswith("UNKNOWN|UNKNOWN|UNKNOWN|"):
            continue
        localite = normalize_text(correction.get("localite"))
        if not localite or _is_generic_localite(localite):
            continue
        grouped.setdefault(localite, []).append(correction)

    result: dict[str, dict] = {}
    for localite, corrections in grouped.items():
        unique_targets = {
            (
                correction.get("region"),
                correction.get("gouvernorat"),
                correction.get("localite"),
                correction.get("code_postal"),
            )
            for correction in corrections
        }
        if len(unique_targets) == 1:
            result[localite] = corrections[0]
    return result


def _write_postal_approved_unmatched_report(
    postal_corrections_by_key: dict[str, dict],
    matched_keys: set[str],
) -> None:
    GEO_QUALITY_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for key, correction in sorted(postal_corrections_by_key.items()):
        if key in matched_keys:
            continue
        rows.append({"geo_key": key, **correction})
    pd.DataFrame(rows).to_csv(POSTAL_APPROVED_UNMATCHED_PATH, index=False, encoding="utf-8-sig")


def _apply_postal_approved_corrections(
    df_resolution: pd.DataFrame,
    postal_corrections_by_key: dict[str, dict],
) -> tuple[pd.DataFrame, dict]:
    """Apply approved postal corrections after initial resolution, before dedup/load."""
    metrics = {
        "n_postal_approved_corrections_matched": 0,
        "n_postal_approved_corrections_not_matched": len(postal_corrections_by_key),
        "n_rows_postal_corrected": 0,
        "n_rows_postal_corrected_by_localite_fallback": 0,
        "n_postal_global_localite_no_gov_only": 0,
        "n_rejected_global_match_due_to_gov_conflict": 0,
    }
    df = df_resolution.copy()
    if df.empty or not postal_corrections_by_key:
        _write_postal_approved_unmatched_report(postal_corrections_by_key, set())
        return df, metrics

    matched_keys: set[str] = set()
    localite_fallback = _unique_global_postal_corrections_by_localite(postal_corrections_by_key)
    if "matched_postal_correction_id" not in df.columns:
        df["matched_postal_correction_id"] = ""

    for idx, row in df.iterrows():
        key = _normalize_existing_geo_key(row.get("geo_key"))
        if not key:
            continue
        correction = postal_corrections_by_key.get(key)
        match_mode = "GEO_KEY"
        matched_key = key
        if correction is None and normalize_cpost(row.get("code_postal")) is None:
            row_localite = normalize_text(row.get("localite"))
            if row_localite:
                correction = localite_fallback.get(row_localite)
                if correction is not None:
                    match_mode = "UNIQUE_APPROVED_LOCALITE"
                    matched_key = correction.get("source_geo_key", key)
        if correction is None:
            continue

        final_region = correction["region"]
        final_gouvernorat = correction["gouvernorat"]
        final_localite = correction["localite"]
        final_code_postal = correction["code_postal"]
        final_pays = "TUNISIE"
        previous_gouvernorat = normalize_gouvernorat(row.get("gouvernorat"))
        conflict = (
            previous_gouvernorat in _VALID_GOVERNORATS
            and previous_gouvernorat != final_gouvernorat
        )
        reason = correction.get("correction_reason") or "approved postal correction matched by geo_key"
        if match_mode == "UNIQUE_APPROVED_LOCALITE" and conflict:
            conflict_reason = (
                "global approved locality postal match rejected because final governorate "
                f"{previous_gouvernorat} differs from candidate governorate {final_gouvernorat}"
            )
            df.at[idx, "geo_quality_level"] = "AMBIGUOUS"
            df.at[idx, "resolution_status"] = "CONFLICT_GOV_LOCALITE"
            df.at[idx, "resolution_method"] = "POSTAL_APPROVED_CORRECTIONS_REJECTED_GLOBAL_LOCALITE"
            df.at[idx, "resolution_reason"] = conflict_reason
            df.at[idx, "conflict_detected"] = "YES"
            df.at[idx, "candidate_summary"] = correction.get("candidate_summary", "")
            df.at[idx, "postal_code_status"] = "POSTAL_CONFLICT_GOV_LOCALITE"
            df.at[idx, "postal_code_method"] = "GLOBAL_LOCALITE_REJECTED"
            df.at[idx, "postal_code_reason"] = conflict_reason
            df.at[idx, "postal_candidate_summary"] = correction.get("candidate_summary", "")
            df.at[idx, "candidate_region"] = final_region
            df.at[idx, "candidate_gouvernorat"] = final_gouvernorat
            df.at[idx, "candidate_localite"] = final_localite
            df.at[idx, "candidate_code_postal"] = final_code_postal
            df.at[idx, "conflict_reason"] = conflict_reason
            metrics["n_rejected_global_match_due_to_gov_conflict"] += 1
            continue
        if match_mode == "UNIQUE_APPROVED_LOCALITE":
            reason = f"{reason}; matched by unique approved localite because generated geo_key differed"
            metrics["n_rows_postal_corrected_by_localite_fallback"] += 1
        if str(correction.get("source_geo_key", "")).upper().startswith("UNKNOWN|UNKNOWN|UNKNOWN|") and previous_gouvernorat not in _VALID_GOVERNORATS:
            metrics["n_postal_global_localite_no_gov_only"] += 1

        df.at[idx, "pays"] = final_pays
        df.at[idx, "region"] = final_region
        df.at[idx, "gouvernorat"] = final_gouvernorat
        df.at[idx, "localite"] = final_localite
        df.at[idx, "code_postal"] = final_code_postal
        df.at[idx, "geo_quality_level"] = _geo_quality_from_resolution(
            "POSTAL_APPROVED_CORRECTION",
            final_gouvernorat,
            final_localite,
            final_region,
            final_code_postal,
            final_pays,
            "POSTAL_APPROVED_CORRECTION",
        )
        df.at[idx, "geo_key"] = build_geo_key(final_pays, final_gouvernorat, final_localite, final_code_postal)
        df.at[idx, "resolution_status"] = "POSTAL_APPROVED_CORRECTION"
        df.at[idx, "resolution_method"] = f"POSTAL_APPROVED_CORRECTIONS_{match_mode}"
        df.at[idx, "resolution_reason"] = reason
        df.at[idx, "resolution_confidence"] = 1.0
        if conflict:
            df.at[idx, "conflict_detected"] = "YES"
        df.at[idx, "candidate_summary"] = correction.get("candidate_summary", "")
        df.at[idx, "postal_code_status"] = "POSTAL_APPROVED_CORRECTION"
        df.at[idx, "postal_code_method"] = f"POSTAL_APPROVED_CORRECTIONS_{match_mode}"
        df.at[idx, "postal_code_reason"] = "approved postal correction contains a real 4-digit code"
        df.at[idx, "postal_candidate_summary"] = correction.get("candidate_summary", "")
        df.at[idx, "matched_postal_correction_id"] = str(correction.get("postal_correction_id", ""))
        matched_keys.add(str(matched_key))

    metrics["n_postal_approved_corrections_matched"] = len(matched_keys)
    metrics["n_postal_approved_corrections_not_matched"] = max(len(postal_corrections_by_key) - len(matched_keys), 0)
    metrics["n_rows_postal_corrected"] = int(df["matched_postal_correction_id"].astype(str).ne("").sum())
    _write_postal_approved_unmatched_report(postal_corrections_by_key, matched_keys)
    return df, metrics


def _reassign_geo_sk(df_final: pd.DataFrame) -> pd.DataFrame:
    """Garde geo_sk=0 pour UNKNOWN et resequence les zones reelles apres deduplication."""
    unknown = df_final[df_final["geo_key"] == _GEO_KEY_UNKNOWN].copy()
    if unknown.empty:
        unknown = pd.DataFrame([{
            "geo_sk": 0,
            "pays": _KEY_UNKNOWN,
            "region": _KEY_UNKNOWN,
            "gouvernorat": _KEY_UNKNOWN,
            "localite": _KEY_UNKNOWN,
            "adresse_fragment": None,
            "code_postal": _KEY_UNKNOWN,
            "geo_entity_type": "UNKNOWN",
            "geo_quality_level": "UNKNOWN",
            "needs_review": "NO",
            "geo_key": _GEO_KEY_UNKNOWN,
            "source_system": SOURCE_SYSTEM,
            "source_context": SOURCE_CONTEXT,
            "created_at": TODAY,
        }])
    else:
        unknown = unknown.sort_values("geo_sk").head(1).copy()
        unknown["geo_sk"] = 0
        unknown["pays"] = _KEY_UNKNOWN
        unknown["region"] = _KEY_UNKNOWN
        unknown["gouvernorat"] = _KEY_UNKNOWN
        unknown["localite"] = _KEY_UNKNOWN
        unknown["adresse_fragment"] = None
        unknown["code_postal"] = _KEY_UNKNOWN
        unknown["geo_entity_type"] = "UNKNOWN"
        unknown["geo_quality_level"] = "UNKNOWN"
        unknown["needs_review"] = "NO"
        unknown["geo_key"] = _GEO_KEY_UNKNOWN

    real = df_final[df_final["geo_key"] != _GEO_KEY_UNKNOWN].copy()
    real = real.sort_values(["pays", "gouvernorat", "region", "localite", "code_postal", "geo_key"], kind="stable").reset_index(drop=True)
    real["geo_sk"] = range(1, len(real) + 1)
    return pd.concat([unknown[FINAL_COLS], real[FINAL_COLS]], ignore_index=True)

_QUALITY_RANK = {
    "VALIDATED": 4,
    "PARTIAL": 3,
    "AMBIGUOUS": 2,
    "UNKNOWN": 1,
}
_RESOLUTION_RANK = {
    "APPROVED_CORRECTION": 70,
    "POSTAL_APPROVED_CORRECTION": 68,
    "CONFLICT_CORRECTED_REFERENCE": 65,
    "RESOLVED_EXACT_LOCALITE": 60,
    "RESOLVED_ALIAS_LOCALITE": 55,
    "RESOLVED_EXACT_DELEGATION": 50,
    "RESOLVED_POSTAL_CODE": 45,
    "RESOLVED_FUZZY_LOCALITE": 42,
    "RESOLVED_FUZZY_ALIAS": 40,
    "STEP1_GOUVSINI_DIMREGION_LINGUISTIC_LOCALITE": 57,
    "STEP2_CITESINI_DIMREGION_LINGUISTIC_LOCALITE": 47,
    "STEP3_REGSINI_DIMREGION_LINGUISTIC_LOCALITE": 47,
    "RESOLVED_GOVERNORATE_ONLY": 35,
    "AMBIGUOUS_EXACT_LOCALITE": 25,
    "AMBIGUOUS_ALIAS_LOCALITE": 24,
    "AMBIGUOUS_EXACT_DELEGATION": 23,
    "AMBIGUOUS_FUZZY_LOCALITE": 20,
    "AMBIGUOUS_FUZZY_ALIAS": 19,
    "UNRESOLVED_NO_REFERENCE": 10,
    "UNRESOLVED_POSTAL_ONLY": 5,
    "UNKNOWN": 0,
}
_POSTAL_STATUS_RANK = {
    "POSTAL_SOURCE_CONFIRMED_REFERENCE": 50,
    "POSTAL_APPROVED_CORRECTION": 48,
    "POSTAL_REFERENCE_EXACT_LOCALITE": 45,
    "POSTAL_REFERENCE_DELEGATION": 40,
    "POSTAL_REFERENCE_ALIAS": 35,
    "POSTAL_SOURCE_PREFIX_ONLY": 20,
    "POSTAL_SOURCE_UNCONFIRMED": 15,
    "POSTAL_MISSING_REFERENCE": 10,
    "POSTAL_NOT_APPLICABLE": 5,
    "POSTAL_ONLY_NO_GEOGRAPHY": 0,
}


def _write_deduplication_decisions(df_decisions: pd.DataFrame) -> None:
    GEO_QUALITY_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    cols = [
        "dedup_selected",
        "geo_key",
        "pays",
        "region",
        "gouvernorat",
        "localite",
        "code_postal",
        "geo_quality_level",
        "resolution_status",
        "postal_code_status",
        "resolution_confidence",
        "source_region",
        "source_gouvernorat",
        "source_localite",
        "source_code_postal",
        "_source_geo_key",
        "resolution_reason",
        "postal_code_reason",
        "_quality_rank",
        "_resolution_rank",
        "_postal_rank",
        "_confidence_rank",
    ]
    report = df_decisions.copy()
    for col in cols:
        if col not in report.columns:
            report[col] = ""
    report[cols].to_csv(DEDUP_DECISIONS_PATH, index=False, encoding="utf-8-sig")


def _deduplicate_resolved_rows(df_real: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    if df_real.empty:
        _write_deduplication_decisions(pd.DataFrame())
        return df_real.copy(), 0, 0

    ranked = df_real.copy()
    if "_resolution_row_id" not in ranked.columns:
        ranked["_resolution_row_id"] = range(len(ranked))
    ranked["_quality_rank"] = ranked["geo_quality_level"].map(_QUALITY_RANK).fillna(0).astype(int)
    ranked["_resolution_rank"] = ranked["resolution_status"].map(_RESOLUTION_RANK).fillna(1).astype(int)
    ranked["_postal_rank"] = ranked["postal_code_status"].map(_POSTAL_STATUS_RANK).fillna(1).astype(int)
    ranked["_confidence_rank"] = pd.to_numeric(ranked.get("resolution_confidence", 0), errors="coerce").fillna(0.0)

    ranked = ranked.sort_values(
        [
            "geo_key",
            "_quality_rank",
            "_resolution_rank",
            "_postal_rank",
            "_confidence_rank",
            "pays",
            "gouvernorat",
            "localite",
            "code_postal",
        ],
        ascending=[True, False, False, False, False, True, True, True, True],
    ).reset_index(drop=True)

    selected = ranked.drop_duplicates(subset=["geo_key"], keep="first").copy()
    selected_ids = set(selected["_resolution_row_id"].tolist())
    duplicate_keys = ranked.loc[ranked.duplicated("geo_key", keep=False), "geo_key"].unique().tolist()
    decisions = ranked[ranked["geo_key"].isin(duplicate_keys)].copy()
    decisions["dedup_selected"] = decisions["_resolution_row_id"].isin(selected_ids).map({True: "YES", False: "NO"})
    _write_deduplication_decisions(decisions)

    helper_cols = ["_quality_rank", "_resolution_rank", "_postal_rank", "_confidence_rank"]
    selected = selected.drop(columns=[col for col in helper_cols if col in selected.columns])
    return selected, len(ranked) - len(selected), len(decisions)


def _write_source_to_resolved_mapping(df_resolution: pd.DataFrame, df_final: pd.DataFrame) -> None:
    GEO_QUALITY_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    final_lookup = df_final[["geo_key", "geo_sk"]].drop_duplicates(subset=["geo_key"]).copy()
    mapping = df_resolution.copy()
    mapping["source_geo_key"] = mapping.get("_source_geo_key", "")
    mapping["resolved_pays"] = mapping.get("pays", _KEY_UNKNOWN)
    mapping["resolved_region"] = mapping.get("region", _KEY_UNKNOWN)
    mapping["resolved_gouvernorat"] = mapping.get("gouvernorat", _KEY_UNKNOWN)
    mapping["resolved_localite"] = mapping.get("localite", _KEY_UNKNOWN)
    mapping["resolved_code_postal"] = mapping.get("code_postal", _KEY_UNKNOWN)
    mapping["resolved_geo_key"] = mapping.get("geo_key", _GEO_KEY_UNKNOWN)
    mapping = mapping.merge(final_lookup, left_on="resolved_geo_key", right_on="geo_key", how="left", suffixes=("", "_dim"))
    cols = [
        "source_region",
        "source_gouvernorat",
        "source_localite",
        "source_code_postal",
        "source_geo_key",
        "resolved_pays",
        "resolved_region",
        "resolved_gouvernorat",
        "resolved_localite",
        "resolved_code_postal",
        "resolved_geo_key",
        "geo_sk",
        "resolution_status",
        "postal_code_status",
        "resolution_reason",
    ]
    for col in cols:
        if col not in mapping.columns:
            mapping[col] = ""
    mapping[cols].to_csv(SOURCE_TO_RESOLVED_MAPPING_PATH, index=False, encoding="utf-8-sig")
# ---------------------------------------------------------------------------
# Transformation
# ---------------------------------------------------------------------------

def transform_dim_geo(
    df_raw: pd.DataFrame,
    logger,
    corrections_by_key: dict[str, dict] | None = None,
    postal_corrections_by_key: dict[str, dict] | None = None,
    reference_indexes: dict | None = None,
    alias_dict: dict | None = None,
) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    n_raw = len(df_raw)
    corrections_by_key = corrections_by_key or {}
    postal_corrections_by_key = postal_corrections_by_key or {}
    reference_indexes = reference_indexes or {
        "localite": {},
        "alias": {},
        "delegation": {},
        "postal": {},
        "postal_localite": {},
        "postal_alias": {},
        "postal_delegation": {},
        "governorate_region": {},
    }
    alias_dict = alias_dict or {}

    resolution_records = [
        _resolve_one_geo_row(row, reference_indexes, corrections_by_key, alias_dict)
        for _, row in df_raw.iterrows()
    ]
    df_resolution = pd.DataFrame(resolution_records)
    if df_resolution.empty:
        df_resolution = pd.DataFrame(columns=[
            "pays", "region", "gouvernorat", "localite", "adresse_fragment",
            "code_postal", "geo_quality_level", "needs_review",
            "_source_geo_key", "resolution_status", "conflict_detected",
            "postal_code_status", "postal_code_method", "postal_code_reason",
            "postal_candidate_summary",
        ])
    for col in ("adresse_fragment", "needs_review", "conflict_detected"):
        if col not in df_resolution.columns:
            df_resolution[col] = "NO" if col != "adresse_fragment" else None
    df_resolution["_resolution_row_id"] = range(len(df_resolution))

    # Business finalization: UNKNOWN-fill + region from gouvernorat + rebuild geo_key.
    df_resolution = finalize_business_fields(df_resolution)

    # Step counts from cascade
    status_counts = df_resolution["resolution_status"].value_counts().to_dict()
    n_step1 = int(status_counts.get("STEP1_GOUVSINI", 0))
    n_step2 = int(status_counts.get("STEP2_CITESINI", 0))
    n_step3 = int(status_counts.get("STEP3_REGSINI", 0))
    n_step4 = int(status_counts.get("STEP4_POSTAL", 0))
    n_step5 = int(status_counts.get("STEP5_EXCLUDED", 0))

    logger.info(f"  Step 1 resolved (gouvsini)  : {n_step1}")
    logger.info(f"  Step 2 resolved (citesini)  : {n_step2}")
    logger.info(f"  Step 3 resolved (regsini)   : {n_step3}")
    logger.info(f"  Step 4 resolved (postal)    : {n_step4}")
    logger.info(f"  Step 5 excluded             : {n_step5}")

    # Separate excluded rows (gouvernorat = UNKNOWN) — write CSV but do not load to dim_geo
    excluded_mask = df_resolution["gouvernorat"] == _KEY_UNKNOWN
    df_excluded = df_resolution[excluded_mask].copy()
    df_included = df_resolution[~excluded_mask].copy()

    GEO_QUALITY_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    excluded_cols = [
        "source_gouvernorat", "source_localite", "source_code_postal", "source_region",
        "source_rue", "_source_geo_key", "resolution_status", "resolution_reason",
    ]
    for col in excluded_cols:
        if col not in df_excluded.columns:
            df_excluded[col] = ""
    df_excluded[excluded_cols].to_csv(DIM_GEO_EXCLUDED_PATH, index=False, encoding="utf-8-sig")
    logger.info(f"  excluded rows written       : {len(df_excluded)} → {DIM_GEO_EXCLUDED_PATH}")

    # Dedup included rows on 4-part geo_key
    df_real, n_dupes, n_dedup_decision_rows = _deduplicate_resolved_rows(df_included)

    df_real = df_real.sort_values(
        ["pays", "gouvernorat", "region", "localite", "code_postal", "geo_key"]
    ).reset_index(drop=True)
    df_real.insert(0, "geo_sk", range(1, len(df_real) + 1))
    df_real["source_system"] = SOURCE_SYSTEM
    df_real["source_context"] = SOURCE_CONTEXT
    df_real["created_at"] = TODAY

    unknown_row = pd.DataFrame([{
        "geo_sk": 0,
        "pays": _KEY_UNKNOWN,
        "region": _KEY_UNKNOWN,
        "gouvernorat": _KEY_UNKNOWN,
        "localite": _KEY_UNKNOWN,
        "adresse_fragment": None,
        "code_postal": _KEY_UNKNOWN,
        "geo_entity_type": "UNKNOWN",
        "geo_quality_level": "UNKNOWN",
        "needs_review": "NO",
        "geo_key": _GEO_KEY_UNKNOWN,
        "source_system": SOURCE_SYSTEM,
        "source_context": SOURCE_CONTEXT,
        "created_at": TODAY,
    }])

    df_final = pd.concat([unknown_row, df_real[FINAL_COLS]], ignore_index=True)
    df_final = _reassign_geo_sk(df_final)

    _write_resolution_reports(df_resolution, df_final)
    _write_source_to_resolved_mapping(df_resolution, df_final)

    region_dist = df_final["region"].value_counts().to_dict()
    ql = df_final["geo_quality_level"].value_counts().to_dict()
    postal_status_counts = df_resolution["postal_code_status"].astype(str).value_counts().to_dict()
    postal_missing_reference_count = int(df_resolution["postal_code_status"].eq("POSTAL_MISSING_REFERENCE").sum())

    # Stub metrics for keys expected by load_dim_geo logging
    _zero_postal = {
        "n_rows_postal_corrected": 0,
        "n_rows_postal_corrected_by_localite_fallback": 0,
        "n_postal_approved_corrections_matched": 0,
        "n_postal_approved_corrections_not_matched": 0,
        "n_postal_global_localite_no_gov_only": 0,
        "n_rejected_global_match_due_to_gov_conflict": 0,
    }

    metrics = {
        **_zero_postal,
        "n_raw": n_raw,
        "n_step1_gouvsini": n_step1,
        "n_step2_citesini": n_step2,
        "n_step3_regsini": n_step3,
        "n_step4_postal": n_step4,
        "n_step5_excluded": n_step5,
        "n_dupes": n_dupes,
        "n_dedup_decision_rows": n_dedup_decision_rows,
        "n_validated": ql.get("VALIDATED", 0),
        "n_partial": ql.get("PARTIAL", 0),
        "n_ambiguous": ql.get("AMBIGUOUS", 0),
        "n_unknown": ql.get("UNKNOWN", 0),
        "quality_distribution": ql,
        "resolution_distribution": status_counts,
        "postal_distribution": postal_status_counts,
        "n_loaded": len(df_final),
        "n_missing_postal_after_resolution": int(
            ((df_final["pays"] == "TUNISIE")
             & (df_final["gouvernorat"] != _KEY_UNKNOWN)
             & (df_final["code_postal"] == _KEY_UNKNOWN)).sum()
        ),
        "n_postal_from_reference_exact_localite": int(postal_status_counts.get("POSTAL_REFERENCE_EXACT_LOCALITE", 0)),
        "n_postal_missing_reference_rows": postal_missing_reference_count,
        "n_conflicts_after_resolution": int(df_resolution.get("conflict_detected", pd.Series(dtype=str)).eq("YES").sum()),
        "entity_type_distribution": df_final["geo_entity_type"].value_counts().to_dict() if "geo_entity_type" in df_final.columns else {},
        "region_distribution": region_dist,
        # legacy keys referenced in load_dim_geo logging (set to 0 / empty)
        "n_generated_before_corrections": len(df_resolution) + 1,
        "n_generated_before_postal_resolution": len(df_resolution) + 1,
        "n_unknown_natural": int(excluded_mask.sum()),
        "n_dropped_unknown_key": 0,
        "n_dupes_after_corrections": 0,
        "n_rows_corrected": 0,
        "n_approved_corrections_matched": 0,
        "n_approved_corrections_not_matched": 0,
        "n_reference_exact_localite_resolved": 0,
        "n_reference_alias_localite_resolved": 0,
        "n_reference_alias_manuel_resolved": 0,
        "n_reclassified_ambiguous_to_partial": 0,
        "n_alias_gov_propagated": 0,
        "n_address_fragment": 0,
        "n_address_fragment_needs_review": 0,
        "n_reference_delegation_resolved": 0,
        "n_reference_postal_resolved": 0,
        "n_reference_conflict_corrected": 0,
        "n_fuzzy_localite_resolved": 0,
        "n_fuzzy_alias_resolved": 0,
        "n_fuzzy_localite_ambiguous": 0,
        "n_fuzzy_alias_ambiguous": 0,
        "n_governorate_only": 0,
        "n_unresolved_no_reference": 0,
        "n_unresolved_postal_only": 0,
        "n_rows_with_source_postal_code": int(df_resolution["source_code_postal"].map(
            lambda x: normalize_cpost(x) is not None).sum()),
        "n_postal_from_source": 0,
        "n_postal_source_confirmed_reference": 0,
        "n_postal_source_prefix_only": 0,
        "n_postal_source_unconfirmed": 0,
        "n_postal_from_approved_corrections": 0,
        "n_postal_from_reference_delegation": 0,
        "n_postal_from_reference_alias": 0,
        "n_postal_ambiguous_rows": 0,
        "n_postal_conflict_rows": 0,
    }
    return df_final, metrics, df_resolution
# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_dim_geo(run_id: str, engine, logger) -> int:
    logger.info(f"[RUN {run_id}] {SOURCE_TABLE} -> dwh.{TABLE_NAME}")

    with engine.connect() as conn:
        exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'staging' AND table_name = 'stg_sinistres'
        """)).fetchone()
    if not exists:
        raise RuntimeError(
            f"Table source {SOURCE_TABLE} introuvable. "
            "Run load_sinistres_sa.py first."
        )

    df_raw = _extract_sinistre(engine, logger)

    if df_raw.empty:
        logger.warning("  No rows in staging.stg_sinistres; load cancelled")
        return 0

    df_ref, ref_metrics = _load_geo_reference(logger)
    df_postal_ref, postal_ref_metrics = _load_postal_reference(logger)
    alias_dict, alias_metrics = _load_geo_alias(logger)
    reference_indexes, reference_index_metrics = _build_reference_resolver_indexes(df_ref)
    postal_indexes, postal_index_metrics = _build_postal_resolver_indexes(df_postal_ref)
    reference_indexes = _merge_postal_indexes(reference_indexes, postal_indexes)
    corrections_by_key, corr_load_metrics = _load_approved_corrections(logger)
    postal_corrections_by_key, postal_corr_load_metrics = _load_postal_approved_corrections(logger)

    df_final, m, _df_resolution = transform_dim_geo(
        df_raw,
        logger,
        corrections_by_key,
        postal_corrections_by_key,
        reference_indexes,
        alias_dict,
    )
    m.update(ref_metrics)
    m.update(postal_ref_metrics)
    m.update(alias_metrics)
    m.update(reference_index_metrics)
    m.update(postal_index_metrics)
    m.update(corr_load_metrics)
    m.update(postal_corr_load_metrics)

    n_rows, elapsed = dwh_utils.write_to_dwh(df_final, engine, TABLE_NAME, logger)

    logger.info("=" * 60)
    logger.info(f"  combinaisons distinctes source     : {m['n_raw']}")
    logger.info(f"  lignes geo generees avant corrections : {m['n_generated_before_corrections']}")
    logger.info(f"  lignes geo avant resolution postale   : {m['n_generated_before_postal_resolution']}")
    logger.info(f"  referentiel geo lignes chargees    : {m['n_reference_rows']}")
    logger.info(f"  termes localite reference          : {m['n_reference_localite_terms']}")
    logger.info(f"  termes alias reference             : {m['n_reference_alias_terms']}")
    logger.info(f"  alias ETL manuel (ref_geo_alias)   : {m['n_geo_alias_entries']}")
    logger.info(f"  termes delegation reference        : {m['n_reference_delegation_terms']}")
    logger.info(f"  referentiel postal lignes chargees : {m['n_postal_reference_rows']}")
    logger.info(f"  referentiel postal lignes utiles   : {m['n_postal_reference_usable_rows']}")
    logger.info(f"  codes postaux ref postale          : {m['n_postal_reference_codes']}")
    logger.info(f"  ref postale par localite           : {m['n_postal_reference_localite_terms']}")
    logger.info(f"  ref postale par delegation         : {m['n_postal_reference_delegation_terms']}")
    logger.info(f"  ref postale par alias              : {m['n_postal_reference_alias_terms']}")
    logger.info(f"  gouvernorats avec region analytique: {m['n_reference_governorate_regions']}")
    logger.info(f"  localites reference ambigues       : {m['n_reference_ambiguous_localite_terms']}")
    logger.info(f"  corrections APPROVED chargees      : {m['n_approved_corrections_loaded']}")
    logger.info(f"  corrections APPROVED par geo_key   : {m['n_approved_corrections_by_geo_key']}")
    logger.info(f"  corrections postales APPROVED chargees : {m['n_postal_approved_corrections_loaded']}")
    logger.info(f"  corrections postales par geo_key       : {m['n_postal_approved_corrections_by_geo_key']}")

    logger.info(f"  Step 1 resolved (gouvsini)         : {m['n_step1_gouvsini']}")
    logger.info(f"  Step 2 resolved (citesini)         : {m['n_step2_citesini']}")
    logger.info(f"  Step 3 resolved (regsini)          : {m['n_step3_regsini']}")
    logger.info(f"  Step 4 resolved (postal prefix)    : {m['n_step4_postal']}")
    logger.info(f"  Step 5 excluded (no gouvernorat)   : {m['n_step5_excluded']}")
    logger.info(f"  excluded → {DIM_GEO_EXCLUDED_PATH.name}")
    logger.info(f"  doublons geo_key supprimes         : {m['n_dupes']}")
    logger.info(f"  lignes absorb. UNKNOWN naturels    : {m['n_unknown_natural']}")
    logger.info(f"  CP remplis GOV_LOCALITE            : {m['n_postal_from_reference_exact_localite']}")
    logger.info(f"  CP reference manquante             : {m['n_postal_missing_reference_rows']}")
    logger.info(f"  lignes TUNISIE sans code postal    : {m['n_missing_postal_after_resolution']}")
    logger.info(f"  zones VALIDATED                    : {m['n_validated']}")
    logger.info(f"  zones PARTIAL                      : {m['n_partial']}")
    logger.info(f"  zones AMBIGUOUS                    : {m['n_ambiguous']}")
    logger.info(f"  ancre UNKNOWN (geo_sk=0)           : {m['n_unknown']}")
    logger.info(f"  total lignes apres corrections     : {m['n_loaded']}")
    logger.info(f"  distribution geo_quality_level     : {m['quality_distribution']}")
    logger.info(f"  distribution region                : {m['region_distribution']}")
    logger.info(f"  distribution geo_entity_type       : {m['entity_type_distribution']}")
    logger.info(f"  distribution resolution            : {m['resolution_distribution']}")
    logger.info(f"  distribution code postal           : {m['postal_distribution']}")
    logger.info(f"  rapport resolution                 : {RESOLUTION_REPORT_PATH}")
    logger.info(f"  unresolved                         : {UNRESOLVED_REPORT_PATH}")
    logger.info(f"  conflits apres resolution          : {CONFLICTS_AFTER_RESOLUTION_PATH}")
    logger.info(f"  codes postaux a enrichir           : {MISSING_POSTAL_REPORT_PATH}")
    logger.info(f"  codes postaux ambigus              : {POSTAL_AMBIGUOUS_REPORT_PATH}")
    logger.info(f"  codes postaux conflits             : {POSTAL_CONFLICTS_REPORT_PATH}")
    logger.info(f"  codes postaux reference manquante  : {POSTAL_MISSING_REFERENCE_REPORT_PATH}")
    logger.info(f"  CP seuls resolus                   : {POSTAL_ONLY_RESOLVED_PATH}")
    logger.info(f"  CP seuls non resolus               : {POSTAL_ONLY_UNRESOLVED_PATH}")
    logger.info(f"  corrections postales non matchees  : {POSTAL_APPROVED_UNMATCHED_PATH}")
    logger.info(f"  conflits gouvernorat/localite      : {GOV_LOCALITY_CONFLICTS_PATH}")
    logger.info(f"  decisions deduplication            : {DEDUP_DECISIONS_PATH}")
    logger.info(f"  mapping source vers dim_geo        : {SOURCE_TO_RESOLVED_MAPPING_PATH}")
    logger.info(f"  load duration                      : {elapsed:.1f}s")
    logger.info("=" * 60)

    logger.info("Validation SQL queries:")
    logger.info("""
SELECT
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE pays IS NULL) AS pays_null,
    COUNT(*) FILTER (WHERE region IS NULL) AS region_null,
    COUNT(*) FILTER (WHERE gouvernorat IS NULL) AS gouvernorat_null,
    COUNT(*) FILTER (WHERE localite IS NULL) AS localite_null,
    COUNT(*) FILTER (WHERE code_postal IS NULL) AS code_postal_null,
    COUNT(*) FILTER (WHERE geo_key IS NULL) AS geo_key_null
FROM dwh.dim_geo;

SELECT geo_key, COUNT(*) AS nb
FROM dwh.dim_geo
GROUP BY geo_key
HAVING COUNT(*) > 1;

SELECT geo_quality_level, COUNT(*) AS nb
FROM dwh.dim_geo
GROUP BY geo_quality_level
ORDER BY nb DESC;

SELECT COUNT(*) AS postal_only_bad_rows
FROM dwh.dim_geo
WHERE pays = 'TUNISIE'
  AND region = 'UNKNOWN'
  AND gouvernorat = 'UNKNOWN'
  AND localite = 'UNKNOWN'
  AND code_postal <> 'UNKNOWN';

SELECT COUNT(*) AS remaining_unknown_postal_with_full_geo
FROM dwh.dim_geo
WHERE pays = 'TUNISIE'
  AND region <> 'UNKNOWN'
  AND gouvernorat <> 'UNKNOWN'
  AND localite <> 'UNKNOWN'
  AND code_postal = 'UNKNOWN';

SELECT *
FROM dwh.dim_geo
WHERE geo_key = 'UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN';
""")

    print("=" * 60)
    print(f"  Step 1 resolved (gouvsini)   : {m['n_step1_gouvsini']}")
    print(f"  Step 2 resolved (citesini)   : {m['n_step2_citesini']}")
    print(f"  Step 3 resolved (regsini)    : {m['n_step3_regsini']}")
    print(f"  Step 4 resolved (postal)     : {m['n_step4_postal']}")
    print(f"  Step 5 excluded              : {m['n_step5_excluded']}")
    print(f"  Total loaded into dwh.dim_geo: {m['n_loaded']}")
    print("=" * 60)

    return n_rows


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _logger = dwh_utils.setup_logging(_run_id, log_name="load_dim_geo")
    _engine = dwh_utils.build_engine(_logger)
    dwh_utils.create_dwh_schema(_engine, _logger)
    _n = load_dim_geo(_run_id, _engine, _logger)
    _logger.info(f"Done: {_n} rows -> dwh.{TABLE_NAME}")

















