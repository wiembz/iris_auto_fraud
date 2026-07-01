"""
etl/mart/load_dim_checkpoint.py
================================
Creates and populates mart.dim_checkpoint, the VHS scoring reference table.

Business purpose:
  mart.dim_checkpoint defines HOW each inspection checkpoint is interpreted
  for Vehicle Health Score (VHS) calculation. It is separate from
  dwh.fact_inspection_checkpoint which stores WHAT was observed.

This loader (initial build only):
  - Uses DROP TABLE IF EXISTS mart.dim_checkpoint CASCADE.
  - This is acceptable only during initial construction when no manual
    review history must be preserved. Do NOT repeat this in future
    scoring or review steps.

Workflow:
  1. Create mart schema if it does not exist.
  2. Drop and recreate mart.dim_checkpoint.
  3. Extract distinct checkpoints from dwh.fact_inspection_checkpoint.
  4. Classify each checkpoint into a business tier using explicit per-code rules.
  5. Apply VHS_BALANCED_V1 penalty profile per tier.
  6. Set is_immobilizing conservatively.
  7. Insert all rows into mart.dim_checkpoint.
  8. Write data/quality_reports/vhs/dim_checkpoint_review.csv.
  9. Log validation SQL.

Constraints:
  - Does NOT modify dwh.fact_inspection_checkpoint or dwh.dim_vehicule.
  - Does NOT calculate VHS scores.
  - Does NOT create fact_vhs_score or any review/historization tables.
  - Does NOT use ML, XGBoost, PCA, or agents.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dwh"))
import dwh_utils

BASE_DIR = Path(__file__).resolve().parent.parent.parent
VHS_REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "vhs"
DIM_CHECKPOINT_REPORT_PATH = VHS_REPORT_DIR / "dim_checkpoint_review.csv"

RULE_VERSION = "VHS_BALANCED_V1"
TODAY = datetime.now(timezone.utc).replace(tzinfo=None)

# ---------------------------------------------------------------------------
# Tier penalty profiles — VHS_BALANCED_V1
# ---------------------------------------------------------------------------

_TIER_PROFILES: dict[str, dict] = {
    "T1_VITAL": {
        "penalty_worn": 10.00,
        "penalty_broken": 25.00,
        "is_vital": True,
        "is_important": False,
        "is_critical_functional": False,
    },
    "T1_IMPORTANT": {
        "penalty_worn": 6.00,
        "penalty_broken": 15.00,
        "is_vital": False,
        "is_important": True,
        "is_critical_functional": False,
    },
    "T2_CRITICAL": {
        "penalty_worn": 5.00,
        "penalty_broken": 12.00,
        "is_vital": False,
        "is_important": False,
        "is_critical_functional": True,
    },
    "T2_NORMAL": {
        "penalty_worn": 3.00,
        "penalty_broken": 8.00,
        "is_vital": False,
        "is_important": False,
        "is_critical_functional": False,
    },
    "T3_COSMETIC": {
        "penalty_worn": 1.00,
        "penalty_broken": 4.00,
        "is_vital": False,
        "is_important": False,
        "is_critical_functional": False,
    },
    "UNKNOWN_REVIEW": {
        "penalty_worn": 0.00,
        "penalty_broken": 0.00,
        "is_vital": False,
        "is_important": False,
        "is_critical_functional": False,
    },
}

# ---------------------------------------------------------------------------
# Checkpoint classification — explicit per-code mapping
#
# Each entry: (tier, is_immobilizing, review_status, review_reason)
#
# Tier review_reason text is standardized per tier per spec:
#   T1_VITAL        : 'Direct safety-critical checkpoint. Non-compensable in VHS scoring.'
#   T1_IMPORTANT    : 'Important safety-related checkpoint.'
#   T2_CRITICAL     : 'Critical functional checkpoint.'
#   T2_NORMAL       : 'Functional or visibility-related checkpoint. Not vital but should not be treated as cosmetic.'
#   T3_COSMETIC     : 'Low-criticality comfort, maintenance, or visual checkpoint.'
#   UNKNOWN_REVIEW  : 'Generic, truncated, or composite checkpoint. Excluded from VHS V1 to avoid arbitrary scoring or double counting.'
# ---------------------------------------------------------------------------

_T1_VITAL_REASON     = "Direct safety-critical checkpoint. Non-compensable in VHS scoring."
_T1_IMPORT_REASON    = "Important safety-related checkpoint."
_T2_CRIT_REASON      = "Critical functional checkpoint."
_T2_NORM_REASON      = "Functional or visibility-related checkpoint. Not vital but should not be treated as cosmetic."
_T3_COSM_REASON      = "Low-criticality comfort, maintenance, or visual checkpoint."
_UNKNOWN_REASON      = "Generic, truncated, or composite checkpoint. Excluded from VHS V1 to avoid arbitrary scoring or double counting."

# (tier, is_immobilizing, review_status, review_reason)
_CHECKPOINT_RULES: dict[str, tuple[str, bool, str, str]] = {

    # ── ENTRETIEN ──────────────────────────────────────────────────────────

    "autres_prestations_controle_bougies_d_allumage": (
        "T2_NORMAL", False, "INITIAL_RULE", _T2_NORM_REASON,
    ),
    "autres_prestations_controle_filtre_a_air": (
        "T3_COSMETIC", False, "INITIAL_RULE", _T3_COSM_REASON,
    ),
    "autres_prestations_controle_filtre_d_habitacle": (
        "T3_COSMETIC", False, "INITIAL_RULE", _T3_COSM_REASON,
    ),
    # Timing belt — immobilizing if breaks
    "autres_prestations_courroie_de_disribution": (
        "T2_CRITICAL", True, "INITIAL_RULE", _T2_CRIT_REASON,
    ),
    "autres_prestations_fonctionnement_climatisation": (
        "T3_COSMETIC", False, "INITIAL_RULE", _T3_COSM_REASON,
    ),
    # Generic maintenance entry — too broad; may duplicate atomic checkpoints
    "autres_prestations_operation_d_entretien": (
        "UNKNOWN_REVIEW", False, "NEEDS_MANUAL_REVIEW", _UNKNOWN_REASON,
    ),

    # ── INTERIEUR ──────────────────────────────────────────────────────────

    "dans_le_vehicule_controle_avertisseur_sonore": (
        "T2_NORMAL", False, "INITIAL_RULE", _T2_NORM_REASON,
    ),
    # Truncated libelle — component cannot be identified safely
    "dans_le_vehicule_controle_etat_et_fonctionnement_des_1": (
        "UNKNOWN_REVIEW", False, "NEEDS_MANUAL_REVIEW", _UNKNOWN_REASON,
    ),
    "dans_le_vehicule_controle_etat_et_fonctionnement_des_ba": (
        "UNKNOWN_REVIEW", False, "NEEDS_MANUAL_REVIEW", _UNKNOWN_REASON,
    ),
    "dans_le_vehicule_controle_etat_et_fonctionnement_du_l_1": (
        "UNKNOWN_REVIEW", False, "NEEDS_MANUAL_REVIEW", _UNKNOWN_REASON,
    ),
    "dans_le_vehicule_controle_etat_et_fonctionnement_du_lev": (
        "UNKNOWN_REVIEW", False, "NEEDS_MANUAL_REVIEW", _UNKNOWN_REASON,
    ),
    # Truncated lighting check — type undetermined
    "dans_le_vehicule_controle_fonctionnement_des_feux_de_1": (
        "UNKNOWN_REVIEW", False, "NEEDS_MANUAL_REVIEW", _UNKNOWN_REASON,
    ),
    # Turn signals / hazard lights — functional safety signaling
    "dans_le_vehicule_controle_fonctionnement_des_feux_de_si": (
        "T2_NORMAL", False, "INITIAL_RULE", _T2_NORM_REASON,
    ),
    # Truncated lighting variant — cannot distinguish from atomic checks
    "dans_le_vehicule_controle_fonctionnement_des_feux_ecl_1": (
        "UNKNOWN_REVIEW", False, "NEEDS_MANUAL_REVIEW", _UNKNOWN_REASON,
    ),
    # Interior verification of exterior lighting controls
    "dans_le_vehicule_controle_fonctionnement_des_feux_eclai": (
        "T2_NORMAL", False, "INITIAL_RULE", _T2_NORM_REASON,
    ),

    # ── SOUS_CAPOT ─────────────────────────────────────────────────────────

    # Battery — immobilizing if broken
    "sous_le_capot_controle_batterie_etat_fixation_et_charge": (
        "T2_CRITICAL", True, "INITIAL_RULE", _T2_CRIT_REASON,
    ),
    # Brake fluid — T1_VITAL (direct braking safety; non-compensable)
    "sous_le_capot_controle_du_niveau_du_liquide_de_frein": (
        "T1_VITAL", False, "INITIAL_RULE", _T1_VITAL_REASON,
    ),
    # Coolant — immobilizing if engine overheats
    "sous_le_capot_controle_du_niveau_du_liquide_de_refroidi": (
        "T2_CRITICAL", True, "INITIAL_RULE", _T2_CRIT_REASON,
    ),
    # Engine oil — immobilizing if seized
    "sous_le_capot_controle_du_niveau_huile_moteur": (
        "T2_CRITICAL", True, "INITIAL_RULE", _T2_CRIT_REASON,
    ),
    # Radiator hoses — functional leak risk, not immediately immobilizing
    "sous_le_capot_controle_durits_de_radiateur": (
        "T2_NORMAL", False, "INITIAL_RULE", _T2_NORM_REASON,
    ),
    # Accessory belts (alternator/power steering) — immobilizing if broken
    "sous_le_capot_controle_etat_des_courroies_d_accessoires": (
        "T2_CRITICAL", True, "INITIAL_RULE", _T2_CRIT_REASON,
    ),

    # ── SOUS_VEHICULE ──────────────────────────────────────────────────────

    "sous_le_vehicule_controle_des_plaquettes_de_freins_ar_s": (
        "T1_VITAL", False, "INITIAL_RULE", _T1_VITAL_REASON,
    ),
    "sous_le_vehicule_controle_des_plaquettes_de_freins_av": (
        "T1_VITAL", False, "INITIAL_RULE", _T1_VITAL_REASON,
    ),
    "sous_le_vehicule_controle_disques_ar_selon_equipement": (
        "T1_VITAL", False, "INITIAL_RULE", _T1_VITAL_REASON,
    ),
    "sous_le_vehicule_controle_disques_av": (
        "T1_VITAL", False, "INITIAL_RULE", _T1_VITAL_REASON,
    ),
    # Shock absorber seals — handling and road holding
    "sous_le_vehicule_controle_etancheite_des_amortisseurs_1": (
        "T1_IMPORTANT", False, "INITIAL_RULE", _T1_IMPORT_REASON,
    ),
    "sous_le_vehicule_controle_etancheite_des_amortisseurs_a": (
        "T1_IMPORTANT", False, "INITIAL_RULE", _T1_IMPORT_REASON,
    ),
    # All fluid seals — major leak can cause brake/oil/coolant failure
    "sous_le_vehicule_controle_etancheite_tous_fluides": (
        "T2_CRITICAL", True, "INITIAL_RULE", _T2_CRIT_REASON,
    ),
    # Truncated generic "detailed check" — scope unclear
    "sous_le_vehicule_controle_etat_approfondi_et_mise_a_p_1": (
        "UNKNOWN_REVIEW", False, "NEEDS_MANUAL_REVIEW", _UNKNOWN_REASON,
    ),
    "sous_le_vehicule_controle_etat_approfondi_et_mise_a_pre": (
        "UNKNOWN_REVIEW", False, "NEEDS_MANUAL_REVIEW", _UNKNOWN_REASON,
    ),
    # Underbody corrosion — structural integrity; not immediately immobilizing
    "sous_le_vehicule_controle_etat_sous_caisse_corrosion_ca": (
        "T2_CRITICAL", False, "INITIAL_RULE", _T2_CRIT_REASON,
    ),
    # Brake calipers — direct braking safety
    "sous_le_vehicule_controle_etriers": (
        "T1_VITAL", False, "INITIAL_RULE", _T1_VITAL_REASON,
    ),
    # Transmission joints and ball joints — loss of control risk
    "sous_le_vehicule_controle_gaine_transmissions_rotules_c": (
        "T1_VITAL", False, "INITIAL_RULE", _T1_VITAL_REASON,
    ),
    # Exhaust line — CO risk if cabin leak; structural; not immediately immobilizing
    "sous_le_vehicule_controle_ligne_d_echappement_et_fixati": (
        "T2_CRITICAL", False, "INITIAL_RULE", _T2_CRIT_REASON,
    ),

    # ── TOUR_DU_VEHICULE ───────────────────────────────────────────────────

    # Wipers — visibility/usability, not purely cosmetic
    "tour_du_vehicule_balais_essuie_glace": (
        "T2_NORMAL", False, "INITIAL_RULE", _T2_NORM_REASON,
    ),
    # Rear lighting — visibility for other drivers
    "tour_du_vehicule_eclairage_arriere": (
        "T2_NORMAL", False, "INITIAL_RULE", _T2_NORM_REASON,
    ),
    # Front headlights — night driving safety; critical functional
    "tour_du_vehicule_eclairage_avant": (
        "T2_CRITICAL", False, "INITIAL_RULE", _T2_CRIT_REASON,
    ),
    # License plates — legal compliance, not mechanical safety
    "tour_du_vehicule_plaques_de_police": (
        "T3_COSMETIC", False, "INITIAL_RULE", _T3_COSM_REASON,
    ),
    "tour_du_vehicule_pneus_arriere": (
        "T1_IMPORTANT", False, "INITIAL_RULE", _T1_IMPORT_REASON,
    ),
    "tour_du_vehicule_pneus_avant": (
        "T1_IMPORTANT", False, "INITIAL_RULE", _T1_IMPORT_REASON,
    ),
    # Mirrors — visibility-related, not purely cosmetic
    "tour_du_vehicule_retroviseur_droit": (
        "T2_NORMAL", False, "INITIAL_RULE", _T2_NORM_REASON,
    ),
    "tour_du_vehicule_retroviseur_gauche": (
        "T2_NORMAL", False, "INITIAL_RULE", _T2_NORM_REASON,
    ),
    # Windshield — visibility-related, not purely cosmetic
    "tour_du_vehicule_vitres_et_pare_brise": (
        "T2_NORMAL", False, "INITIAL_RULE", _T2_NORM_REASON,
    ),
}


def _classify(code: str) -> tuple[str, bool, str, str]:
    """Return (tier, is_immobilizing, review_status, review_reason) for a code."""
    if code in _CHECKPOINT_RULES:
        return _CHECKPOINT_RULES[code]
    return ("UNKNOWN_REVIEW", False, "NEEDS_MANUAL_REVIEW",
            "Code not in classification table — auto-fallback to UNKNOWN_REVIEW")


def _build_row(code: str, libelle: str, zone: str) -> dict:
    tier, is_immobilizing, review_status, review_reason = _classify(code)
    profile = _TIER_PROFILES[tier]
    is_scored = tier != "UNKNOWN_REVIEW"

    return {
        "checkpoint_code":        code,
        "checkpoint_libelle":     libelle,
        "zone_controle":          zone,
        "tier":                   tier,
        "is_vhs_scored":          is_scored,
        "is_vital":               profile["is_vital"],
        "is_important":           profile["is_important"],
        "is_critical_functional": profile["is_critical_functional"],
        "is_immobilizing":        is_immobilizing,
        "penalty_worn":           profile["penalty_worn"],
        "penalty_broken":         profile["penalty_broken"],
        "rule_version":           RULE_VERSION,
        "is_active":              True,
        "valid_from":             TODAY,
        "valid_to":               None,
        "review_status":          review_status,
        "review_reason":          review_reason,
        "created_at":             TODAY,
    }


DDL_CREATE_SCHEMA = "CREATE SCHEMA IF NOT EXISTS mart;"

DDL_CREATE_TABLE = """
DROP TABLE IF EXISTS mart.dim_checkpoint CASCADE;

CREATE TABLE mart.dim_checkpoint (
    checkpoint_sk          BIGSERIAL    PRIMARY KEY,
    checkpoint_code        TEXT         NOT NULL UNIQUE,
    checkpoint_libelle     TEXT,
    zone_controle          TEXT,
    tier                   TEXT         NOT NULL,
    is_vhs_scored          BOOLEAN      NOT NULL DEFAULT TRUE,
    is_vital               BOOLEAN      NOT NULL DEFAULT FALSE,
    is_important           BOOLEAN      NOT NULL DEFAULT FALSE,
    is_critical_functional BOOLEAN      NOT NULL DEFAULT FALSE,
    is_immobilizing        BOOLEAN      NOT NULL DEFAULT FALSE,
    penalty_worn           NUMERIC(6,2) NOT NULL DEFAULT 0,
    penalty_broken         NUMERIC(6,2) NOT NULL DEFAULT 0,
    rule_version           TEXT         NOT NULL DEFAULT 'VHS_BALANCED_V1',
    is_active              BOOLEAN      NOT NULL DEFAULT TRUE,
    valid_from             TIMESTAMP    DEFAULT NOW(),
    valid_to               TIMESTAMP,
    review_status          TEXT         DEFAULT 'INITIAL_RULE',
    review_reason          TEXT,
    created_at             TIMESTAMP    DEFAULT NOW()
);
"""

VALIDATION_SQL = """
SELECT COUNT(*) FROM mart.dim_checkpoint;

SELECT tier, COUNT(*)
FROM mart.dim_checkpoint
GROUP BY tier
ORDER BY tier;

SELECT is_vhs_scored, COUNT(*)
FROM mart.dim_checkpoint
GROUP BY is_vhs_scored;

SELECT is_immobilizing, COUNT(*)
FROM mart.dim_checkpoint
GROUP BY is_immobilizing;

SELECT checkpoint_code, checkpoint_libelle, zone_controle, tier,
       penalty_worn, penalty_broken, is_vhs_scored, review_reason
FROM mart.dim_checkpoint
ORDER BY tier, zone_controle, checkpoint_code;

SELECT checkpoint_code, checkpoint_libelle, zone_controle, review_reason
FROM mart.dim_checkpoint
WHERE tier = 'UNKNOWN_REVIEW'
ORDER BY zone_controle, checkpoint_code;
"""

# Columns written to the DB (no internal helpers)
_DB_COLS = [
    "checkpoint_code", "checkpoint_libelle", "zone_controle",
    "tier", "is_vhs_scored", "is_vital", "is_important",
    "is_critical_functional", "is_immobilizing",
    "penalty_worn", "penalty_broken", "rule_version",
    "is_active", "valid_from", "valid_to",
    "review_status", "review_reason", "created_at",
]

# Columns written to the quality report CSV
_REPORT_COLS = [
    "checkpoint_code", "checkpoint_libelle", "zone_controle",
    "tier", "penalty_worn", "penalty_broken",
    "is_vhs_scored", "is_vital", "is_important",
    "is_critical_functional", "is_immobilizing",
    "review_status", "review_reason",
]


def load_dim_checkpoint():
    logger = dwh_utils.setup_logging("load_dim_checkpoint")
    logger.info("=" * 60)
    logger.info("[RUN] dwh.fact_inspection_checkpoint -> mart.dim_checkpoint")
    logger.info("=" * 60)

    engine = dwh_utils.build_engine(logger)

    # ------------------------------------------------------------------
    # 1. Fetch distinct checkpoints from source
    # ------------------------------------------------------------------
    with engine.connect() as conn:
        df_src = pd.read_sql(
            text("""
                SELECT DISTINCT
                    checkpoint_code,
                    checkpoint_libelle,
                    zone_controle
                FROM dwh.fact_inspection_checkpoint
                ORDER BY zone_controle, checkpoint_code
            """),
            conn,
        )
    logger.info(f"  distinct checkpoints from dwh.fact_inspection_checkpoint: {len(df_src)}")

    # ------------------------------------------------------------------
    # 2. Classify and build rows
    # ------------------------------------------------------------------
    rows = [
        _build_row(r["checkpoint_code"], r["checkpoint_libelle"], r["zone_controle"])
        for _, r in df_src.iterrows()
    ]
    df = pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # 3. DDL: create schema and table
    # ------------------------------------------------------------------
    with engine.begin() as conn:
        conn.execute(text(DDL_CREATE_SCHEMA))
        logger.info("  schema mart: OK")
        conn.execute(text(DDL_CREATE_TABLE))
        logger.info("  mart.dim_checkpoint: dropped and recreated (initial build only)")

    # ------------------------------------------------------------------
    # 4. Insert
    # ------------------------------------------------------------------
    with engine.begin() as conn:
        df[_DB_COLS].to_sql(
            "dim_checkpoint",
            conn,
            schema="mart",
            if_exists="append",
            index=False,
            chunksize=500,
            method="multi",
        )
    logger.info(f"  inserted: {len(df)} rows -> mart.dim_checkpoint")

    # ------------------------------------------------------------------
    # 5. Quality report CSV
    # ------------------------------------------------------------------
    VHS_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    df[_REPORT_COLS].to_csv(DIM_CHECKPOINT_REPORT_PATH, index=False, encoding="utf-8-sig")
    logger.info(f"  quality report: {DIM_CHECKPOINT_REPORT_PATH}")

    # ------------------------------------------------------------------
    # 6. Tier / flag summary
    # ------------------------------------------------------------------
    tier_counts    = df["tier"].value_counts().sort_index().to_dict()
    scored         = int(df["is_vhs_scored"].sum())
    unscored       = int((~df["is_vhs_scored"]).sum())
    immobilizing   = int(df["is_immobilizing"].sum())
    needs_review   = int((df["review_status"] == "NEEDS_MANUAL_REVIEW").sum())

    logger.info("=" * 60)
    logger.info(f"  total checkpoints loaded : {len(df)}")
    for tier in ["T1_VITAL", "T1_IMPORTANT", "T2_CRITICAL", "T2_NORMAL", "T3_COSMETIC", "UNKNOWN_REVIEW"]:
        logger.info(f"    {tier:<20}: {tier_counts.get(tier, 0)}")
    logger.info(f"  is_vhs_scored = TRUE     : {scored}")
    logger.info(f"  is_vhs_scored = FALSE    : {unscored}  (UNKNOWN_REVIEW)")
    logger.info(f"  is_immobilizing = TRUE   : {immobilizing}")
    logger.info(f"  needs manual review      : {needs_review}")
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # 7. Validation SQL
    # ------------------------------------------------------------------
    logger.info("Validation SQL queries:")
    logger.info(VALIDATION_SQL)

    # ------------------------------------------------------------------
    # 8. Print summary
    # ------------------------------------------------------------------
    print("=" * 60)
    print(f"  mart.dim_checkpoint loaded : {len(df)} rows")
    print()
    print("  Tier distribution:")
    for tier in ["T1_VITAL", "T1_IMPORTANT", "T2_CRITICAL", "T2_NORMAL", "T3_COSMETIC", "UNKNOWN_REVIEW"]:
        n = tier_counts.get(tier, 0)
        tag = "  [not scored]" if tier == "UNKNOWN_REVIEW" else ""
        print(f"    {tier:<20}: {n}{tag}")
    print()
    print(f"  is_vhs_scored = TRUE   : {scored}")
    print(f"  is_vhs_scored = FALSE  : {unscored}  (UNKNOWN_REVIEW)")
    print(f"  is_immobilizing = TRUE : {immobilizing}")
    print(f"  needs manual review    : {needs_review}")
    print(f"  rule version           : {RULE_VERSION}")
    print(f"  report                 : {DIM_CHECKPOINT_REPORT_PATH.name}")
    print("=" * 60)

    logger.info(f"Done: {len(df)} rows -> mart.dim_checkpoint")
    return df


if __name__ == "__main__":
    load_dim_checkpoint()
