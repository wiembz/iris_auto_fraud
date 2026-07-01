# T1 Criticality Diagnostic — VHS_BALANCED_V1_20260630_103138

    ---

    ## 1. Context

    VHS_BALANCED_V1 is **technically coherent** (0 business rule audit issues).
    However, the decision distribution is severe:
    - CRITIQUE = 54.9% (157 / 286 inspections)
    - Grade D = 54.9% — CRITIQUE is exclusively safety-grade-driven
    - Grade B = 0 — no inspection has only non-critical T1 anomalies

    This diagnostic investigates whether `est_anomalie_critique = true` in the source
    inspection data is proportionate to the actual vehicle condition.

    The core question:
    > **Is `est_anomalie_critique` over-assigned in the staging data,
    > or do these inspections genuinely reflect critical defects?**

    ---

    ## 2. T1 Criticality Distribution

    | Metric | Value |
    |---|---|
    | T1 checkpoint rows (all observations) | 3146 |
    | T1 rows: OK (no anomaly) | 2710 |
    | T1 rows: WORN (non-critical anomaly) | 0 |
    | T1 rows: BROKEN (critical anomaly) | 436 |
    | % of T1 rows that are critical | 13.9% |

    ### Top T1 Checkpoints by Critical Anomaly Count

    | checkpoint | tier | nb_critique | pct_critique |
|---|---|---|---|
| Controle gaine transmissions rotules c | T1_VITAL | 93 | 32.5% |
| Controle des plaquettes de freins av | T1_VITAL | 67 | 23.4% |
| Pneus arriere | T1_IMPORTANT | 45 | 15.7% |
| Pneus avant | T1_IMPORTANT | 44 | 15.4% |
| Controle disques av | T1_VITAL | 40 | 14.0% |
| Controle etancheite des amortisseurs a | T1_IMPORTANT | 39 | 13.6% |
| Controle etancheite des amortisseurs 1 | T1_IMPORTANT | 35 | 12.2% |
| Controle des plaquettes de freins ar s | T1_VITAL | 34 | 11.9% |
| Controle disques ar selon equipement | T1_VITAL | 17 | 5.9% |
| Controle du niveau du liquide de frein | T1_VITAL | 16 | 5.6% |

    ---

    ## 3. valeur_controle Interpretation for T1 Checkpoints

    The table below shows how `valeur_controle` values map to `est_anomalie_critique`
    for T1 checkpoints only.

    | valeur_controle | est_anomalie_critique | n |
|---|---|---|
| Contrôle OK | False | 2222 |
| Bon | False | 483 |
| Intervention conseillée | True | 226 |
| Contrôle non OK | True | 121 |
| Défectueux | True | 75 |
| Proposition faite | True | 14 |
| Réparation effectuée suite à l’accord client | False | 5 |

    ### Key observations:

    - **`Intervention conseillée`** — literally means "intervention recommended".
      This is an advisory flag. If `est_anomalie_critique = true` for these rows,
      it means the inspector marked the intervention as urgent/safety-critical.
      This is the most ambiguous case: an "advisory" combined with a "critical" flag
      could indicate either genuine urgency or systematic over-flagging.

    - **`Contrôle non OK`** — control not OK. More likely to reflect a real defect.

    - **`Défectueux`** — defective. Strongest wording; critical flag is most justified here.

    - **`NON`** — negative result, usually non-critical. Appears with est_anomalie=true only.

    - **`Proposition faite` / `PROPOSITION FAITE`** — proposal made (for repair/replacement).
      May or may not be critical depending on inspector assessment.

    ---

    ## 4. Possible Overcriticality — `Intervention conseillée` with est_anomalie_critique = true

    Total cases: **226**

    These are T1 checkpoints where the valeur_controle says "Intervention conseillée"
    (advisory) but est_anomalie_critique is set to true (critical/BROKEN in VHS).

    | checkpoint | tier | nb_intervention_critique |
|---|---|---|
| Controle gaine transmissions rotules c | T1_VITAL | 71 |
| Controle des plaquettes de freins av | T1_VITAL | 43 |
| Controle disques av | T1_VITAL | 29 |
| Controle etancheite des amortisseurs 1 | T1_IMPORTANT | 21 |
| Controle etancheite des amortisseurs a | T1_IMPORTANT | 18 |
| Controle des plaquettes de freins ar s | T1_VITAL | 17 |
| Controle du niveau du liquide de frein | T1_VITAL | 14 |
| Controle disques ar selon equipement | T1_VITAL | 8 |
| Controle etriers | T1_VITAL | 5 |

    ### Why this matters:

    In VHS_BALANCED_V1, the normalization rule is:
    - `est_anomalie_critique = true` → `observed_status = BROKEN` → `penalty_broken`

    If "Intervention conseillée" should semantically be WORN (advisory) rather than BROKEN
    (immediate danger), then these 226 cases would be over-penalized.

    However, the VHS specification uses `est_anomalie_critique` as the authoritative flag
    regardless of the text label — this is correct if the inspector workflow guarantees
    that `est_anomalie_critique` is only set for genuinely critical defects.

    The question to validate with domain experts:
    > **Can an inspector set `est_anomalie_critique = true` while writing
    > "Intervention conseillée" (advisory), and is that intentional?**

    ---

    ## 5. Recommendations

    Do not change VHS weights, penalties, or tier classifications before answering:

    ### Option A — Keep current mapping (no change)
    If the business confirms that `est_anomalie_critique = true` always reflects a
    genuine safety-critical defect regardless of valeur_controle text, then the
    current scoring is correct.
    The CRITIQUE rate reflects the actual fleet condition.

    ### Option B — Differentiate by valeur_controle text
    Map `est_anomalie_critique = true` + `valeur_controle = 'Intervention conseillée'`
    to a new status `WORN_STRONG` with a penalty between `penalty_worn` and `penalty_broken`.
    This would prevent BROKEN classification for advisory-level critical flags.
    **This requires updating `normalize_observed_status` in `compute_vhs.py`.**

    ### Option C — Tighten the Grade D condition
    Require ≥2 T1_VITAL BROKEN (instead of 1) before assigning Grade D.
    This would reduce Grade D / CRITIQUE counts without changing individual penalties.
    **This requires updating `_compute_grade` in `compute_vhs.py`.**

    ### Recommended sequence:
    1. Share `t1_possible_overcritical_cases.csv` and `t1_broken_to_grade_d_link.csv`
       with the domain expert / inspection data owner.
    2. Validate whether `est_anomalie_critique` is systematically over-assigned
       for `Intervention conseillée` rows.
    3. Decide on Option A, B, or C (or a combination).
    4. Implement as VHS_BALANCED_V2 only after validation.

    ---

    *Generated by etl/mart/audit_vhs_t1_criticality.py — read-only, no DB modifications.*