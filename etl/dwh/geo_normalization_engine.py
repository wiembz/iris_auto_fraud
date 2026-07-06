"""
etl/dwh/geo_normalization_engine.py
=====================================
Controlled geographic normalization engine for IRIS.

This engine does NOT blindly correct addresses. It keeps original source values,
proposes normalized values, assigns a confidence score and classifies each row
with a geo_quality_level for downstream Power BI and scoring usage.

The script is idempotent: the audit table is fully reloaded on each run.
A view dwh.v_dim_geo_normalized exposes the normalized values safely.

Do NOT add fraud scoring logic here.
This task is only about controlled geographic normalization for dwh.dim_geo.
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

# ---------------------------------------------------------------------------
# Fuzzy backend — rapidfuzz preferred, difflib fallback (no extra dependency)
# ---------------------------------------------------------------------------
try:
    from rapidfuzz.fuzz import ratio as _rf_ratio
    from rapidfuzz.process import extract as _rf_extract

    def _fuzz_score(a: str, b: str) -> float:
        return float(_rf_ratio(a, b))

    def _fuzz_top_n(query: str, choices: list[str], n: int = 2) -> list[tuple[str, float]]:
        return [(m, float(s)) for m, s, _ in _rf_extract(query, choices, limit=n)]

    _FUZZY_BACKEND = "rapidfuzz"
except ImportError:
    from difflib import SequenceMatcher

    def _fuzz_score(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100.0

    def _fuzz_top_n(query: str, choices: list[str], n: int = 2) -> list[tuple[str, float]]:
        scored = sorted(
            ((c, _fuzz_score(query, c)) for c in choices),
            key=lambda x: x[1],
            reverse=True,
        )
        return scored[:n]

    _FUZZY_BACKEND = "difflib"

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent

AUDIT_TABLE  = "geo_normalization_audit"
VIEW_NAME    = "v_dim_geo_normalized"
SOURCE_TABLE = "dwh.dim_geo"
TODAY        = datetime.now(timezone.utc).replace(tzinfo=None)

GEO_REFERENCE_PATH = BASE_DIR / "data" / "reference" / "dim_geo" / "geo_tunisia_reference.csv"
GEO_ALIAS_PATH     = BASE_DIR / "data" / "reference" / "dim_geo" / "ref_geo_alias.csv"

# Fuzzy score thresholds (0–100 scale)
FUZZY_HIGH_THRESHOLD   = 92.0   # ≥ 92 → FUZZY_HIGH  → VALIDATED
FUZZY_MEDIUM_THRESHOLD = 80.0   # 80–92 → FUZZY_MEDIUM → AMBIGUOUS (needs review)
FUZZY_MIN_GAP          = 5.0    # minimum gap between top-2 to avoid forced ambiguity

# ---------------------------------------------------------------------------
# Geographic constants
# ---------------------------------------------------------------------------
_VALID_GOVERNORATS = frozenset({
    "TUNIS", "ARIANA", "BEN AROUS", "MANOUBA",
    "NABEUL", "ZAGHOUAN", "BIZERTE",
    "BEJA", "JENDOUBA", "KEF", "SILIANA",
    "SOUSSE", "MONASTIR", "MAHDIA", "SFAX",
    "KAIROUAN", "KASSERINE", "SIDI BOUZID",
    "GABES", "MEDENINE", "TATAOUINE",
    "GAFSA", "TOZEUR", "KEBILI",
})

_INVALID_TEXT = frozenset({
    "", "NULL", "NAN", "NONE", "UNKNOWN", "INCONNU", "INCONNUE",
    "NON RENSEIGNE", "NON RENSEIGNEE", "N/A", "N A", "NA", "#N/A",
    "ND", "NR", "/", "-", "--", "---", ".", "..", "0", "0000", "1",
})

# ---------------------------------------------------------------------------
# Entity-type patterns
# ---------------------------------------------------------------------------
_PAT_ADRESSE = re.compile(
    r'\b(AV|AVE|AVENUE|BD|BLVD|BOULEVARD|RUE|IMPASSE|ALLEE|PASSAGE|RUELLE|IMMEUBLE|IMM|N\s*\d+)\b'
)
_PAT_ROUTE = re.compile(
    r'\b(ROUTE|RTE|AUTOROUTE|GP\s*\d*|RN\s*\d*|\d+\s*KM|MC\s*\d+|ROCADE|CONTOURNEMENT)\b'
)
_PAT_INTERET = re.compile(
    r'\b(AEROPORT|GARE|PORT|HOPITAL|CLINIQUE|UNIVERSITE|STADE|TECHNOPOLE|FOIRE|MARCHE|SOUK|COMPLEXE|CARTHAGE AIRPORT|'
    r'HOTEL|BANQUE|BANK|PARKING|ROND\s*POINT|RONDPOINT|CARREFOUR)\b'
)
_PAT_ZONE = re.compile(
    r'\b(CITE|ZONE|ZI|ZA|ZIT|QUARTIER|QT|RESIDENCE|RES|LOTISSEMENT|LOT|BLOC|'
    r'LAC|CHARGUIA|MENZAH|EL MENZAH|ENNASR|MANAR|CENTRE URBAIN|JARDINS|GHAZELA)\b'
)

# Abbreviation normalization applied during text cleaning
_ABBREV_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bAVE\b'),      "AV"),
    (re.compile(r'\bAVENUE\b'),   "AV"),
    (re.compile(r'\bBLVD\b'),     "BD"),
    (re.compile(r'\bBOULEVARD\b'), "BD"),
    (re.compile(r'\bRTE\b'),      "ROUTE"),
    (re.compile(r'\bCITEE\b'),    "CITE"),
    (re.compile(r'\bCTE\b'),      "CITE"),
]

# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

def normalize_text(value) -> str | None:
    """Clean and normalize a geographic text value for matching.

    Handles NULL, strips spaces, removes accents, standardizes abbreviations.
    Returns None for empty or semantically void values.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    s = unicodedata.normalize("NFKD", str(value))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.upper()
    s = re.sub(r"['’‘`]", " ", s)   # apostrophes
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s or s in _INVALID_TEXT:
        return None
    for pattern, replacement in _ABBREV_RULES:
        s = pattern.sub(replacement, s)
    s = re.sub(r"\s+", " ", s).strip()
    return None if (not s or s in _INVALID_TEXT) else s


def normalize_cpost(value) -> str | None:
    """Normalize to a 4-digit Tunisian postal code string, or None."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    try:
        val = int(digits)
    except ValueError:
        return None
    return str(val).zfill(4) if 700 <= val <= 9999 else None

# ---------------------------------------------------------------------------
# Entity type classification
# ---------------------------------------------------------------------------

def classify_geo_entity_type(localite_clean: str | None) -> str:
    """Classify a normalized localite string into a geographic entity category.

    Returns one of: LOCALITE, QUARTIER_ZONE, ADRESSE_PARTIELLE, ROUTE_AUTOROUTE,
    POINT_INTERET, GOUVERNORAT, UNKNOWN.
    """
    if not localite_clean or localite_clean in _INVALID_TEXT:
        return "UNKNOWN"
    s = localite_clean
    if s in _VALID_GOVERNORATS:
        return "GOUVERNORAT"
    if _PAT_ADRESSE.search(s):
        return "ADRESSE_PARTIELLE"
    if _PAT_ROUTE.search(s):
        return "ROUTE_AUTOROUTE"
    if _PAT_INTERET.search(s):
        return "POINT_INTERET"
    if _PAT_ZONE.search(s):
        return "QUARTIER_ZONE"
    return "LOCALITE"

# ---------------------------------------------------------------------------
# Reference and alias loading
# ---------------------------------------------------------------------------

def _load_reference(logger) -> tuple[dict[str, list[dict]], list[str], list[str]]:
    """Load geo_tunisia_reference.csv and build a normalized localite index.

    Returns (index, all_ref_terms, canonical_terms) where:
    - index: maps any normalized term (localite/delegation/alias) → list of ref dicts
    - all_ref_terms: every indexed term (used for diagnostics only)
    - canonical_terms: primary localite names ONLY — used for fuzzy matching to avoid
      false matches through delegation keys that may index different localities.

    Root-cause note: delegation keys in `index` can map to multiple localities
    (e.g. key "MAHDIA" → [EZZAHRA, MAHDIA, ...]).  Fuzzy matching against
    canonical_terms ensures we only ever propose the primary localite name as the
    fuzzy match target, then the primary-ref filter below resolves the correct entry.
    """
    if not GEO_REFERENCE_PATH.exists():
        logger.warning(f"  Reference absent: {GEO_REFERENCE_PATH}")
        return {}, [], []

    df = pd.read_csv(GEO_REFERENCE_PATH, dtype=str, keep_default_na=False)
    df.columns = [c.strip().lower() for c in df.columns]
    logger.info(f"  Reference: {len(df)} rows  ({GEO_REFERENCE_PATH.name})")

    index: dict[str, list[dict]] = {}
    canonical_terms: list[str] = []

    def _add(term: str, ref: dict) -> None:
        if term:
            index.setdefault(term, []).append(ref)

    for _, row in df.iterrows():
        loc      = normalize_text(row.get("localite", ""))
        deleg    = normalize_text(row.get("delegation", ""))
        gouv     = normalize_text(row.get("gouvernorat", ""))
        region   = normalize_text(row.get("region", ""))
        cp       = normalize_cpost(row.get("code_postal", ""))
        if not loc:
            continue
        ref = {
            "localite_reference": loc,
            "gouvernorat":        gouv or "UNKNOWN",
            "region":             region or "UNKNOWN",
            "delegation":         deleg or "UNKNOWN",
            "code_postal":        cp,
        }
        _add(loc, ref)
        canonical_terms.append(loc)  # primary localite name — safe for fuzzy matching
        if deleg and deleg != loc:
            _add(deleg, ref)         # delegation key → NOT added to canonical_terms
        for part in re.split(r"[|;]", str(row.get("aliases", ""))):
            alias = normalize_text(part)
            if alias and alias != loc:
                _add(alias, ref)     # CSV alias → NOT added to canonical_terms

    all_terms = list(index.keys())
    logger.info(
        f"  Reference index: {len(all_terms)} total terms "
        f"({len(canonical_terms)} canonical localites)"
    )
    return index, all_terms, canonical_terms


def _load_aliases(logger) -> dict[str, dict]:
    """Load ref_geo_alias.csv keyed by normalized alias_source.

    Returns an empty dict if the file is absent (non-fatal).
    """
    if not GEO_ALIAS_PATH.exists():
        logger.warning(f"  Alias file absent: {GEO_ALIAS_PATH} — alias matching disabled")
        return {}

    df = pd.read_csv(GEO_ALIAS_PATH, dtype=str, keep_default_na=False)
    df.columns = [c.strip().lower() for c in df.columns]
    logger.info(f"  Aliases: {len(df)} rows  ({GEO_ALIAS_PATH.name})")

    index: dict[str, dict] = {}
    for _, row in df.iterrows():
        active = str(row.get("is_active", "1")).strip().upper()
        if active in ("0", "FALSE", "NO", "N"):
            continue
        key = normalize_text(row.get("alias_source", ""))
        if not key:
            continue
        try:
            score = float(str(row.get("confidence_score", "0.95")).replace(",", "."))
        except (ValueError, TypeError):
            score = 0.95
        index[key] = {
            "localite_reference":   normalize_text(row.get("localite_reference", "")) or "UNKNOWN",
            "gouvernorat_reference": normalize_text(row.get("gouvernorat_reference", "")) or "",
            "region_reference":      normalize_text(row.get("region_reference", "")) or "",
            "alias_type":            str(row.get("alias_type", "TYPO")).strip().upper(),
            "confidence_score":      max(0.0, min(1.0, score)),
            "commentaire":           str(row.get("commentaire", "")).strip(),
        }
    logger.info(f"  Alias index: {len(index)} active entries")
    return index

# ---------------------------------------------------------------------------
# Row normalization pipeline
# ---------------------------------------------------------------------------

def _normalize_row(
    row: dict,
    ref_index: dict[str, list[dict]],
    canonical_terms: list[str],
    alias_index: dict[str, dict],
) -> dict:
    """Apply the full normalization pipeline to one dim_geo row."""
    geo_sk      = row.get("geo_sk")
    geo_key     = str(row.get("geo_key") or "")
    pays_src    = str(row.get("pays") or "")
    region_src  = str(row.get("region") or "")
    gouv_src    = str(row.get("gouvernorat") or "")
    loc_src     = str(row.get("localite") or "")
    cp_src      = str(row.get("code_postal") or "")

    # Step 1 — clean source values
    region_clean = normalize_text(region_src)
    gouv_clean   = normalize_text(gouv_src)
    loc_clean    = normalize_text(loc_src)
    cp_clean     = normalize_cpost(cp_src)
    gouv_valid   = gouv_clean if gouv_clean in _VALID_GOVERNORATS else None

    # Step 2 — entity type on source localite
    entity_type = classify_geo_entity_type(loc_clean)

    # Helpers: sensible defaults
    pays_norm  = normalize_text(pays_src) or "UNKNOWN"
    reg_norm   = region_clean or "UNKNOWN"
    gouv_norm  = gouv_clean or "UNKNOWN"
    loc_norm   = loc_clean or "UNKNOWN"
    cp_norm    = cp_clean or "UNKNOWN"

    def _row(pays_n, reg_n, gouv_n, loc_n, cp_n,
             entity, method, score, quality, review,
             c1, c1s, c2, c2s, reason):
        return {
            "geo_sk":                geo_sk,
            "geo_key":               geo_key,
            "pays_source":           pays_src,
            "region_source":         region_src,
            "gouvernorat_source":    gouv_src,
            "localite_source":       loc_src,
            "code_postal_source":    cp_src,
            "region_clean":          region_clean or "",
            "gouvernorat_clean":     gouv_clean or "",
            "localite_clean":        loc_clean or "",
            "code_postal_clean":     cp_clean or "",
            "pays_normalise":        pays_n,
            "region_normalisee":     reg_n,
            "gouvernorat_normalise": gouv_n,
            "localite_normalisee":   loc_n,
            "code_postal_normalise": cp_n,
            "geo_entity_type":       entity,
            "match_method":          method,
            "confidence_score":      round(float(score), 4),
            "geo_quality_level":     quality,
            "needs_review":          bool(review),
            "candidate_1":           c1 or "",
            "candidate_1_score":     round(float(c1s), 2) if c1s is not None else None,
            "candidate_2":           c2 or "",
            "candidate_2_score":     round(float(c2s), 2) if c2s is not None else None,
            "match_reason":          reason,
            "created_at":            TODAY,
        }

    # ── A. No geographic signal at all ───────────────────────────────────────
    if not loc_clean and not gouv_valid and not cp_clean:
        return _row(
            pays_norm, "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN",
            "UNKNOWN", "UNKNOWN", 0.0, "UNKNOWN", False,
            None, None, None, None, "no usable geographic signal",
        )

    # ── B. Address/route fragment ─────────────────────────────────────────────
    if entity_type in ("ADRESSE_PARTIELLE", "ROUTE_AUTOROUTE"):
        if gouv_valid:
            return _row(
                "TUNISIE", reg_norm, gouv_valid, "UNKNOWN", cp_norm,
                entity_type, "ADDRESS_FRAGMENT", 0.50, "PARTIAL", False,
                None, None, None, None,
                f"address/route fragment with confirmed gouvernorat={gouv_valid}; locality not inferred",
            )
        return _row(
            pays_norm, reg_norm, gouv_norm, "UNKNOWN", cp_norm,
            entity_type, "ADDRESS_FRAGMENT", 0.0, "PARTIAL", True,
            None, None, None, None,
            f"address/route fragment; no gouvernorat to confirm geography (entity_type={entity_type})",
        )

    # ── C. No localite but valid gouvernorat ──────────────────────────────────
    if not loc_clean and gouv_valid:
        return _row(
            "TUNISIE", reg_norm, gouv_valid, "UNKNOWN", cp_norm,
            entity_type, "GOVERNORATE_ONLY", 0.60, "PARTIAL", False,
            None, None, None, None,
            f"no localite signal; gouvernorat={gouv_valid} retained",
        )

    # ── D. Exact reference match ──────────────────────────────────────────────
    if loc_clean and loc_clean in ref_index:
        refs = ref_index[loc_clean]
        # Narrow to same governorate when possible
        if gouv_valid:
            gov_refs = [r for r in refs if r.get("gouvernorat") == gouv_valid]
            best = gov_refs if gov_refs else refs
        else:
            best = refs

        def _exact_gov_conflict(ref_gov: str) -> bool:
            """True when source and reference governorates are both valid and differ.

            Only fires when gov_refs was EMPTY — meaning the reference has no entry
            for the source gouvernorat, yet we still found the localite name in the
            index under a different gouvernorat (e.g. ARIANA found but source says
            BEN AROUS).  When gov_refs was non-empty, best is already filtered to
            matching governorates so this check will always return False there.
            """
            return (
                gouv_valid is not None
                and ref_gov not in ("", "UNKNOWN")
                and ref_gov != gouv_valid
            )

        if len(best) == 1:
            ref = best[0]
            if _exact_gov_conflict(ref["gouvernorat"]):
                return _row(
                    "TUNISIE", ref["region"], ref["gouvernorat"],
                    ref["localite_reference"], cp_clean or ref.get("code_postal") or "UNKNOWN",
                    entity_type, "EXACT_REFERENCE_GOV_CONFLICT", 0.80, "AMBIGUOUS", True,
                    loc_clean, 100.0, None, None,
                    f"exact reference match but gouvernorat conflict: "
                    f"source={gouv_valid!r} ≠ reference={ref['gouvernorat']!r} "
                    f"— retaining reference gouvernorat for audit; review required",
                )
            return _row(
                "TUNISIE", ref["region"], ref["gouvernorat"],
                ref["localite_reference"], cp_clean or ref.get("code_postal") or "UNKNOWN",
                entity_type, "EXACT_REFERENCE", 1.0, "VALIDATED", False,
                loc_clean, 100.0, None, None,
                f"exact reference match (gouvernorat={ref['gouvernorat']})",
            )
        if len(best) > 1:
            # If all candidates agree on the same canonical name, check conflict then VALIDATED
            canonical_names = {r["localite_reference"] for r in best}
            ref = best[0]
            if len(canonical_names) == 1:
                if _exact_gov_conflict(ref["gouvernorat"]):
                    return _row(
                        "TUNISIE", ref["region"], ref["gouvernorat"],
                        ref["localite_reference"], cp_clean or ref.get("code_postal") or "UNKNOWN",
                        entity_type, "EXACT_REFERENCE_GOV_CONFLICT", 0.80, "AMBIGUOUS", True,
                        loc_clean, 100.0, None, None,
                        f"exact reference match but gouvernorat conflict: "
                        f"source={gouv_valid!r} ≠ reference={ref['gouvernorat']!r} "
                        f"({len(best)} sub-entries, all agree on {list(canonical_names)[0]})",
                    )
                return _row(
                    "TUNISIE", ref["region"], ref["gouvernorat"],
                    ref["localite_reference"], cp_clean or ref.get("code_postal") or "UNKNOWN",
                    entity_type, "EXACT_REFERENCE", 1.0, "VALIDATED", False,
                    loc_clean, 100.0, None, None,
                    f"exact reference match ({len(best)} sub-entries all agree on {list(canonical_names)[0]})",
                )
            return _row(
                "TUNISIE", ref["region"], ref["gouvernorat"],
                ref["localite_reference"], cp_clean or "UNKNOWN",
                entity_type, "EXACT_REFERENCE_AMBIGUOUS", 0.80, "AMBIGUOUS", True,
                loc_clean, 100.0, None, None,
                f"exact match: {len(canonical_names)} different canonical names possible "
                f"({', '.join(list(canonical_names)[:3])}) — context insufficient",
            )

    # ── E. Alias match ────────────────────────────────────────────────────────
    if loc_clean and loc_clean in alias_index:
        al       = alias_index[loc_clean]
        al_score = al["confidence_score"]
        al_loc   = al["localite_reference"]
        al_gov   = al.get("gouvernorat_reference") or gouv_norm
        al_reg   = al.get("region_reference") or reg_norm
        al_entity = classify_geo_entity_type(al_loc)

        # Enrich alias target from reference if possible
        if al_loc in ref_index:
            gov_refs = [r for r in ref_index[al_loc] if r.get("gouvernorat") == al_gov]
            if gov_refs:
                al_gov = gov_refs[0]["gouvernorat"]
                al_reg = gov_refs[0]["region"]

        # Gouvernorat conflict check: alias CSV specifies a known gouvernorat that
        # differs from the source row's gouvernorat.  Only fires when al_gov is a
        # *valid* gouvernorat name (not an empty fallback or "UNKNOWN").
        al_gov_is_valid   = al_gov in _VALID_GOVERNORATS
        al_gov_conflict   = (
            gouv_valid is not None
            and al_gov_is_valid
            and al_gov != gouv_valid
        )
        pays_out = "TUNISIE" if al_gov_is_valid else pays_norm

        if al_gov_conflict:
            return _row(
                pays_out, al_reg or reg_norm, al_gov or gouv_norm, al_loc, cp_norm,
                al_entity, "ALIAS_GOV_CONFLICT", min(al_score, 0.80), "AMBIGUOUS", True,
                loc_clean, al_score * 100.0, None, None,
                f"alias: {loc_src!r} → {al_loc!r} (type={al['alias_type']}, score={al_score:.2f})"
                f" but gouvernorat conflict: source={gouv_valid!r} ≠ alias={al_gov!r}"
                + (f"; {al['commentaire']}" if al.get("commentaire") else ""),
            )

        if al_score >= 0.90 and al_entity not in ("ADRESSE_PARTIELLE", "ROUTE_AUTOROUTE"):
            quality, review = "VALIDATED", False
        elif al_entity in ("ADRESSE_PARTIELLE", "ROUTE_AUTOROUTE"):
            quality, review = "PARTIAL", True
        elif al_score >= 0.85:
            quality, review = "PARTIAL", False
        else:
            quality, review = "AMBIGUOUS", True

        return _row(
            pays_out, al_reg or reg_norm, al_gov or gouv_norm, al_loc, cp_norm,
            al_entity, "ALIAS_MANUEL", al_score, quality, review,
            loc_clean, al_score * 100.0, None, None,
            f"alias: {loc_src!r} → {al_loc!r} "
            f"(type={al['alias_type']}, score={al_score:.2f})"
            + (f"; {al['commentaire']}" if al.get("commentaire") else ""),
        )

    # ── F. Fuzzy matching (locality-like entities only) ───────────────────────
    # Fuzzy match is performed against canonical_terms only (primary localite
    # names from the CSV localite column).  This avoids false positives caused
    # by delegation keys in ref_index that can map to multiple different
    # localities (e.g. key "MAHDIA" indexes both MAHDIA and EZZAHRA because
    # EZZAHRA's delegation is Mahdia).
    if loc_clean and entity_type not in ("ADRESSE_PARTIELLE", "ROUTE_AUTOROUTE") and canonical_terms:
        top2   = _fuzz_top_n(loc_clean, canonical_terms, n=2)
        c1     = top2[0][0] if top2 else None
        c1s    = top2[0][1] if top2 else 0.0
        c2     = top2[1][0] if len(top2) > 1 else None
        c2s    = top2[1][1] if len(top2) > 1 else 0.0
        gap    = c1s - c2s

        def _resolve_fuzzy_ref(matched_term: str) -> dict:
            """Pick the best reference dict for a fuzzy-matched canonical term.

            Prefer refs where localite_reference == matched_term (primary entries),
            then narrow by gouvernorat context when available.
            """
            all_r = ref_index.get(matched_term, [])
            # Primary filter: only refs whose canonical name IS the matched term
            primary = [r for r in all_r if r.get("localite_reference") == matched_term]
            pool    = primary if primary else all_r
            if gouv_valid:
                gov_r = [r for r in pool if r.get("gouvernorat") == gouv_valid]
                return gov_r[0] if gov_r else (pool[0] if pool else {})
            return pool[0] if pool else {}

        if c1 and c1s >= FUZZY_HIGH_THRESHOLD and (c2 is None or gap >= FUZZY_MIN_GAP):
            ref     = _resolve_fuzzy_ref(c1)
            ref_gov = ref.get("gouvernorat", "")
            # Gouvernorat contradiction: source and reference disagree — reject HIGH
            if gouv_valid and ref_gov and ref_gov not in ("UNKNOWN", "") and ref_gov != gouv_valid:
                confidence = min(0.75, c1s / 100.0)
                return _row(
                    pays_norm, reg_norm, gouv_valid, loc_norm, cp_norm,
                    entity_type, "FUZZY_HIGH_GOV_CONFLICT", confidence, "AMBIGUOUS", True,
                    c1, c1s, c2, c2s,
                    f"fuzzy HIGH {c1s:.1f} for {loc_clean!r}→{c1!r} REJECTED: "
                    f"source gouvernorat {gouv_valid!r} ≠ reference gouvernorat {ref_gov!r}",
                )
            confidence = min(1.0, c1s / 100.0)
            return _row(
                "TUNISIE",
                ref.get("region", reg_norm), ref.get("gouvernorat", gouv_norm),
                ref.get("localite_reference", c1), cp_clean or ref.get("code_postal") or "UNKNOWN",
                entity_type, "FUZZY_HIGH", confidence, "VALIDATED", False,
                c1, c1s, c2, c2s,
                f"fuzzy HIGH: {loc_clean!r} → {c1!r} (score={c1s:.1f}, gap={gap:.1f})",
            )

        if c1 and c1s >= FUZZY_MEDIUM_THRESHOLD:
            ref        = _resolve_fuzzy_ref(c1)
            ref_gov    = ref.get("gouvernorat", "")
            confidence = min(0.85, c1s / 100.0)
            gov_conflict = (
                gouv_valid and ref_gov and ref_gov not in ("UNKNOWN", "")
                and ref_gov != gouv_valid
            )
            reason = (
                f"fuzzy MEDIUM: {loc_clean!r} → {c1!r} (score={c1s:.1f}, gap={gap:.1f})"
                + (f" — gouvernorat conflict: {gouv_valid} vs {ref_gov}" if gov_conflict else "")
                + " — needs review"
            )
            return _row(
                "TUNISIE" if ref_gov else pays_norm,
                ref.get("region", reg_norm), ref_gov or gouv_norm,
                ref.get("localite_reference", c1), cp_clean or "UNKNOWN",
                entity_type, "FUZZY_MEDIUM", confidence, "AMBIGUOUS", True,
                c1, c1s, c2, c2s, reason,
            )

    # ── G. Governorate retained, locality unresolved ──────────────────────────
    if gouv_valid:
        return _row(
            "TUNISIE", reg_norm, gouv_valid, loc_norm, cp_norm,
            entity_type, "GOVERNORATE_ONLY", 0.55, "PARTIAL", False,
            None, None, None, None,
            f"no reference/alias/fuzzy match for {loc_clean!r}; gouvernorat={gouv_valid} retained",
        )

    # ── H. Unresolved ────────────────────────────────────────────────────────
    return _row(
        pays_norm, reg_norm, gouv_norm, loc_norm, cp_norm,
        entity_type, "UNRESOLVED", 0.0, "AMBIGUOUS", True,
        None, None, None, None,
        f"no match found for {loc_clean!r}; geography retained as-is",
    )


# ---------------------------------------------------------------------------
# View creation
# ---------------------------------------------------------------------------

def _create_normalized_view(engine, logger) -> None:
    """Create or replace dwh.v_dim_geo_normalized."""
    ddl = f"""
CREATE OR REPLACE VIEW dwh.{VIEW_NAME} AS
SELECT
    d.geo_sk,
    COALESCE(NULLIF(a.pays_normalise,        'UNKNOWN'), d.pays)        AS pays,
    COALESCE(NULLIF(a.region_normalisee,     'UNKNOWN'), d.region)      AS region,
    COALESCE(NULLIF(a.gouvernorat_normalise, 'UNKNOWN'), d.gouvernorat) AS gouvernorat,
    CASE
        WHEN a.localite_normalisee IS NOT NULL
         AND a.localite_normalisee <> 'UNKNOWN'
        THEN a.localite_normalisee
        ELSE d.localite
    END                                                                   AS localite,
    COALESCE(NULLIF(a.code_postal_normalise, 'UNKNOWN'), d.code_postal) AS code_postal,
    a.geo_entity_type,
    COALESCE(a.geo_quality_level, d.geo_quality_level)                  AS geo_quality_level,
    a.match_method,
    a.confidence_score,
    a.needs_review,
    d.pays        AS pays_source,
    d.region      AS region_source,
    d.gouvernorat AS gouvernorat_source,
    d.localite    AS localite_source,
    d.code_postal AS code_postal_source,
    d.geo_key,
    d.source_system,
    d.source_context,
    d.created_at  AS dim_created_at
FROM dwh.dim_geo d
LEFT JOIN dwh.{AUDIT_TABLE} a ON a.geo_sk = d.geo_sk;
"""
    with engine.begin() as conn:
        conn.execute(text(ddl))
    logger.info(f"  View dwh.{VIEW_NAME} created or replaced")


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def run_geo_normalization(run_id: str, engine, logger) -> int:
    logger.info(f"[RUN {run_id}] geo_normalization_engine")
    logger.info(f"  Fuzzy backend: {_FUZZY_BACKEND}")
    logger.info(f"  FUZZY_HIGH >= {FUZZY_HIGH_THRESHOLD:.0f}, FUZZY_MEDIUM >= {FUZZY_MEDIUM_THRESHOLD:.0f}")

    # ── 1. Read dim_geo ───────────────────────────────────────────────────────
    with engine.connect() as conn:
        exists = conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'dwh' AND table_name = 'dim_geo'"
        )).fetchone()
    if not exists:
        raise RuntimeError("dwh.dim_geo not found — run load_dim_geo.py first")

    with engine.connect() as conn:
        df_geo = pd.read_sql(text(f"SELECT * FROM {SOURCE_TABLE}"), conn)
    logger.info(f"  {len(df_geo)} rows read from {SOURCE_TABLE}")

    # ── 2. Load reference and aliases ─────────────────────────────────────────
    ref_index, _, canonical_terms = _load_reference(logger)
    alias_index = _load_aliases(logger)

    # ── 3. Normalize each row ─────────────────────────────────────────────────
    logger.info("  Normalizing rows...")
    audit_rows = [
        _normalize_row(row.to_dict(), ref_index, canonical_terms, alias_index)
        for _, row in df_geo.iterrows()
    ]
    df_audit = pd.DataFrame(audit_rows)
    df_audit.insert(0, "audit_id", range(1, len(df_audit) + 1))
    logger.info(f"  {len(df_audit)} audit rows prepared")
    if len(df_audit) != len(df_geo):
        logger.error(
            f"  ROW COUNT MISMATCH: audit={len(df_audit)} vs dim_geo={len(df_geo)} — investigate"
        )
    else:
        logger.info(f"  Row count check: OK ({len(df_audit)} == {len(df_geo)})")

    # ── 4. Write audit table (idempotent) ─────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(text(f"DROP VIEW IF EXISTS dwh.{VIEW_NAME}"))
    n_rows, elapsed = dwh_utils.write_to_dwh(df_audit, engine, AUDIT_TABLE, logger)

    # ── 5. Recreate view ──────────────────────────────────────────────────────
    _create_normalized_view(engine, logger)

    # ── 6. Collect metrics ────────────────────────────────────────────────────
    method_counts  = df_audit["match_method"].value_counts().to_dict()
    quality_counts = df_audit["geo_quality_level"].value_counts().to_dict()
    entity_counts  = df_audit["geo_entity_type"].value_counts().to_dict()
    n_review       = int(df_audit["needs_review"].eq(True).sum())
    avg_score      = df_audit.loc[df_audit["confidence_score"] > 0, "confidence_score"].mean()

    logger.info("=" * 60)
    logger.info(f"  total dim_geo rows read          : {len(df_geo)}")
    logger.info(f"  total audit rows inserted        : {n_rows}")
    logger.info(f"  load duration                    : {elapsed:.1f}s")
    logger.info(f"  fuzzy backend                    : {_FUZZY_BACKEND}")
    logger.info(f"  reference canonical terms        : {len(canonical_terms)}")
    logger.info(f"  aliases loaded                   : {len(alias_index)}")
    logger.info("")
    logger.info("  ── Match method breakdown ──")
    for meth, cnt in sorted(method_counts.items(), key=lambda x: -x[1]):
        logger.info(f"    {meth:<35}: {cnt}")
    logger.info("")
    logger.info("  ── Quality level breakdown ──")
    for ql, cnt in sorted(quality_counts.items(), key=lambda x: -x[1]):
        logger.info(f"    {ql:<35}: {cnt}")
    logger.info("")
    logger.info("  ── Entity type breakdown ──")
    for et, cnt in sorted(entity_counts.items(), key=lambda x: -x[1]):
        logger.info(f"    {et:<35}: {cnt}")
    logger.info("")
    logger.info(f"  rows needing review              : {n_review}")
    logger.info(f"  average confidence (scored rows) : {avg_score:.3f}")

    # ── 7. Top-20 normalized examples ────────────────────────────────────────
    df_show = df_audit[
        df_audit["match_method"].isin(["EXACT_REFERENCE", "ALIAS_MANUEL", "FUZZY_HIGH", "FUZZY_MEDIUM"])
        & (df_audit["localite_normalisee"] != df_audit["localite_source"])
        & (df_audit["localite_normalisee"] != "UNKNOWN")
    ].sort_values("confidence_score", ascending=False).head(20)

    if not df_show.empty:
        logger.info("")
        logger.info("  ── Top-20 normalization examples ──")
        for _, r in df_show.iterrows():
            logger.info(
                f"    [{r['match_method']:<20}] "
                f"{str(r['localite_source']):<25} → {str(r['localite_normalisee']):<25} "
                f"({r['confidence_score']:.2f})"
            )

    # ── 8. Validation SQL ─────────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info("Validation SQL queries:")
    logger.info(f"""
-- total audit rows
SELECT COUNT(*) FROM dwh.{AUDIT_TABLE};

-- quality distribution
SELECT geo_quality_level, COUNT(*) AS nb
FROM dwh.{AUDIT_TABLE}
GROUP BY geo_quality_level
ORDER BY nb DESC;

-- match method distribution
SELECT match_method, COUNT(*) AS nb
FROM dwh.{AUDIT_TABLE}
GROUP BY match_method
ORDER BY nb DESC;

-- entity type distribution
SELECT geo_entity_type, COUNT(*) AS nb
FROM dwh.{AUDIT_TABLE}
GROUP BY geo_entity_type
ORDER BY nb DESC;

-- rows needing review
SELECT COUNT(*) AS needs_review_count
FROM dwh.{AUDIT_TABLE}
WHERE needs_review = true;

-- top ambiguous rows
SELECT
    localite_source, region_source, gouvernorat_source, code_postal_source,
    candidate_1, candidate_1_score, candidate_2, candidate_2_score, match_reason
FROM dwh.{AUDIT_TABLE}
WHERE geo_quality_level = 'AMBIGUOUS'
ORDER BY candidate_1_score DESC NULLS LAST
LIMIT 100;

-- high-confidence fuzzy corrections
SELECT
    localite_source, localite_normalisee, gouvernorat_normalise, region_normalisee,
    confidence_score, match_method, match_reason
FROM dwh.{AUDIT_TABLE}
WHERE match_method = 'FUZZY_HIGH'
ORDER BY confidence_score DESC
LIMIT 100;

-- normalized view spot-check
SELECT geo_sk, pays, gouvernorat, localite, geo_quality_level,
       match_method, confidence_score, needs_review
FROM dwh.{VIEW_NAME}
ORDER BY geo_sk
LIMIT 50;
""")
    logger.info("=" * 60)

    return n_rows


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _run_id  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _logger  = dwh_utils.setup_logging(_run_id, log_name="geo_normalization_engine")
    _engine  = dwh_utils.build_engine(_logger)
    dwh_utils.create_dwh_schema(_engine, _logger)
    _n = run_geo_normalization(_run_id, _engine, _logger)
    _logger.info(f"Done: {_n} rows -> dwh.{AUDIT_TABLE}")
