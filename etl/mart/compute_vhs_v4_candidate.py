"""
etl/mart/compute_vhs_v4_candidate.py
=====================================
Computes the Vehicle Health Score V4 candidate (VHS_BALANCED_V4_CANDIDATE).

Changes from V3:
  - Systeme de penalite base sur des SYSTEMES FONCTIONNELS (freinage, suspension,
    transmission, moteur, carrosserie, etc.) pour eviter les doubles comptages.
  - Chaque systeme est evalue une seule fois : la somme des penalites brutes
    des checkpoints d'un meme systeme est plafonnee par le cap du systeme.
  - WORN_STRONG utilise `penalty_worn x 0.6` au lieu du midpoint (worn+broken)/2,
    ce qui evite de sur-penaliser les "Intervention conseillee" sur organes vitaux.
  - Score plancher = 5 si le vehicule est encore roulable (is_drivable=True).
  - Penalite kilometrage inchangee.
  - Grade de securite et decision metier inchanges par rapport a V3.
  - Rapport de comparaison V3 vs V4 inclus.

Philosophie du score:
  0 = vehicule inutilisable / hors etat de rouler
  20-40 = vehicule use, exploitable sous reserve de reparations importantes
  70-85 = vehicule en bon etat general
  90+ = vehicule en excellent etat

V1, V2 et V3 results are NEVER modified.

Sources:
  dwh.fact_inspection_vehicule   - one row per inspection
  dwh.fact_inspection_checkpoint - observed checkpoint values
  mart.dim_checkpoint            - scoring reference (criticality, penalties)

Outputs (appended to existing tables):
  mart.fact_vhs_score
  mart.fact_vhs_penalty_detail
  data/quality_reports/vhs/vhs_balanced_v4_candidate/
    vhs_v4_distribution_by_decision.csv
    vhs_v4_distribution_by_grade.csv
    vhs_v4_observed_status_distribution.csv
    vhs_v4_penalty_by_system.csv
    vhs_v4_penalty_by_tier.csv
    vhs_v4_ambiguous_values_mapping.csv
    vhs_v3_vs_v4_comparison.csv
    vhs_v4_audit_summary.md
"""
from __future__ import annotations

import math
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dwh"))
import dwh_utils

BASE_DIR   = Path(__file__).resolve().parent.parent.parent
REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "vhs" / "vhs_balanced_v4_candidate"

PROFILE_NAME = "VHS_BALANCED_V4_CANDIDATE"
RULE_VERSION  = "VHS_BALANCED_V4_CANDIDATE"
TODAY         = datetime.now(timezone.utc).replace(tzinfo=None)

V3_RUN_ID = "VHS_BALANCED_V3_CANDIDATE_20260703_181530"

# -- Lookup sets (lowercase, accent-stripped) ----------------------------------
_REPAIR_PHRASES = frozenset([
    "reparation effectuee suite a l'accord client",
    "reparation effectuee suite a l\u2019accord client",
])

_BROKEN_VALUES       = frozenset(["defectueux", "controle non ok"])
_INTERVENTION_VALUES = frozenset(["intervention conseillee"])
_PROPOSITION_VALUES  = frozenset(["proposition faite"])
_NON_VALUES          = frozenset(["non"])
_OK_VALUES           = frozenset(["bon", "controle ok", "oui"])
_STATE_VALUES        = {"OK": 1.0, "WORN": 0.5, "WORN_STRONG": 0.25, "BROKEN": 0.0}

_DIM_COLS = [
    "checkpoint_code",
    "checkpoint_libelle",
    "zone_controle",
    "tier",
    "is_vital",
    "is_important",
    "is_critical_functional",
    "is_immobilizing",
    "is_vhs_scored",
    "penalty_worn",
    "penalty_broken",
]

# -- Regroupement des checkpoints par SYSTEME FONCTIONNEL ----------------------
# Format: { substring_dans_checkpoint_code : nom_systeme }
SYSTEM_MAP: dict[str, str] = {
    # Freinage
    "plaquettes_de_freins": "SYS_FREINAGE",
    "disques":              "SYS_FREINAGE",
    "etriers":              "SYS_FREINAGE",
    "liquide_de_frein":     "SYS_FREINAGE",
    # Suspension & direction
    "amortisseur":          "SYS_SUSPENSION",
    "rotule":               "SYS_SUSPENSION",
    "silent_bloc":          "SYS_SUSPENSION",
    "lame":                 "SYS_SUSPENSION",
    "direction":            "SYS_SUSPENSION",
    "cremaillere":          "SYS_SUSPENSION",
    # Transmission
    "transmission":         "SYS_TRANSMISSION",
    "gaine_transmission":   "SYS_TRANSMISSION",
    "gaine_transmissions":  "SYS_TRANSMISSION",
    # Moteur & fluides
    "huile_moteur":              "SYS_MOTEUR",
    "niveau_huile":              "SYS_MOTEUR",
    "courroie_de_distribution":  "SYS_MOTEUR",
    "courroie_distribution":     "SYS_MOTEUR",
    "radiateur":                 "SYS_MOTEUR",
    "refroidissement":           "SYS_MOTEUR",
    "durits":                    "SYS_MOTEUR",
    "courroie_accessoire":       "SYS_MOTEUR",
    "courroie_d_accessoire":     "SYS_MOTEUR",
    # Pneus (AV/AR separes pour garder la progressivite)
    "pneus_avant":  "SYS_PNEUS_AV",
    "pneus_arriere":"SYS_PNEUS_AR",
    "pneu_avant":   "SYS_PNEUS_AV",
    "pneu_arriere": "SYS_PNEUS_AR",
    # Carrosserie & structure
    "sous_caisse":  "SYS_STRUCTURE",
    "corrosion":    "SYS_STRUCTURE",
    "chassis":      "SYS_STRUCTURE",
    # Echappement
    "echappement":       "SYS_ECHAPPEMENT",
    "ligne_d_echappement":"SYS_ECHAPPEMENT",
    # Eclairage
    "eclairage_avant":  "SYS_ECLAIRAGE",
    "eclairage_arriere":"SYS_ECLAIRAGE",
    "feux_de_si":       "SYS_ECLAIRAGE",
    "feux_eclai":       "SYS_ECLAIRAGE",
    "feux_positi":      "SYS_ECLAIRAGE",
    "batterie":         "SYS_ELECTRIQUE",
}

# Plafonds de penalite par systeme (en points, sur 100)
SYSTEM_CAP: dict[str, float] = {
    "SYS_FREINAGE":     20.0,
    "SYS_SUSPENSION":   15.0,
    "SYS_TRANSMISSION": 15.0,
    "SYS_MOTEUR":       18.0,
    "SYS_PNEUS_AV":      8.0,
    "SYS_PNEUS_AR":      8.0,
    "SYS_STRUCTURE":    12.0,
    "SYS_ECHAPPEMENT":   8.0,
    "SYS_ECLAIRAGE":     6.0,
    "SYS_ELECTRIQUE":    4.0,
}

# Score plancher: un vehicule roulable ne peut jamais avoir 0/100
SCORE_FLOOR_DRIVABLE = 5.0


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

DDL_CREATE_SCHEMA = "CREATE SCHEMA IF NOT EXISTS mart;"

DDL_FACT_VHS_SCORE = """
CREATE TABLE IF NOT EXISTS mart.fact_vhs_score (
    vhs_score_sk           BIGSERIAL PRIMARY KEY,
    inspection_key         TEXT             NOT NULL,
    vehicule_sk            BIGINT,
    date_inspection_sk     BIGINT,
    immatriculation_norm   TEXT,
    kilometrage            DOUBLE PRECISION,
    vhs_raw_score          NUMERIC(6,2),
    kilometrage_penalty    NUMERIC(6,2),
    vhs_before_cap         NUMERIC(6,2),
    vhs_final_score        NUMERIC(6,2),
    safety_score           NUMERIC(6,2),
    functional_score       NUMERIC(6,2),
    cosmetic_score         NUMERIC(6,2),
    safety_grade           TEXT,
    decision               TEXT,
    is_drivable            BOOLEAN,
    hard_cap_applied       BOOLEAN,
    hard_cap_type          TEXT,
    nb_penalties_applied   INTEGER,
    nb_anomalies_total     BIGINT,
    nb_anomalies_critiques BIGINT,
    profile_name           TEXT             NOT NULL,
    rule_version           TEXT             NOT NULL,
    run_id                 TEXT             NOT NULL,
    calculated_at          TIMESTAMP        DEFAULT NOW(),
    source_system          TEXT             DEFAULT 'IRIS_VHS',
    created_at             TIMESTAMP        DEFAULT NOW(),
    CONSTRAINT uq_vhs_score UNIQUE (inspection_key, profile_name, rule_version, run_id)
);
"""

DDL_V4_SCORE_COLS = [
    "ALTER TABLE mart.fact_vhs_score ADD COLUMN IF NOT EXISTS nb_checkpoints_scored INTEGER;",
    "ALTER TABLE mart.fact_vhs_score ADD COLUMN IF NOT EXISTS nb_ok INTEGER;",
    "ALTER TABLE mart.fact_vhs_score ADD COLUMN IF NOT EXISTS nb_worn INTEGER;",
    "ALTER TABLE mart.fact_vhs_score ADD COLUMN IF NOT EXISTS nb_worn_strong INTEGER;",
    "ALTER TABLE mart.fact_vhs_score ADD COLUMN IF NOT EXISTS nb_broken INTEGER;",
    "ALTER TABLE mart.fact_vhs_score ADD COLUMN IF NOT EXISTS nb_unknown INTEGER;",
    "ALTER TABLE mart.fact_vhs_score ADD COLUMN IF NOT EXISTS nb_repaired INTEGER;",
    "ALTER TABLE mart.fact_vhs_score ADD COLUMN IF NOT EXISTS has_critical_functional BOOLEAN;",
    "ALTER TABLE mart.fact_vhs_score ADD COLUMN IF NOT EXISTS cap_value NUMERIC(6,2);",
    "ALTER TABLE mart.fact_vhs_score ADD COLUMN IF NOT EXISTS nb_systems_penalized INTEGER;",
    "ALTER TABLE mart.fact_vhs_score ADD COLUMN IF NOT EXISTS penalty_raw_before_cap NUMERIC(6,2);",
    "ALTER TABLE mart.fact_vhs_score ADD COLUMN IF NOT EXISTS penalty_after_system_cap NUMERIC(6,2);",
]

DDL_FACT_VHS_PENALTY_DETAIL = """
CREATE TABLE IF NOT EXISTS mart.fact_vhs_penalty_detail (
    penalty_detail_sk      BIGSERIAL PRIMARY KEY,
    inspection_key         TEXT             NOT NULL,
    vehicule_sk            BIGINT,
    date_inspection_sk     BIGINT,
    immatriculation_norm   TEXT,
    checkpoint_code        TEXT             NOT NULL,
    checkpoint_libelle     TEXT,
    zone_controle          TEXT,
    observed_value         TEXT,
    observed_status        TEXT,
    penalty_applied        NUMERIC(6,2)     NOT NULL DEFAULT 0,
    penalty_reason         TEXT,
    tier                   TEXT,
    is_vital               BOOLEAN,
    is_important           BOOLEAN,
    is_critical_functional BOOLEAN,
    is_immobilizing        BOOLEAN,
    is_hard_cap_trigger    BOOLEAN          DEFAULT FALSE,
    hard_cap_type          TEXT,
    profile_name           TEXT             NOT NULL,
    rule_version           TEXT             NOT NULL,
    run_id                 TEXT             NOT NULL,
    created_at             TIMESTAMP        DEFAULT NOW(),
    CONSTRAINT uq_penalty_detail UNIQUE (inspection_key, checkpoint_code, profile_name, rule_version, run_id)
);
"""

DDL_V4_PENALTY_COLS = [
    "ALTER TABLE mart.fact_vhs_penalty_detail ADD COLUMN IF NOT EXISTS valeur_controle TEXT;",
    "ALTER TABLE mart.fact_vhs_penalty_detail ADD COLUMN IF NOT EXISTS est_anomalie BOOLEAN;",
    "ALTER TABLE mart.fact_vhs_penalty_detail ADD COLUMN IF NOT EXISTS est_anomalie_critique BOOLEAN;",
    "ALTER TABLE mart.fact_vhs_penalty_detail ADD COLUMN IF NOT EXISTS penalty_worn NUMERIC(6,2);",
    "ALTER TABLE mart.fact_vhs_penalty_detail ADD COLUMN IF NOT EXISTS penalty_broken NUMERIC(6,2);",
    "ALTER TABLE mart.fact_vhs_penalty_detail ADD COLUMN IF NOT EXISTS systeme_fonctionnel TEXT;",
    "ALTER TABLE mart.fact_vhs_penalty_detail ADD COLUMN IF NOT EXISTS penalty_raw_checkpoint NUMERIC(6,2);",
    "ALTER TABLE mart.fact_vhs_penalty_detail ADD COLUMN IF NOT EXISTS penalty_capped_by_system BOOLEAN;",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_accents(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _norm_val(raw) -> str:
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return ""
    return _strip_accents(" ".join(str(raw).strip().split()).lower())


def _get_system(checkpoint_code: str) -> str:
    code_lower = checkpoint_code.lower()
    for substring, system in SYSTEM_MAP.items():
        if substring in code_lower:
            return system
    return "SYS_INDEPENDANT"


# ---------------------------------------------------------------------------
# normalize_observed_status -- identique V3 (10 regles de priorite)
# ---------------------------------------------------------------------------

def normalize_observed_status(row) -> str:
    renseigne = bool(row.get("est_controle_renseigne", True))
    anomalie  = bool(row.get("est_anomalie", False))
    critique  = bool(row.get("est_anomalie_critique", False))
    val       = _norm_val(row.get("valeur_controle"))

    if not renseigne:       return "UNKNOWN"
    if not val:             return "UNKNOWN"
    if any(phrase in val for phrase in _REPAIR_PHRASES): return "REPAIRED"
    if val == "defectueux": return "BROKEN"
    if val == "controle non ok": return "BROKEN"

    if val in _INTERVENTION_VALUES:
        if critique: return "WORN_STRONG"
        if anomalie: return "WORN"
        return "UNKNOWN"

    if val in _PROPOSITION_VALUES:
        if critique: return "WORN_STRONG"
        if anomalie: return "WORN"
        return "UNKNOWN"

    if val in _NON_VALUES:
        if critique: return "WORN_STRONG"
        if anomalie: return "WORN"
        return "UNKNOWN"

    if val in _OK_VALUES:
        if not anomalie and not critique: return "OK"
        if critique: return "WORN_STRONG"
        if anomalie: return "WORN"
        return "OK"

    if critique: return "WORN_STRONG"
    if anomalie: return "WORN"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Penalite checkpoint V4
# WORN_STRONG = penalty_worn x 0.6  (au lieu de (worn+broken)/2 en V3)
# ---------------------------------------------------------------------------

def _compute_checkpoint_penalty_v4(status: str, pw: float, pb: float) -> float:
    if status == "WORN":        return round(pw, 2)
    if status == "WORN_STRONG": return round(pw * 0.6, 2)
    if status == "BROKEN":      return round(pb, 2)
    return 0.0


_PENALTY_REASON_V4 = {
    "OK":          "OK_NO_PENALTY",
    "UNKNOWN":     "UNKNOWN_NO_PENALTY",
    "REPAIRED":    "REPAIRED_NO_PENALTY",
    "WORN":        "WORN_PENALTY",
    "WORN_STRONG": "WORN_STRONG_60PCT_WORN_PENALTY",
    "BROKEN":      "BROKEN_CONFIRMED_DEFECT_PENALTY",
}


# ---------------------------------------------------------------------------
# Penalite kilometrage -- identique V3
# ---------------------------------------------------------------------------

def _km_penalty(km) -> float:
    if km is None or (isinstance(km, float) and math.isnan(km)) or km <= 0:
        return 1.0
    km = float(km)
    if km >= 350_000: return 6.0
    if km >= 250_000: return 4.0
    if km >= 180_000: return 2.5
    if km >= 120_000: return 1.0
    return 0.0


# ---------------------------------------------------------------------------
# Grade securite & decision -- identiques V3
# ---------------------------------------------------------------------------

def _compute_grade(vital_broken, vital_worn_strong, important_broken, t1_worn, t1_worn_strong) -> str:
    if vital_broken >= 1 or important_broken >= 3:                            return "D"
    if vital_worn_strong >= 1 or important_broken >= 1 or (t1_worn + t1_worn_strong) >= 4: return "C"
    if t1_worn >= 1 or t1_worn_strong >= 1:                                   return "B"
    return "A"


def _compute_decision(grade: str, drivable: bool, has_cf: bool, vhs_bc: float) -> str:
    if grade == "D":                               return "CRITIQUE"
    if not drivable:                               return "IMMOBILISE"
    if grade == "C" or has_cf or vhs_bc < 70.0:   return "DEGRADE"
    return "OK"


def _compute_cap(grade: str, drivable: bool, has_cf: bool) -> tuple[Optional[float], Optional[str]]:
    if grade == "D":   return 40.0, "GRADE_D"
    if not drivable:   return 50.0, "IMMOBILIZED"
    if grade == "C":   return 65.0, "GRADE_C"
    if has_cf:         return 65.0, "CRITICAL_FUNCTIONAL"
    return None, None


# ---------------------------------------------------------------------------
# Core processing -- V4
# ---------------------------------------------------------------------------

def _process_all_v4(
    df_veh: pd.DataFrame,
    df_cp_raw: pd.DataFrame,
    df_dim: pd.DataFrame,
    run_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:

    # Merge dim into checkpoints
    df_cp = df_cp_raw.merge(
        df_dim[[c for c in _DIM_COLS if c in df_dim.columns]],
        on="checkpoint_code", how="inner",
    )
    df_cp["penalty_worn"]   = df_cp["penalty_worn"].astype(float)
    df_cp["penalty_broken"] = df_cp["penalty_broken"].astype(float)

    for col in ("est_controle_renseigne", "est_anomalie", "est_anomalie_critique",
                "is_vital", "is_important", "is_critical_functional",
                "is_immobilizing", "is_vhs_scored"):
        if col in df_cp.columns:
            df_cp[col] = df_cp[col].fillna(False).astype(bool)

    # V4 observed_status (identique V3)
    df_cp["observed_status"] = df_cp.apply(normalize_observed_status, axis=1)

    # Systeme fonctionnel
    df_cp["systeme_fonctionnel"] = df_cp["checkpoint_code"].map(_get_system)

    # Penalite brute par checkpoint (V4: WORN_STRONG = worn x 0.6)
    is_scored = (
        df_cp["is_vhs_scored"].astype(bool)
        if "is_vhs_scored" in df_cp.columns
        else pd.Series(True, index=df_cp.index)
    )
    pw = df_cp["penalty_worn"]
    pb = df_cp["penalty_broken"]
    st = df_cp["observed_status"]

    df_cp["penalty_raw_checkpoint"] = np.where(
        ~is_scored, 0.0,
        pd.Series(
            [_compute_checkpoint_penalty_v4(s, w, b) for s, w, b in zip(st, pw, pb)],
            index=df_cp.index,
        ),
    )

    df_cp["penalty_reason"] = np.where(
        ~is_scored,
        "NON_SCORED_CHECKPOINT",
        st.map(_PENALTY_REASON_V4).fillna("UNKNOWN_NO_PENALTY"),
    )

    # Regroupement par systeme: somme plafonnee par systeme
    sys_agg = (
        df_cp[df_cp["penalty_raw_checkpoint"] > 0]
        .groupby(["inspection_key", "systeme_fonctionnel"])["penalty_raw_checkpoint"]
        .sum()
        .reset_index()
        .rename(columns={"penalty_raw_checkpoint": "sys_raw_total"})
    )
    sys_agg["sys_cap"] = sys_agg["systeme_fonctionnel"].map(
        lambda s: SYSTEM_CAP.get(s, float("inf"))
    )
    sys_agg["sys_effective_total"] = sys_agg[["sys_raw_total", "sys_cap"]].min(axis=1)
    sys_agg["sys_capped"] = sys_agg["sys_effective_total"] < sys_agg["sys_raw_total"]
    sys_agg["sys_ratio"] = np.where(
        sys_agg["sys_raw_total"] > 0,
        sys_agg["sys_effective_total"] / sys_agg["sys_raw_total"],
        1.0,
    )

    df_cp = df_cp.merge(
        sys_agg[["inspection_key", "systeme_fonctionnel", "sys_ratio", "sys_capped"]],
        on=["inspection_key", "systeme_fonctionnel"],
        how="left",
    )
    df_cp["sys_ratio"]  = df_cp["sys_ratio"].fillna(1.0)
    df_cp["sys_capped"] = df_cp["sys_capped"].fillna(False)

    # Penalite effective apres ratio systeme
    df_cp["penalty_applied"] = (df_cp["penalty_raw_checkpoint"] * df_cp["sys_ratio"]).round(2)
    df_cp["penalty_capped_by_system"] = df_cp["sys_capped"] & (df_cp["penalty_raw_checkpoint"] > 0)

    # state_value pour les subscores
    df_cp["state_value"] = st.map(_STATE_VALUES)

    all_keys = df_veh["inspection_key"].values

    # Agregations
    total_pen = (
        df_cp.groupby("inspection_key")["penalty_applied"].sum()
        .reindex(all_keys, fill_value=0.0)
    )
    total_pen_raw = (
        df_cp.groupby("inspection_key")["penalty_raw_checkpoint"].sum()
        .reindex(all_keys, fill_value=0.0)
    )

    df_t1 = df_cp[df_cp["tier"].isin(["T1_VITAL", "T1_IMPORTANT"])]
    df_t2 = df_cp[df_cp["tier"].isin(["T2_CRITICAL", "T2_NORMAL"])]
    df_t3 = df_cp[df_cp["tier"] == "T3_COSMETIC"]

    safety_agg     = df_t1.groupby("inspection_key")["state_value"].mean() * 100
    functional_agg = df_t2.groupby("inspection_key")["state_value"].mean() * 100
    cosmetic_agg   = df_t3.groupby("inspection_key")["state_value"].mean() * 100

    def _count(mask):
        return df_cp[mask].groupby("inspection_key").size().reindex(all_keys, fill_value=0)

    t1_vital_broken      = _count((df_cp["tier"] == "T1_VITAL")     & (st == "BROKEN"))
    t1_vital_ws          = _count((df_cp["tier"] == "T1_VITAL")     & (st == "WORN_STRONG"))
    t1_important_broken  = _count((df_cp["tier"] == "T1_IMPORTANT") & (st == "BROKEN"))
    t1_worn_count        = _count(df_cp["tier"].isin(["T1_VITAL","T1_IMPORTANT"]) & (st == "WORN"))
    t1_worn_strong_count = _count(df_cp["tier"].isin(["T1_VITAL","T1_IMPORTANT"]) & (st == "WORN_STRONG"))
    immo_broken_count    = _count(df_cp["is_immobilizing"].astype(bool) & (st == "BROKEN"))
    cf_broken_count      = _count(df_cp["is_critical_functional"].astype(bool) & (st == "BROKEN"))
    nb_penalties         = _count(df_cp["penalty_applied"] > 0)
    nb_ok                = _count(is_scored & (st == "OK"))
    nb_worn              = _count(is_scored & (st == "WORN"))
    nb_worn_strong       = _count(is_scored & (st == "WORN_STRONG"))
    nb_broken            = _count(is_scored & (st == "BROKEN"))
    nb_unknown           = _count(is_scored & (st == "UNKNOWN"))
    nb_repaired          = _count(is_scored & (st == "REPAIRED"))
    nb_scored            = _count(is_scored)

    nb_systems_pen = (
        df_cp[df_cp["penalty_applied"] > 0]
        .groupby("inspection_key")["systeme_fonctionnel"].nunique()
        .reindex(all_keys, fill_value=0)
    )

    # Construction des lignes de score
    score_rows = []
    for _, vrow in df_veh.iterrows():
        key = vrow["inspection_key"]

        total_p_raw = float(total_pen_raw[key])
        total_p_eff = float(total_pen[key])
        vhs_raw     = round(max(0.0, 100.0 - total_p_eff), 2)
        km_p        = round(_km_penalty(vrow.get("kilometrage")), 2)
        vhs_bc      = round(max(0.0, vhs_raw - km_p), 2)

        grade    = _compute_grade(
            int(t1_vital_broken[key]),
            int(t1_vital_ws[key]),
            int(t1_important_broken[key]),
            int(t1_worn_count[key]),
            int(t1_worn_strong_count[key]),
        )
        drivable = immo_broken_count[key] == 0
        has_cf   = cf_broken_count[key] > 0

        decision        = _compute_decision(grade, drivable, has_cf, vhs_bc)
        cap_val, cap_tp = _compute_cap(grade, drivable, has_cf)

        vhs_final        = round(min(vhs_bc, cap_val), 2) if cap_val is not None else vhs_bc
        hard_cap_applied = (cap_val is not None) and (vhs_final < vhs_bc)

        # Score plancher V4
        if drivable and vhs_final < SCORE_FLOOR_DRIVABLE:
            vhs_final = SCORE_FLOOR_DRIVABLE

        ss = safety_agg.get(key)
        fs = functional_agg.get(key)
        cs = cosmetic_agg.get(key)

        score_rows.append({
            "inspection_key":             key,
            "vehicule_sk":                int(vrow["vehicule_sk"])        if pd.notna(vrow.get("vehicule_sk"))        else None,
            "date_inspection_sk":         int(vrow["date_inspection_sk"]) if pd.notna(vrow.get("date_inspection_sk")) else None,
            "immatriculation_norm":       vrow.get("immatriculation_norm"),
            "kilometrage":                float(vrow["kilometrage"])       if pd.notna(vrow.get("kilometrage"))        else None,
            "vhs_raw_score":              vhs_raw,
            "kilometrage_penalty":        km_p,
            "vhs_before_cap":             vhs_bc,
            "vhs_final_score":            vhs_final,
            "safety_score":               round(float(ss), 2) if pd.notna(ss) else None,
            "functional_score":           round(float(fs), 2) if pd.notna(fs) else None,
            "cosmetic_score":             round(float(cs), 2) if pd.notna(cs) else None,
            "safety_grade":               grade,
            "decision":                   decision,
            "is_drivable":                bool(drivable),
            "hard_cap_applied":           bool(hard_cap_applied),
            "hard_cap_type":              cap_tp,
            "cap_value":                  float(cap_val) if cap_val is not None else None,
            "has_critical_functional":    bool(has_cf),
            "nb_penalties_applied":       int(nb_penalties[key]),
            "nb_checkpoints_scored":      int(nb_scored[key]),
            "nb_ok":                      int(nb_ok[key]),
            "nb_worn":                    int(nb_worn[key]),
            "nb_worn_strong":             int(nb_worn_strong[key]),
            "nb_broken":                  int(nb_broken[key]),
            "nb_unknown":                 int(nb_unknown[key]),
            "nb_repaired":                int(nb_repaired[key]),
            "nb_anomalies_total":         int(vrow["nb_anomalies_total"])     if pd.notna(vrow.get("nb_anomalies_total"))     else 0,
            "nb_anomalies_critiques":     int(vrow["nb_anomalies_critiques"]) if pd.notna(vrow.get("nb_anomalies_critiques")) else 0,
            "nb_systems_penalized":       int(nb_systems_pen[key]),
            "penalty_raw_before_cap":     round(total_p_raw, 2),
            "penalty_after_system_cap":   round(total_p_eff, 2),
            "profile_name":               PROFILE_NAME,
            "rule_version":               RULE_VERSION,
            "run_id":                     run_id,
            "calculated_at":              TODAY,
            "source_system":              "IRIS_VHS",
            "created_at":                 TODAY,
        })

    df_scores = pd.DataFrame(score_rows)

    # Construction des lignes de detail de penalite
    df_det = df_cp.copy()
    df_det["is_hard_cap_trigger"] = False
    df_det["hard_cap_type_det"]   = None

    def _mark_trigger(mask: pd.Series, cap_type: str) -> None:
        df_det.loc[mask, "is_hard_cap_trigger"] = True
        df_det.loc[mask, "hard_cap_type_det"]    = cap_type

    # CRITICAL_FUNCTIONAL
    cf_insp = df_scores.loc[df_scores["hard_cap_type"] == "CRITICAL_FUNCTIONAL", "inspection_key"]
    if len(cf_insp):
        _mark_trigger(
            df_det["inspection_key"].isin(cf_insp) &
            df_det["is_critical_functional"].astype(bool) &
            (df_det["observed_status"] == "BROKEN"),
            "CRITICAL_FUNCTIONAL",
        )

    # GRADE_C
    c_keys = df_scores.loc[df_scores["safety_grade"] == "C", "inspection_key"].values
    if len(c_keys):
        vital_ws_mask = t1_vital_ws[c_keys].values >= 1
        _mark_trigger(
            df_det["inspection_key"].isin(c_keys[vital_ws_mask]) &
            (df_det["tier"] == "T1_VITAL") & (df_det["observed_status"] == "WORN_STRONG"),
            "GRADE_C",
        )
        _mark_trigger(
            df_det["inspection_key"].isin(c_keys) &
            (df_det["tier"] == "T1_IMPORTANT") & (df_det["observed_status"] == "BROKEN"),
            "GRADE_C",
        )
        t1_combined        = t1_worn_count[c_keys].values + t1_worn_strong_count[c_keys].values
        high_combined_keys = c_keys[t1_combined >= 4]
        if len(high_combined_keys):
            _mark_trigger(
                df_det["inspection_key"].isin(high_combined_keys) &
                df_det["tier"].isin(["T1_VITAL", "T1_IMPORTANT"]) &
                df_det["observed_status"].isin(["WORN", "WORN_STRONG"]),
                "GRADE_C",
            )

    # IMMOBILIZED
    immo_insp = df_scores.loc[~df_scores["is_drivable"], "inspection_key"]
    if len(immo_insp):
        _mark_trigger(
            df_det["inspection_key"].isin(immo_insp) &
            df_det["is_immobilizing"].astype(bool) &
            (df_det["observed_status"] == "BROKEN"),
            "IMMOBILIZED",
        )

    # GRADE_D (highest priority)
    d_keys = df_scores.loc[df_scores["safety_grade"] == "D", "inspection_key"].values
    if len(d_keys):
        _mark_trigger(
            df_det["inspection_key"].isin(d_keys) &
            (df_det["tier"] == "T1_VITAL") & (df_det["observed_status"] == "BROKEN"),
            "GRADE_D",
        )
        imp_d_mask = t1_important_broken[d_keys].values >= 3
        if imp_d_mask.any():
            _mark_trigger(
                df_det["inspection_key"].isin(d_keys[imp_d_mask]) &
                (df_det["tier"] == "T1_IMPORTANT") & (df_det["observed_status"] == "BROKEN"),
                "GRADE_D",
            )

    df_det["profile_name"] = PROFILE_NAME
    df_det["rule_version"] = RULE_VERSION
    df_det["run_id"]       = run_id
    df_det["created_at"]   = TODAY

    _pen_cols = [
        "inspection_key", "vehicule_sk", "date_inspection_sk", "immatriculation_norm",
        "checkpoint_code",
        "checkpoint_libelle" if "checkpoint_libelle" in df_det.columns else None,
        "zone_controle"      if "zone_controle"      in df_det.columns else None,
        "valeur_controle",
        "observed_status",
        "penalty_applied",
        "penalty_reason",
        "penalty_worn",
        "penalty_broken",
        "penalty_raw_checkpoint",
        "systeme_fonctionnel",
        "penalty_capped_by_system",
        "tier",
        "est_anomalie",
        "est_anomalie_critique",
        "is_vital", "is_important", "is_critical_functional", "is_immobilizing",
        "is_hard_cap_trigger", "hard_cap_type_det",
        "profile_name", "rule_version", "run_id", "created_at",
    ]
    _pen_cols_clean = [c for c in _pen_cols if c is not None and c in df_det.columns]
    df_penalty = df_det[_pen_cols_clean].copy()
    df_penalty = df_penalty.rename(columns={
        "valeur_controle":   "observed_value",
        "hard_cap_type_det": "hard_cap_type",
    })
    if "valeur_controle" not in df_penalty.columns:
        df_penalty["valeur_controle"] = df_det["valeur_controle"].values
    if "est_anomalie" not in df_penalty.columns:
        df_penalty["est_anomalie"] = df_det.get("est_anomalie", False)
    if "est_anomalie_critique" not in df_penalty.columns:
        df_penalty["est_anomalie_critique"] = df_det.get("est_anomalie_critique", False)

    return df_scores, df_penalty


# ---------------------------------------------------------------------------
# Audit -- V4
# ---------------------------------------------------------------------------

def _run_audit_v4(
    df_scores: pd.DataFrame,
    df_penalty: pd.DataFrame,
    df_cp_raw: pd.DataFrame,
    run_id: str,
) -> pd.DataFrame:
    issues: list[dict] = []

    def _add(test: str, key: str, desc: str, severity: str) -> None:
        issues.append({
            "test_name":         test,
            "inspection_key":    key,
            "issue_description": desc,
            "severity":          severity,
            "profile_name":      PROFILE_NAME,
            "rule_version":      RULE_VERSION,
            "run_id":            run_id,
        })

    for _, row in df_scores.iterrows():
        key      = row["inspection_key"]
        decision = row["decision"]
        det      = df_penalty[df_penalty["inspection_key"] == key] if len(df_penalty) else pd.DataFrame()

        if (len(det) > 0 and any((det["tier"] == "T1_VITAL") & (det["observed_status"] == "BROKEN")) and decision == "OK"):
            _add("T1_VITAL_BROKEN_NOT_OK", key, "T1_VITAL BROKEN checkpoint but decision is OK", "CRITICAL")

        if (len(det) > 0 and any((det["tier"] == "T1_VITAL") & (det["observed_status"] == "WORN_STRONG")) and decision == "OK"):
            _add("T1_VITAL_WORN_STRONG_NOT_OK", key, "T1_VITAL WORN_STRONG checkpoint but decision is OK", "CRITICAL")

        if (len(det) > 0 and any(det["is_immobilizing"].astype(bool) & (det["observed_status"] == "BROKEN")) and decision == "OK"):
            _add("IMMOBILIZING_BROKEN_NOT_OK", key, "Immobilizing BROKEN checkpoint but decision is OK", "CRITICAL")

        all_tiers = set(det["tier"].unique()) if len(det) > 0 else set()
        if all_tiers.issubset({"T3_COSMETIC"}) and all_tiers and decision == "CRITIQUE":
            _add("COSMETIC_ONLY_NOT_CRITIQUE", key, "Only T3_COSMETIC penalties but decision is CRITIQUE", "HIGH")

        if row["nb_penalties_applied"] == 0 and decision == "CRITIQUE":
            _add("KM_ALONE_NOT_CRITIQUE", key, "No checkpoint penalties but decision is CRITIQUE", "HIGH")

        if row["hard_cap_applied"] and (row["hard_cap_type"] is None or pd.isna(row["hard_cap_type"])):
            _add("HARD_CAP_TYPE_MISSING", key, "hard_cap_applied=true but hard_cap_type is null", "CRITICAL")

        if decision == "CRITIQUE" and (len(det) == 0 or not any(det["penalty_applied"] > 0)):
            _add("CRITIQUE_NEEDS_EXPLANATION", key, "CRITIQUE decision but no penalty rows in detail", "HIGH")

    if len(df_penalty) > 0 and "tier" in df_penalty.columns:
        bad = df_penalty[(df_penalty["tier"] == "UNKNOWN_REVIEW") & (df_penalty["penalty_applied"] > 0)]
        for _, prow in bad.iterrows():
            _add("UNKNOWN_REVIEW_NO_PENALTY", prow["inspection_key"],
                 f"UNKNOWN_REVIEW checkpoint {prow['checkpoint_code']} has penalty > 0", "CRITICAL")

    if len(df_penalty) > 0 and "observed_value" in df_penalty.columns:
        prop_broken = df_penalty[
            df_penalty["observed_value"].apply(lambda v: _norm_val(v) in _PROPOSITION_VALUES) &
            (df_penalty["observed_status"] == "BROKEN")
        ]
        for _, prow in prop_broken.iterrows():
            _add("PROPOSITION_FAITE_NOT_BROKEN", prow["inspection_key"],
                 f"PROPOSITION FAITE mapped to BROKEN at {prow['checkpoint_code']}", "CRITICAL")

    if len(df_penalty) > 0 and "observed_value" in df_penalty.columns:
        non_broken = df_penalty[
            df_penalty["observed_value"].apply(lambda v: _norm_val(v) in _NON_VALUES) &
            (df_penalty["observed_status"] == "BROKEN")
        ]
        for _, prow in non_broken.iterrows():
            _add("NON_NOT_BROKEN", prow["inspection_key"],
                 f"NON mapped to BROKEN at {prow['checkpoint_code']}", "CRITICAL")

    if len(df_cp_raw) > 0 and "valeur_controle" in df_cp_raw.columns:
        explicit_broken = df_cp_raw[
            df_cp_raw["valeur_controle"].apply(lambda v: _norm_val(v) in _BROKEN_VALUES)
        ]
        if len(explicit_broken) > 0 and len(df_penalty) > 0:
            for key in explicit_broken["inspection_key"].unique():
                det_key = df_penalty[df_penalty["inspection_key"] == key]
                non_broken_explicit = det_key[
                    det_key.get("observed_value", pd.Series(dtype=str)).apply(
                        lambda v: _norm_val(v) in _BROKEN_VALUES
                    ) & (det_key["observed_status"] != "BROKEN")
                ]
                for _, prow in non_broken_explicit.iterrows():
                    _add("EXPLICIT_DEFECT_MUST_BE_BROKEN", key,
                         f"'{prow.get('observed_value')}' should be BROKEN but got {prow['observed_status']}",
                         "CRITICAL")

    cols = ["test_name", "inspection_key", "issue_description", "severity", "profile_name", "rule_version", "run_id"]
    return pd.DataFrame(issues) if issues else pd.DataFrame(columns=cols)


# ---------------------------------------------------------------------------
# V3 vs V4 comparison
# ---------------------------------------------------------------------------

def _compare_v3_v4(
    engine,
    df_v4_scores: pd.DataFrame,
    df_v4_penalty: pd.DataFrame,
    run_id_v4: str,
    logger,
) -> tuple[pd.DataFrame, str]:
    logger.info("  Loading V3 scores for V3 vs V4 comparison ...")
    try:
        with engine.connect() as conn:
            df_v3 = pd.read_sql(
                text("""
                    SELECT inspection_key, immatriculation_norm,
                           vhs_final_score, safety_grade, decision, hard_cap_type
                    FROM mart.fact_vhs_score
                    WHERE run_id = :rid
                """),
                conn, params={"rid": V3_RUN_ID},
            )
    except Exception as exc:
        logger.warning(f"  Could not load V3 scores: {exc}. Skipping comparison.")
        return pd.DataFrame(columns=["inspection_key"]), "V3 scores not available for comparison."

    df_v4 = df_v4_scores[[
        "inspection_key", "vhs_final_score", "safety_grade", "decision", "hard_cap_type",
        "penalty_raw_before_cap", "penalty_after_system_cap",
    ]].copy()

    merged = df_v3.rename(columns={
        "vhs_final_score": "v3_score",
        "safety_grade":    "v3_grade",
        "decision":        "v3_decision",
        "hard_cap_type":   "v3_hard_cap_type",
    }).merge(
        df_v4.rename(columns={
            "vhs_final_score":          "v4_score",
            "safety_grade":             "v4_grade",
            "decision":                 "v4_decision",
            "hard_cap_type":            "v4_hard_cap_type",
            "penalty_raw_before_cap":   "v4_pen_raw",
            "penalty_after_system_cap": "v4_pen_effective",
        }),
        on="inspection_key", how="outer",
    )

    merged["score_delta"]      = (merged["v4_score"] - merged["v3_score"]).round(2)
    merged["grade_changed"]    = merged["v3_grade"]    != merged["v4_grade"]
    merged["decision_changed"] = merged["v3_decision"] != merged["v4_decision"]

    cmp_cols = [
        "inspection_key", "immatriculation_norm",
        "v3_score", "v4_score", "score_delta",
        "v3_grade", "v4_grade", "grade_changed",
        "v3_decision", "v4_decision", "decision_changed",
        "v3_hard_cap_type", "v4_hard_cap_type",
        "v4_pen_raw", "v4_pen_effective",
    ]
    df_cmp = merged[[c for c in cmp_cols if c in merged.columns]].copy()
    df_cmp = df_cmp.sort_values("score_delta", ascending=True).reset_index(drop=True)

    n_total      = len(df_cmp)
    n_dec_change = int(df_cmp["decision_changed"].sum()) if "decision_changed" in df_cmp else 0
    n_grd_change = int(df_cmp["grade_changed"].sum())    if "grade_changed"    in df_cmp else 0

    def _dist(col):
        return df_cmp[col].value_counts().sort_index().to_dict() if col in df_cmp else {}

    v3_dec = _dist("v3_decision")
    v4_dec = _dist("v4_decision")
    v3_grd = _dist("v3_grade")
    v4_grd = _dist("v4_grade")

    def _score_stats(col):
        s = df_cmp[col].dropna()
        return (round(s.mean(), 2), round(s.min(), 2), round(s.max(), 2)) if len(s) else (0.0, 0.0, 0.0)

    v3_avg, v3_min, v3_max = _score_stats("v3_score")
    v4_avg, v4_min, v4_max = _score_stats("v4_score")

    n_sys_capped = int(df_v4_penalty.get("penalty_capped_by_system", pd.Series([False])).sum()) if len(df_v4_penalty) > 0 else 0

    decision_order = ["CRITIQUE", "DEGRADE", "IMMOBILISE", "OK"]
    grade_order    = ["A", "B", "C", "D"]

    dec_table = (
        "| Decision | V3 | V4 | Delta |\n|---|---|---|---|\n" +
        "\n".join(
            f"| {d} | {v3_dec.get(d,0)} | {v4_dec.get(d,0)} | {v4_dec.get(d,0)-v3_dec.get(d,0):+d} |"
            for d in decision_order
        )
    )
    grd_table = (
        "| Grade | V3 | V4 | Delta |\n|---|---|---|---|\n" +
        "\n".join(
            f"| {g} | {v3_grd.get(g,0)} | {v4_grd.get(g,0)} | {v4_grd.get(g,0)-v3_grd.get(g,0):+d} |"
            for g in grade_order
        )
    )

    markdown = dedent(f"""
    # VHS V3 vs V4 Candidate -- Comparison Summary

    ## 1. Run IDs
    | | Value |
    |---|---|
    | V3 run_id | `{V3_RUN_ID}` |
    | V4 run_id | `{run_id_v4}` |
    | Inspections compared | {n_total} |
    | Decision changed | {n_dec_change} ({round(100*n_dec_change/n_total,1) if n_total else 0}%) |
    | Safety grade changed | {n_grd_change} ({round(100*n_grd_change/n_total,1) if n_total else 0}%) |

    ## 2. Decision Distribution
    {dec_table}

    ## 3. Safety Grade Distribution
    {grd_table}

    ## 4. Score Statistics
    | Metric | V3 | V4 |
    |---|---|---|
    | Average score | {v3_avg} | {v4_avg} |
    | Min score | {v3_min} | {v4_min} |
    | Max score | {v3_max} | {v4_max} |

    ## 5. Changements cles V3 -> V4
    | Aspect | V3 | V4 |
    |---|---|---|
    | Penalite WORN_STRONG | (worn+broken)/2 | worn x 0.6 |
    | Regroupement systemes | Non | Oui (plafond par systeme) |
    | Score plancher si roulable | 0 | {SCORE_FLOOR_DRIVABLE} |
    | Checkpoints plafonnes par systeme | N/A | {n_sys_capped} |

    ## 6. Plafonds par systeme (V4)
    | Systeme | Cap (pts) |
    |---|---|
    | SYS_FREINAGE | {SYSTEM_CAP.get('SYS_FREINAGE')} |
    | SYS_SUSPENSION | {SYSTEM_CAP.get('SYS_SUSPENSION')} |
    | SYS_TRANSMISSION | {SYSTEM_CAP.get('SYS_TRANSMISSION')} |
    | SYS_MOTEUR | {SYSTEM_CAP.get('SYS_MOTEUR')} |
    | SYS_PNEUS_AV | {SYSTEM_CAP.get('SYS_PNEUS_AV')} |
    | SYS_PNEUS_AR | {SYSTEM_CAP.get('SYS_PNEUS_AR')} |
    | SYS_STRUCTURE | {SYSTEM_CAP.get('SYS_STRUCTURE')} |
    | SYS_ECHAPPEMENT | {SYSTEM_CAP.get('SYS_ECHAPPEMENT')} |
    | SYS_ECLAIRAGE | {SYSTEM_CAP.get('SYS_ECLAIRAGE')} |
    | SYS_ELECTRIQUE | {SYSTEM_CAP.get('SYS_ELECTRIQUE')} |

    *Generated by etl/mart/compute_vhs_v4_candidate.py*
    *V1, V2 and V3 data are unchanged.*
    """).strip()

    return df_cmp, markdown


# ---------------------------------------------------------------------------
# Rapports audit CSV + markdown
# ---------------------------------------------------------------------------

def _generate_audit_reports(
    df_scores: pd.DataFrame,
    df_penalty: pd.DataFrame,
    df_audit: pd.DataFrame,
    df_cmp: pd.DataFrame,
    run_id: str,
    report_dir: Path,
    logger,
) -> dict[str, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    p = report_dir / "vhs_v4_distribution_by_decision.csv"
    df_scores["decision"].value_counts().reset_index().rename(
        columns={"index": "decision", "decision": "count"}
    ).to_csv(p, index=False, encoding="utf-8-sig")
    paths["decision"] = p

    p = report_dir / "vhs_v4_distribution_by_grade.csv"
    df_scores["safety_grade"].value_counts().reset_index().rename(
        columns={"index": "safety_grade", "safety_grade": "count"}
    ).to_csv(p, index=False, encoding="utf-8-sig")
    paths["grade"] = p

    p = report_dir / "vhs_v4_observed_status_distribution.csv"
    if len(df_penalty) > 0 and "observed_status" in df_penalty.columns:
        df_penalty["observed_status"].value_counts().reset_index().rename(
            columns={"index": "observed_status", "observed_status": "count"}
        ).to_csv(p, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(columns=["observed_status", "count"]).to_csv(p, index=False)
    paths["status"] = p

    p = report_dir / "vhs_v4_penalty_by_system.csv"
    if len(df_penalty) > 0 and "systeme_fonctionnel" in df_penalty.columns:
        sys_report = df_penalty.groupby("systeme_fonctionnel").agg(
            total_penalty_applied=("penalty_applied", "sum"),
            total_penalty_raw=("penalty_raw_checkpoint", "sum"),
            n_checkpoints=("penalty_raw_checkpoint", "count"),
            n_capped=("penalty_capped_by_system", "sum"),
            avg_penalty_applied=("penalty_applied", "mean"),
        ).reset_index()
        sys_report["system_cap"] = sys_report["systeme_fonctionnel"].map(
            lambda s: SYSTEM_CAP.get(s, "no_cap")
        )
        sys_report.to_csv(p, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame().to_csv(p, index=False)
    paths["system"] = p

    p = report_dir / "vhs_v4_penalty_by_tier.csv"
    if len(df_penalty) > 0 and "tier" in df_penalty.columns:
        df_penalty.groupby("tier")["penalty_applied"].agg(
            total_penalty="sum", n_rows="count", avg_penalty="mean"
        ).reset_index().to_csv(p, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(columns=["tier", "total_penalty", "n_rows", "avg_penalty"]).to_csv(p, index=False)
    paths["tier"] = p

    p = report_dir / "vhs_v4_ambiguous_values_mapping.csv"
    if len(df_penalty) > 0 and "observed_value" in df_penalty.columns:
        ambi = df_penalty.groupby(["observed_value", "observed_status"]).size().reset_index(name="count")
        ambi = ambi[ambi["observed_value"].apply(
            lambda v: _norm_val(v) in _PROPOSITION_VALUES | _NON_VALUES | _INTERVENTION_VALUES
        )]
        ambi.to_csv(p, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(columns=["observed_value", "observed_status", "count"]).to_csv(p, index=False)
    paths["ambiguous"] = p

    p = report_dir / "vhs_v3_vs_v4_comparison.csv"
    df_cmp.to_csv(p, index=False, encoding="utf-8-sig")
    paths["comparison"] = p

    # Audit summary markdown
    p = report_dir / "vhs_v4_audit_summary.md"
    n_total  = len(df_scores)
    dec_dist = df_scores["decision"].value_counts().sort_index().to_dict()
    grd_dist = df_scores["safety_grade"].value_counts().sort_index().to_dict()
    n_ws     = int((df_penalty["observed_status"] == "WORN_STRONG").sum()) if len(df_penalty) else 0
    n_capped = int(df_penalty.get("penalty_capped_by_system", pd.Series([False])).sum()) if len(df_penalty) else 0
    vhs_final = df_scores["vhs_final_score"]
    pen_raw   = df_scores.get("penalty_raw_before_cap",  pd.Series(dtype=float))
    pen_eff   = df_scores.get("penalty_after_system_cap", pd.Series(dtype=float))

    dec_table_md = (
        "| Decision | Count |\n|---|---|\n" +
        "\n".join(f"| {d} | {dec_dist.get(d,0)} |" for d in ["OK","DEGRADE","IMMOBILISE","CRITIQUE"])
    )
    grd_table_md = (
        "| Grade | Count |\n|---|---|\n" +
        "\n".join(f"| {g} | {grd_dist.get(g,0)} |" for g in ["A","B","C","D"])
    )

    md = dedent(f"""
    # VHS_BALANCED_V4_CANDIDATE -- Audit Summary

    **Run ID:** `{run_id}`
    **Profile:** `{PROFILE_NAME}`
    **Date:** {TODAY.strftime('%Y-%m-%d')}

    ## 1. Objectif & Philosophie

    V4 corrige deux problemes identifies dans V3 :

    **Probleme 1 -- Sur-penalisation WORN_STRONG:**
    En V3, WORN_STRONG = (worn + broken) / 2.
    Sur un frein (penalty_worn=10, penalty_broken=25) : 17.5 pts x 6 composants = 105 pts -> score 0.
    En V4, WORN_STRONG = penalty_worn x 0.6 = 6 pts x 6 = 36 pts -> conserve la granularite.

    **Probleme 2 -- Double comptage par systeme:**
    En V3, plaquettes + disques + etriers + rotules = 4x le meme systeme.
    En V4, chaque systeme a un plafond : SYS_FREINAGE = max {SYSTEM_CAP.get('SYS_FREINAGE')} pts.

    **Score plancher:**
    Vehicule roulable + inspecte -> score minimum = {SCORE_FLOOR_DRIVABLE} / 100.

    ## 2. Dataset
    | Metric | Value |
    |---|---|
    | Total inspections scored | {n_total:,} |
    | Total penalty detail rows | {len(df_penalty):,} |
    | WORN_STRONG rows | {n_ws:,} |
    | Checkpoints plafonnes par systeme | {n_capped:,} |

    ## 3. Decision Distribution
    {dec_table_md}

    ## 4. Grade Distribution
    {grd_table_md}

    ## 5. Score Statistics
    | Metric | Value |
    |---|---|
    | Average vhs_final_score | {vhs_final.mean():.2f} |
    | Min vhs_final_score | {vhs_final.min():.2f} |
    | Max vhs_final_score | {vhs_final.max():.2f} |
    | Average penalite brute (avant cap systeme) | {pen_raw.mean():.2f} |
    | Average penalite effective (apres cap systeme) | {pen_eff.mean():.2f} |

    ## 6. Regles de scoring V4
    | Statut | Formule V3 | Formule V4 |
    |---|---|---|
    | OK | 0 | 0 |
    | WORN | penalty_worn | penalty_worn |
    | WORN_STRONG | (worn + broken) / 2 | **worn x 0.6** |
    | BROKEN | penalty_broken | penalty_broken |
    | REPAIRED | 0 | 0 |
    | UNKNOWN | 0 | 0 |

    ## 7. Audit Issues
    Total V4 contract violations: **{len(df_audit)}**
    {"No issues found." if len(df_audit) == 0 else df_audit[['test_name','inspection_key','issue_description','severity']].head(20).to_markdown(index=False)}

    ## 8. Recommandation
    V4 est une version candidate necessitant validation metier par BNA Assurances avant
    promotion en production.
    **V1, V2 et V3 data sont inchangees.**

    *Generated by `etl/mart/compute_vhs_v4_candidate.py`*
    """).strip()

    p.write_text(md, encoding="utf-8")
    paths["summary"] = p

    logger.info(f"  Reports written to: {report_dir}")
    for name, fpath in paths.items():
        logger.info(f"    {name:<15}: {fpath.name}")

    return paths


# ---------------------------------------------------------------------------
# Orchestrateur principal
# ---------------------------------------------------------------------------

def compute_vhs_v4_candidate():
    logger = dwh_utils.setup_logging("compute_vhs_v4_candidate")
    run_id = f"VHS_BALANCED_V4_CANDIDATE_{TODAY.strftime('%Y%m%d_%H%M%S')}"

    logger.info("=" * 70)
    logger.info(f"[RUN] {run_id}")
    logger.info(f"      profile={PROFILE_NAME}  rule={RULE_VERSION}")
    logger.info("  V1, V2 and V3 data will NOT be modified")
    logger.info("  V4 Key changes vs V3:")
    logger.info("    - WORN_STRONG penalty: worn x 0.6 (instead of (worn+broken)/2)")
    logger.info("    - System grouping with caps to avoid double-counting")
    logger.info(f"    - Score floor for drivable vehicles: {SCORE_FLOOR_DRIVABLE}")
    logger.info("=" * 70)

    engine = dwh_utils.build_engine(logger)

    # 1. DDL
    with engine.begin() as conn:
        conn.execute(text(DDL_CREATE_SCHEMA))
        conn.execute(text(DDL_FACT_VHS_SCORE))
        conn.execute(text(DDL_FACT_VHS_PENALTY_DETAIL))
        for stmt in DDL_V4_SCORE_COLS + DDL_V4_PENALTY_COLS:
            conn.execute(text(stmt))
    logger.info("  DDL: tables and V4 columns ensured")

    # 2. Load source data
    with engine.connect() as conn:
        df_veh    = pd.read_sql(text("SELECT * FROM dwh.fact_inspection_vehicule"), conn)
        df_cp_raw = pd.read_sql(text("SELECT * FROM dwh.fact_inspection_checkpoint"), conn)
        df_dim    = pd.read_sql(
            text("SELECT * FROM mart.dim_checkpoint WHERE is_vhs_scored = true"), conn
        )
    logger.info(f"  inspections loaded        : {len(df_veh)}")
    logger.info(f"  checkpoint observations   : {len(df_cp_raw)}")
    logger.info(f"  scored dim_checkpoint rows: {len(df_dim)}")

    # 3. Compute V4
    df_scores, df_penalty = _process_all_v4(df_veh, df_cp_raw, df_dim, run_id)

    n_ws     = int((df_penalty["observed_status"] == "WORN_STRONG").sum())  if len(df_penalty) else 0
    n_broken = int((df_penalty["observed_status"] == "BROKEN").sum())       if len(df_penalty) else 0
    n_capped = int(df_penalty.get("penalty_capped_by_system", pd.Series([False])).sum()) if len(df_penalty) else 0

    _prop_broken = int(df_penalty[
        df_penalty.get("observed_value", pd.Series(dtype=str)).apply(lambda v: _norm_val(v) in _PROPOSITION_VALUES) &
        (df_penalty["observed_status"] == "BROKEN")
    ].shape[0]) if len(df_penalty) else 0

    _non_broken = int(df_penalty[
        df_penalty.get("observed_value", pd.Series(dtype=str)).apply(lambda v: _norm_val(v) in _NON_VALUES) &
        (df_penalty["observed_status"] == "BROKEN")
    ].shape[0]) if len(df_penalty) else 0

    vhs_stats = df_scores["vhs_final_score"]
    pen_raw   = df_scores.get("penalty_raw_before_cap",  pd.Series(dtype=float))
    pen_eff   = df_scores.get("penalty_after_system_cap", pd.Series(dtype=float))

    logger.info(f"  V4 scores computed        : {len(df_scores)}")
    logger.info(f"  penalty detail rows       : {len(df_penalty)}")
    logger.info(f"  WORN_STRONG rows          : {n_ws}")
    logger.info(f"  BROKEN rows               : {n_broken}")
    logger.info(f"  Checkpoints sys-capped    : {n_capped}")
    logger.info(f"  PROPOSITION FAITE->BROKEN : {_prop_broken}  (must be 0)")
    logger.info(f"  NON->BROKEN               : {_non_broken}  (must be 0)")
    logger.info(f"  VHS scores avg={vhs_stats.mean():.1f}  min={vhs_stats.min():.1f}  max={vhs_stats.max():.1f}")
    logger.info(f"  Penalty raw avg (before)  : {pen_raw.mean():.1f}")
    logger.info(f"  Penalty eff avg (after)   : {pen_eff.mean():.1f}")

    # 4. Idempotency
    with engine.begin() as conn:
        conn.execute(text("""
            DELETE FROM mart.fact_vhs_score
            WHERE profile_name = :p AND rule_version = :v AND run_id = :r
        """), {"p": PROFILE_NAME, "v": RULE_VERSION, "r": run_id})
        conn.execute(text("""
            DELETE FROM mart.fact_vhs_penalty_detail
            WHERE profile_name = :p AND rule_version = :v AND run_id = :r
        """), {"p": PROFILE_NAME, "v": RULE_VERSION, "r": run_id})

    # 5. Insert scores
    with engine.begin() as conn:
        df_scores.to_sql(
            "fact_vhs_score", conn, schema="mart",
            if_exists="append", index=False, chunksize=500, method="multi",
        )
    logger.info(f"  inserted -> mart.fact_vhs_score          : {len(df_scores)} rows")

    # 6. Insert penalty details
    if len(df_penalty) > 0:
        with engine.begin() as conn:
            df_penalty.to_sql(
                "fact_vhs_penalty_detail", conn, schema="mart",
                if_exists="append", index=False, chunksize=500, method="multi",
            )
    logger.info(f"  inserted -> mart.fact_vhs_penalty_detail : {len(df_penalty)} rows")

    # 7. Audit
    df_audit = _run_audit_v4(df_scores, df_penalty, df_cp_raw, run_id)
    logger.info(f"  V4 audit issues           : {len(df_audit)}")

    # 8. V3 vs V4 comparison
    df_cmp, md_cmp = _compare_v3_v4(engine, df_scores, df_penalty, run_id, logger)
    n_dec_changes = int(df_cmp["decision_changed"].sum()) if "decision_changed" in df_cmp.columns else 0
    n_grd_changes = int(df_cmp["grade_changed"].sum())    if "grade_changed"    in df_cmp.columns else 0

    # 9. Write reports
    report_paths = _generate_audit_reports(
        df_scores, df_penalty, df_audit, df_cmp, run_id, REPORT_DIR, logger
    )
    md_cmp_path = REPORT_DIR / "vhs_v3_vs_v4_comparison_summary.md"
    md_cmp_path.write_text(md_cmp, encoding="utf-8")

    # 10. Console summary
    decision_counts = df_scores["decision"].value_counts().sort_index().to_dict()
    grade_counts    = df_scores["safety_grade"].value_counts().sort_index().to_dict()
    status_counts   = df_penalty["observed_status"].value_counts().sort_index().to_dict() if len(df_penalty) else {}

    print("=" * 70)
    print(f"  run_id                       : {run_id}")
    print(f"  total inspections scored     : {len(df_scores)}")
    print()
    print("  Decision distribution (V4):")
    for k in ["OK", "DEGRADE", "IMMOBILISE", "CRITIQUE"]:
        print(f"    {k:<15}: {decision_counts.get(k, 0)}")
    print()
    print("  Safety grade distribution (V4):")
    for k in ["A", "B", "C", "D"]:
        print(f"    Grade {k}: {grade_counts.get(k, 0)}")
    print()
    print("  Observed status distribution (V4):")
    for k in ["OK", "WORN", "WORN_STRONG", "BROKEN", "REPAIRED", "UNKNOWN"]:
        print(f"    {k:<15}: {status_counts.get(k, 0)}")
    print()
    print(f"  PROPOSITION FAITE -> BROKEN  : {_prop_broken}  (V4 contract: must be 0)")
    print(f"  NON -> BROKEN                : {_non_broken}  (V4 contract: must be 0)")
    print(f"  WORN_STRONG rows             : {n_ws}")
    print(f"  Checkpoints sys-capped       : {n_capped}")
    print()
    print(f"  Penalty avg (raw before cap) : {pen_raw.mean():.1f}")
    print(f"  Penalty avg (after sys cap)  : {pen_eff.mean():.1f}")
    print()
    print(f"  V3 vs V4 decision changes    : {n_dec_changes}")
    print(f"  V3 vs V4 grade changes       : {n_grd_changes}")
    print()
    print(f"  VHS final avg={vhs_stats.mean():.1f}  min={vhs_stats.min():.1f}  max={vhs_stats.max():.1f}")
    print(f"  Audit issues                 : {len(df_audit)}")
    print()
    print(f"  Audit report folder: {REPORT_DIR}")
    for name, fpath in report_paths.items():
        print(f"    {fpath.name}")
    print("=" * 70)

    logger.info(f"Done: {len(df_scores)} V4 scores, {len(df_penalty)} penalty rows -> mart")
    return df_scores, df_penalty, df_audit, df_cmp


if __name__ == "__main__":
    compute_vhs_v4_candidate()
