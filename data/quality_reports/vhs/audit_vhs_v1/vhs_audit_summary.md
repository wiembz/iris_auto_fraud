# VHS V1 Audit Report — VHS_BALANCED_V1_20260630_103138

    ---

    ## 1. VHS V1 Run Summary

    | Metric | Value |
    |---|---|
    | run_id | `VHS_BALANCED_V1_20260630_103138` |
    | profile | VHS_BALANCED_V1 |
    | rule version | VHS_BALANCED_V1 |
    | inspections scored | 286 |
    | penalty detail rows | 1186 |
    | vhs_final_score avg | 51.82 |
    | vhs_final_score min | 0.00 |
    | vhs_final_score max | 100.00 |

    ### Decision Distribution

    | decision | nb | % |
|---|---|---|
| CRITIQUE | 157 | 54.9 |
| OK | 86 | 30.07 |
| DEGRADE | 38 | 13.29 |
| IMMOBILISE | 5 | 1.75 |

    ### Safety Grade Distribution

    | grade | nb | % |
|---|---|---|
| A | 95 | 33.22 |
| C | 34 | 11.89 |
| D | 157 | 54.9 |

    ### Hard Cap Distribution

    | cap type | nb |
|---|---|
| CRITICAL_FUNCTIONAL | 4 |
| GRADE_C | 24 |
| GRADE_D | 73 |
| IMMOBILIZED | 4 |

    ---

    ## 2. Main Observations

    ### 2.1 High CRITIQUE Rate

    **157 out of 286 inspections (54.9%)** are classified CRITIQUE.
    This is a severe distribution for a fleet scoring system.

    The primary driver is **safety grade logic**:
    Grade D accounts for exactly 157 inspections, which equals the number of CRITIQUE decisions.
    This means CRITIQUE is almost entirely driven by Grade D, not by VHS thresholds.

    Grade D is triggered when:
    - at least one T1_VITAL checkpoint is BROKEN, OR
    - at least 3 T1_IMPORTANT checkpoints are BROKEN.

    ### 2.2 Grade B = 0

    Grade B requires at least one T1 WORN checkpoint with no T1 BROKEN.
    Grade B count is **0**.

    In the penalty detail table, across all T1 checkpoints:
    - T1 BROKEN occurrences: 436
    - T1 WORN occurrences: 0
    - Total T1 anomaly occurrences: 436

    The vast majority of T1 anomalies are BROKEN, not WORN.

    In VHS_BALANCED_V1, `est_anomalie_critique = true` maps directly to BROKEN.
    If an inspection has even one T1 checkpoint with `est_anomalie_critique = true`,
    it immediately achieves Grade D, bypassing Grade B and C entirely.
    This is the direct cause of Grade B = 0.

    This does **not** mean the code is wrong.
    It means the `est_anomalie_critique` flag in the source data is very frequently set,
    and the critical classification covers almost all T1 anomalies.
    **This should be reviewed before validating the calibration.**

    ### 2.3 Hard Caps Activate Frequently

    Hard caps were applied to a significant portion of inspections.
    When a hard cap is applied, it means the VHS score was already above the cap limit —
    the scoring penalties alone were not severe enough to breach the cap threshold,
    but the grade/drivability rule enforces the ceiling.

    ---

    ## 3. Top Penalty Drivers

    The following checkpoints contributed the most total penalty points across all inspections:

    | # | checkpoint_libelle | tier | observed_status | nb | total_penalty |
|---|---|---|---|---|---|
| 1 | Controle gaine transmissions rotules c | T1_VITAL | BROKEN | 93 | 2325.0 |
| 2 | Controle des plaquettes de freins av | T1_VITAL | BROKEN | 67 | 1675.0 |
| 3 | Controle disques av | T1_VITAL | BROKEN | 40 | 1000.0 |
| 4 | Controle des plaquettes de freins ar s | T1_VITAL | BROKEN | 34 | 850.0 |
| 5 | Pneus arriere | T1_IMPORTANT | BROKEN | 45 | 675.0 |
| 6 | Pneus avant | T1_IMPORTANT | BROKEN | 44 | 660.0 |
| 7 | Controle etancheite des amortisseurs a | T1_IMPORTANT | BROKEN | 39 | 585.0 |
| 8 | Controle etancheite des amortisseurs 1 | T1_IMPORTANT | BROKEN | 35 | 525.0 |
| 9 | Controle disques ar selon equipement | T1_VITAL | BROKEN | 17 | 425.0 |
| 10 | Controle du niveau du liquide de frein | T1_VITAL | BROKEN | 16 | 400.0 |

    ---

    ## 4. Grade D Drivers

    The following checkpoints most frequently triggered the GRADE_D hard cap:

    | checkpoint_libelle | tier | observed_status | nb |
|---|---|---|---|
| Controle gaine transmissions rotules c | T1_VITAL | BROKEN | 93 |
| Controle des plaquettes de freins av | T1_VITAL | BROKEN | 67 |
| Controle disques av | T1_VITAL | BROKEN | 40 |
| Controle des plaquettes de freins ar s | T1_VITAL | BROKEN | 34 |
| Controle disques ar selon equipement | T1_VITAL | BROKEN | 17 |
| Controle du niveau du liquide de frein | T1_VITAL | BROKEN | 16 |
| Controle etriers | T1_VITAL | BROKEN | 6 |

    The dominant trigger is `sous_le_vehicule_controle_gaine_transmissions_rotules_c`
    (transmission joints / ball joints) and brake disc/pad checkpoints —
    all classified T1_VITAL. Any single BROKEN occurrence yields Grade D.

    ---

    ## 5. Business Interpretation

    ### 5.1 Technical Coherence

    The VHS_BALANCED_V1 computation is **technically coherent**:
    - Business rule audit issues = 0.
    - All hard cap triggers correctly trace to penalty detail rows.
    - UNKNOWN_REVIEW checkpoints contributed zero penalties.
    - Scoring is fully explainable via mart.fact_vhs_penalty_detail.

    ### 5.2 Calibration Concern

    The score distribution is **potentially too strict** for a first production version:
    - 54.9% CRITIQUE is high if the expectation is a normal fleet distribution.
    - Grade D is triggered by a single T1_VITAL BROKEN event, with no exception.
    - `est_anomalie_critique = true` is the source-level flag. Its frequency and reliability
      in the staging data must be verified before finalizing the scoring model.

    ### 5.3 What This Means

    The current results reflect the data as-is:
    - If the source data quality is reliable and inspections are genuinely severe,
      the distribution may be correct.
    - If `est_anomalie_critique` is over-assigned in the staging pipeline,
      the penalties and grade logic will systematically over-classify.

    **The system needs domain expert review before calibration decisions are made.**

    ---

    ## 6. Recommended Next Steps

    1. **Do not change weights immediately.**
       The current distribution should first be reviewed by a vehicle inspection domain expert.

    2. **Review the top 191 high-severity cases** listed in
       `vhs_high_severity_review_candidates.csv`.
       Verify whether the CRITIQUE classification reflects real vehicle conditions.

    3. **Check `est_anomalie_critique` reliability.**
       If this flag is set too liberally in the staging pipeline,
       all downstream scores will be skewed toward BROKEN, Grade D, and CRITIQUE.

    4. **Consider softening the Grade D trigger for VHS_BALANCED_V2:**
       - Option A: Require ≥2 T1_VITAL BROKEN (instead of 1) for Grade D.
       - Option B: Keep Grade D at 1 T1_VITAL BROKEN, but cap the penalty (e.g., cap=55 instead of 40).
       - Option C: Distinguish between `Intervention conseillée` (advisory) and `Défectueux` (defective)
         when assigning BROKEN vs WORN, rather than relying solely on `est_anomalie_critique`.

    5. **Prepare VHS_BALANCED_V2 only after:**
       - Confirming data quality of `est_anomalie_critique` with the data owner.
       - Reviewing at least 20 CRITIQUE cases manually.
       - Defining the expected target distribution with the business team.

    ---

    *Report generated by etl/mart/audit_vhs_v1.py — read-only analysis of VHS_BALANCED_V1_20260630_103138.*