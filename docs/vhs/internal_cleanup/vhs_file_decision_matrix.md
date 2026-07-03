# VHS File Decision Matrix

> Generated: 2026-07-03  
> Author: project cleanup audit  
> Scope: all VHS-related files across etl/, docs/, data/quality_reports/, notebooks/, scoring/, logs/  
> **No files were moved, deleted, or modified during this audit.**

---

## Categories

| Code | Meaning |
|------|---------|
| `KEEP_MAIN` | Needed directly in the clean final pipeline |
| `KEEP_AUDIT` | Evidence / traceability, not part of daily pipeline |
| `KEEP_MAINTENANCE` | Scripts that modify reference data — not normal execution |
| `ARCHIVE_VERSION` | Old V1/V2 logic kept for traceability |
| `ARCHIVE_EXPERIMENT` | Exploratory notebooks, comment analysis, intermediate outputs |
| `IGNORE_GIT` | Must not be committed (logs, pycache, generated artefacts) |
| `REVIEW_MANUALLY` | Purpose unclear — needs human decision |

---

## etl/mart/ — Scripts

| Current file | Category | Target location | Keep in Git? | Reason |
|---|---|---|---|---|
| `etl/mart/compute_vhs_v3_candidate.py` | **KEEP_MAIN** | `etl/mart/compute_vhs_v3_candidate.py` | ✅ Yes | Official V3 compute engine. Final corrected run `VHS_BALANCED_V3_CANDIDATE_20260703_181257`. IMMOBILISE=13, CRITIQUE=51, audit issues=0. |
| `etl/mart/compute_vhs.py` | **ARCHIVE_VERSION** | `etl/mart/archive/v1/compute_vhs_v1.py` | ✅ Yes (archive) | V1 engine. No WORN_STRONG. Superseded by V2 then V3. Kept for traceability. |
| `etl/mart/compute_vhs_v2.py` | **ARCHIVE_VERSION** | `etl/mart/archive/v2/compute_vhs_v2.py` | ✅ Yes (archive) | V2 engine. Introduced WORN_STRONG but had ambiguous mapping (PROPOSITION FAITE → BROKEN). Superseded by V3. |
| `etl/mart/audit_vhs_v1.py` | **ARCHIVE_VERSION** | `etl/mart/archive/v1/audit_vhs_v1.py` | ✅ Yes (archive) | V1 audit. Historical. Superseded by V2/V3 audits. |
| `etl/mart/audit_vhs_t1_criticality.py` | **KEEP_AUDIT** | `etl/mart/audits/audit_vhs_t1_criticality.py` | ✅ Yes | Audits T1 checkpoint classification. Still relevant: `mart.dim_checkpoint` is shared across all versions. |
| `etl/mart/audit_vhs_v2_severe_cases.py` | **ARCHIVE_VERSION** | `etl/mart/archive/v2/audit_vhs_v2_severe_cases.py` | ✅ Yes (archive) | V2 severe cases audit. Historical. No longer the reference run. |
| `etl/mart/audit_vhs_v3_immobilise_cases.py` | **KEEP_AUDIT** | `etl/mart/audits/audit_vhs_v3_immobilise_cases.py` | ✅ Yes | Identified the 25 IMMOBILISE cases in old V3 run. Proof of the investigation that led to the dim_checkpoint fix. |
| `etl/mart/audit_vhs_v3_immobilise_driver_labels.py` | **KEEP_AUDIT** | `etl/mart/audits/audit_vhs_v3_immobilise_driver_labels.py` | ✅ Yes | Resolved labels for the 5 IMMOBILISE driver checkpoints. Confirmed dim_checkpoint is the correct label source. |
| `etl/mart/update_dim_checkpoint_v3_immobilizing_flags.py` | **KEEP_MAINTENANCE** | `etl/mart/maintenance/update_dim_checkpoint_v3_immobilizing_flags.py` | ✅ Yes | Applied the business decision: 4 checkpoints set to `is_immobilizing=FALSE`. Idempotent. Must be kept for audit trail. |
| `etl/mart/compare_vhs_v3_candidate_before_after_immobilizing_fix.py` | **KEEP_AUDIT** | `etl/mart/audits/compare_vhs_v3_candidate_before_after_immobilizing_fix.py` | ✅ Yes | Validates that the fix produced the expected result: IMMOBILISE 25→13, 12× IMMOBILISE→DEGRADE, 0× IMMOBILISE→OK, all 8 checks passed. |

---

## etl/mart/__pycache__/ — Compiled bytecode

| Current file | Category | Target location | Keep in Git? | Reason |
|---|---|---|---|---|
| `etl/mart/__pycache__/compute_vhs.cpython-312.pyc` | **IGNORE_GIT** | — | ❌ No | Auto-generated. Already covered by `__pycache__/` in `.gitignore`. |
| `etl/mart/__pycache__/compute_vhs_v2.cpython-312.pyc` | **IGNORE_GIT** | — | ❌ No | Auto-generated. |
| `etl/mart/__pycache__/compute_vhs_v3_candidate.cpython-312.pyc` | **IGNORE_GIT** | — | ❌ No | Auto-generated. |
| `etl/mart/__pycache__/audit_vhs_v1.cpython-312.pyc` | **IGNORE_GIT** | — | ❌ No | Auto-generated. |
| `etl/mart/__pycache__/audit_vhs_t1_criticality.cpython-312.pyc` | **IGNORE_GIT** | — | ❌ No | Auto-generated. |
| `etl/mart/__pycache__/audit_vhs_v2_severe_cases.cpython-312.pyc` | **IGNORE_GIT** | — | ❌ No | Auto-generated. |
| `etl/mart/__pycache__/audit_vhs_v3_immobilise_cases.cpython-312.pyc` | **IGNORE_GIT** | — | ❌ No | Auto-generated. |

---

## scoring/ — Legacy

| Current file | Category | Target location | Keep in Git? | Reason |
|---|---|---|---|---|
| `scoring/compute_vhs.py` | **ARCHIVE_VERSION** | `etl/mart/archive/v1/compute_vhs_v1_scoring_copy.py` | ✅ Yes (archive) | Duplicate of V1 compute logic, placed in `scoring/` before the pipeline moved to `etl/mart/`. Kept only for historical completeness. |

---

## docs/ — Documentation

| Current file | Category | Target location | Keep in Git? | Reason |
|---|---|---|---|---|
| `docs/vhs/vhs_calculation_method.md` | **KEEP_MAIN** | `docs/vhs/vhs_calculation_method.md` | ✅ Yes | Complete V3 specification: 21 sections, statuses, mapping rules, penalty formulas, grade rules, hard caps. Version = VHS_BALANCED_V3_CANDIDATE. |
| `docs/diagrams/vhs_calculation_flow.mmd` | **KEEP_MAIN** | `docs/diagrams/vhs_calculation_flow.mmd` | ✅ Yes | Mermaid flowchart: full calculation from load → mapping → grade → decision → hard cap → DB write. |
| `docs/diagrams/vhs_mapping_rules.mmd` | **KEEP_MAIN** | `docs/diagrams/vhs_mapping_rules.mmd` | ✅ Yes | Mermaid diagram: `valeur_controle → observed_status` mapping for V3. |

---

## notebooks/ — Exploratory analysis

| Current file | Category | Target location | Keep in Git? | Reason |
|---|---|---|---|---|
| `notebooks/04_staffim_comment_analysis_for_vhs.ipynb` | **ARCHIVE_EXPERIMENT** | `notebooks/archive/04_staffim_comment_analysis_for_vhs.ipynb` | ❌ No | Exploratory. Full `notebooks/` already excluded by `.gitignore`. Contains NON section analysis and STAFFIM comment classification. Useful reference but not part of the pipeline. |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_by_checkpoint.csv` | **ARCHIVE_EXPERIMENT** | — | ❌ No | Notebook output written to wrong path (inside `notebooks/` instead of `data/`). Covered by `*.csv` in `.gitignore`. |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_profile_summary.csv` | **ARCHIVE_EXPERIMENT** | — | ❌ No | Same as above. |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_simple_cases.csv` | **ARCHIVE_EXPERIMENT** | — | ❌ No | Same as above. |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_critical_cases.csv` | **ARCHIVE_EXPERIMENT** | — | ❌ No | Same as above. |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_no_anomaly_cases.csv` | **ARCHIVE_EXPERIMENT** | — | ❌ No | Same as above. |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_with_strong_comments.csv` | **ARCHIVE_EXPERIMENT** | — | ❌ No | Same as above. |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_with_advisory_or_unclear_comments.csv` | **ARCHIVE_EXPERIMENT** | — | ❌ No | Same as above. |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_in_severe_cases.csv` | **ARCHIVE_EXPERIMENT** | — | ❌ No | Same as above. |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_hard_cap_triggers.csv` | **ARCHIVE_EXPERIMENT** | — | ❌ No | Same as above. |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_simulation_if_not_broken.csv` | **ARCHIVE_EXPERIMENT** | — | ❌ No | Same as above. |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/staffim_comment_analysis_summary.md` | **ARCHIVE_EXPERIMENT** | — | ❌ No | Duplicate of the main copy in `data/quality_reports/vhs/staffim_comment_analysis/`. Covered by `notebooks/` in `.gitignore`. |

---

## data/quality_reports/vhs/ — Root level

| Current file | Category | Target location | Keep in Git? | Reason |
|---|---|---|---|---|
| `data/quality_reports/vhs/dim_checkpoint_review.csv` | **REVIEW_MANUALLY** | — | ❓ Unclear | Origin unclear. Not produced by any identified script. Could be a manual review file or an intermediate export. Needs investigation before moving or deleting. |
| `data/quality_reports/vhs/vhs_business_rule_audit.csv` | **ARCHIVE_VERSION** | `data/quality_reports/vhs/archive/v1/vhs_business_rule_audit_v1.csv` | ❌ No (CSV excluded) | V1 business rule audit. Superseded by V2 and V3 versions. |
| `data/quality_reports/vhs/vhs_business_rule_audit_v2.csv` | **ARCHIVE_VERSION** | `data/quality_reports/vhs/archive/v2/vhs_business_rule_audit_v2.csv` | ❌ No (CSV excluded) | V2 business rule audit. Superseded by V3. |
| `data/quality_reports/vhs/vhs_v1_vs_v2_comparison.csv` | **ARCHIVE_VERSION** | `data/quality_reports/vhs/archive/v2/vhs_v1_vs_v2_comparison.csv` | ❌ No (CSV excluded) | V1 vs V2 per-inspection comparison. Historical. |
| `data/quality_reports/vhs/vhs_v1_vs_v2_summary.md` | **ARCHIVE_VERSION** | `data/quality_reports/vhs/archive/v2/vhs_v1_vs_v2_summary.md` | ✅ Yes (.md kept) | V1 vs V2 narrative summary. Historical traceability. |

---

## data/quality_reports/vhs/audit_vhs_v1/ — V1 reports

| Current file | Category | Target location | Keep in Git? | Reason |
|---|---|---|---|---|
| `audit_vhs_v1/vhs_audit_summary.md` | **ARCHIVE_VERSION** | `data/quality_reports/vhs/archive/v1/vhs_audit_summary.md` | ✅ Yes (.md kept) | V1 audit summary markdown. Historical. |
| `audit_vhs_v1/vhs_decision_distribution.csv` | **ARCHIVE_VERSION** | `data/quality_reports/vhs/archive/v1/` | ❌ No (CSV excluded) | V1 decision distribution. Historical. |
| `audit_vhs_v1/vhs_safety_grade_distribution.csv` | **ARCHIVE_VERSION** | `data/quality_reports/vhs/archive/v1/` | ❌ No | Historical. |
| `audit_vhs_v1/vhs_score_distribution.csv` | **ARCHIVE_VERSION** | `data/quality_reports/vhs/archive/v1/` | ❌ No | Historical. |
| `audit_vhs_v1/vhs_critical_cases_summary.csv` | **ARCHIVE_VERSION** | `data/quality_reports/vhs/archive/v1/` | ❌ No | Historical. |
| `audit_vhs_v1/vhs_critical_without_applied_cap.csv` | **ARCHIVE_VERSION** | `data/quality_reports/vhs/archive/v1/` | ❌ No | Historical. |
| `audit_vhs_v1/vhs_grade_d_triggers.csv` | **ARCHIVE_VERSION** | `data/quality_reports/vhs/archive/v1/` | ❌ No | Historical. |
| `audit_vhs_v1/vhs_top_penalty_checkpoints.csv` | **ARCHIVE_VERSION** | `data/quality_reports/vhs/archive/v1/` | ❌ No | Historical. |
| `audit_vhs_v1/vhs_high_severity_review_candidates.csv` | **ARCHIVE_VERSION** | `data/quality_reports/vhs/archive/v1/` | ❌ No | Historical. |
| `audit_vhs_v1/vhs_t1_status_distribution.csv` | **ARCHIVE_VERSION** | `data/quality_reports/vhs/archive/v1/` | ❌ No | Historical. |

---

## data/quality_reports/vhs/audit_t1_criticality/ — T1 criticality

| Current file | Category | Target location | Keep in Git? | Reason |
|---|---|---|---|---|
| `audit_t1_criticality/t1_audit_summary.md` | **KEEP_AUDIT** | `data/quality_reports/vhs/audit_t1_criticality/t1_audit_summary.md` | ✅ Yes | T1 criticality audit summary. `mart.dim_checkpoint` is shared — this analysis is still valid for V3. |
| `audit_t1_criticality/t1_criticality_by_checkpoint.csv` | **KEEP_AUDIT** | unchanged | ❌ No (CSV excluded) | T1 per-checkpoint criticality breakdown. |
| `audit_t1_criticality/t1_value_control_distribution.csv` | **KEEP_AUDIT** | unchanged | ❌ No | Distribution of `valeur_controle` for T1 checkpoints. |
| `audit_t1_criticality/t1_critical_comments_sample.csv` | **KEEP_AUDIT** | unchanged | ❌ No | Sample of comments on critical T1 checkpoints. |
| `audit_t1_criticality/t1_broken_to_grade_d_link.csv` | **KEEP_AUDIT** | unchanged | ❌ No | Link between BROKEN T1 and Grade D decisions. |
| `audit_t1_criticality/t1_possible_overcritical_cases.csv` | **KEEP_AUDIT** | unchanged | ❌ No | Checkpoints that may be over-classified as critical. |

---

## data/quality_reports/vhs/audit_vhs_v2_severe_cases/ — V2 severe cases

| Current file | Category | Target location | Keep in Git? | Reason |
|---|---|---|---|---|
| `audit_vhs_v2_severe_cases/v2_severe_cases_audit_summary.md` | **ARCHIVE_VERSION** | `data/quality_reports/vhs/archive/v2/v2_severe_cases_audit_summary.md` | ✅ Yes (.md kept) | V2 severe cases summary. Historical. |
| `audit_vhs_v2_severe_cases/v2_severe_cases_summary.csv` | **ARCHIVE_VERSION** | `archive/v2/` | ❌ No | Historical. |
| `audit_vhs_v2_severe_cases/v2_severe_penalty_details.csv` | **ARCHIVE_VERSION** | `archive/v2/` | ❌ No | Historical. |
| `audit_vhs_v2_severe_cases/v2_grade_d_drivers.csv` | **ARCHIVE_VERSION** | `archive/v2/` | ❌ No | Historical. |
| `audit_vhs_v2_severe_cases/v2_immobilized_driver.csv` | **ARCHIVE_VERSION** | `archive/v2/` | ❌ No | Historical — V2 had only 1 IMMOBILISE case. |
| `audit_vhs_v2_severe_cases/v2_critical_case_explanations.csv` | **ARCHIVE_VERSION** | `archive/v2/` | ❌ No | Historical. |
| `audit_vhs_v2_severe_cases/v2_worn_strong_effect_on_severe_cases.csv` | **ARCHIVE_VERSION** | `archive/v2/` | ❌ No | Historical. |

---

## data/quality_reports/vhs/staffim_comment_analysis/ — STAFFIM analysis

| Current file | Category | Target location | Keep in Git? | Reason |
|---|---|---|---|---|
| `staffim_comment_analysis/staffim_comment_analysis_summary.md` | **ARCHIVE_EXPERIMENT** | `data/quality_reports/vhs/archive/v3_experiments/staffim_comment_analysis_summary.md` | ✅ Yes (.md kept) | Exploratory STAFFIM comment analysis. Informed V3 design but not part of the pipeline. |
| `staffim_comment_analysis/staffim_comment_profile.csv` | **ARCHIVE_EXPERIMENT** | `archive/v3_experiments/` | ❌ No | Exploratory CSV output. |
| `staffim_comment_analysis/comments_with_ok_value.csv` | **ARCHIVE_EXPERIMENT** | `archive/v3_experiments/` | ❌ No | Exploratory. |
| `staffim_comment_analysis/proposition_faite_comment_context.csv` | **ARCHIVE_EXPERIMENT** | `archive/v3_experiments/` | ❌ No | Exploratory. |
| `staffim_comment_analysis/intervention_conseillee_comment_context.csv` | **ARCHIVE_EXPERIMENT** | `archive/v3_experiments/` | ❌ No | Exploratory. |
| `staffim_comment_analysis/critique_with_advisory_comments.csv` | **ARCHIVE_EXPERIMENT** | `archive/v3_experiments/` | ❌ No | Exploratory. |
| `staffim_comment_analysis/critical_comment_evidence.csv` | **ARCHIVE_EXPERIMENT** | `archive/v3_experiments/` | ❌ No | Exploratory. |
| `staffim_comment_analysis/staffim_comment_examples.csv` | **ARCHIVE_EXPERIMENT** | `archive/v3_experiments/` | ❌ No | Exploratory. |
| `staffim_comment_analysis/staffim_comment_crosstabs.csv` | **ARCHIVE_EXPERIMENT** | `archive/v3_experiments/` | ❌ No | Exploratory. |

---

## data/quality_reports/vhs/vhs_balanced_v3_candidate/ — Final V3 run reports

### Root V3 outputs

| Current file | Category | Target location | Keep in Git? | Reason |
|---|---|---|---|---|
| `vhs_balanced_v3_candidate/vhs_v3_audit_summary.md` | **KEEP_MAIN** | `data/quality_reports/vhs/final/vhs_v3_audit_summary.md` | ✅ Yes | Key final summary of the corrected V3 run. IMMOBILISE=13, CRITIQUE=51, Grade D=51, audit issues=0. |
| `vhs_balanced_v3_candidate/vhs_v3_distribution_by_decision.csv` | **KEEP_AUDIT** | `data/quality_reports/vhs/final/` | ❌ No (CSV excluded) | Final V3 decision distribution. Regenerable from DB. |
| `vhs_balanced_v3_candidate/vhs_v3_distribution_by_grade.csv` | **KEEP_AUDIT** | `data/quality_reports/vhs/final/` | ❌ No | Same. |
| `vhs_balanced_v3_candidate/vhs_v3_observed_status_distribution.csv` | **KEEP_AUDIT** | `data/quality_reports/vhs/final/` | ❌ No | Same. |
| `vhs_balanced_v3_candidate/vhs_v3_penalty_by_tier.csv` | **KEEP_AUDIT** | `data/quality_reports/vhs/final/` | ❌ No | Same. |
| `vhs_balanced_v3_candidate/vhs_v3_ambiguous_values_mapping.csv` | **KEEP_AUDIT** | `data/quality_reports/vhs/final/` | ❌ No | Contract proof: PROPOSITION FAITE→BROKEN=0, NON→BROKEN=0. Regenerable. |
| `vhs_balanced_v3_candidate/vhs_v2_vs_v3_comparison.csv` | **KEEP_AUDIT** | `data/quality_reports/vhs/final/` | ❌ No | V2 vs V3 per-inspection comparison. Regenerable. |
| `vhs_balanced_v3_candidate/vhs_v2_vs_v3_comparison_summary.md` | **KEEP_AUDIT** | `data/quality_reports/vhs/final/vhs_v2_vs_v3_comparison_summary.md` | ✅ Yes | V2 vs V3 narrative markdown. Kept in Git. |

### dim_checkpoint_update/

| Current file | Category | Target location | Keep in Git? | Reason |
|---|---|---|---|---|
| `dim_checkpoint_update/dim_checkpoint_immobilizing_update_summary.md` | **KEEP_MAINTENANCE** | `data/quality_reports/vhs/final/dim_checkpoint_immobilizing_update_summary.md` | ✅ Yes | Documents the `is_immobilizing` flag change: which 4 checkpoints were updated, before/after state, validation result. Critical audit trail. |
| `dim_checkpoint_update/dim_checkpoint_immobilizing_before.csv` | **KEEP_MAINTENANCE** | `data/quality_reports/vhs/final/` | ❌ No (CSV excluded) | Before state of the 5 driver checkpoints. Useful for comparison but regenerable. |
| `dim_checkpoint_update/dim_checkpoint_immobilizing_after.csv` | **KEEP_MAINTENANCE** | `data/quality_reports/vhs/final/` | ❌ No | After state of the 5 driver checkpoints. |

### immobilise_audit/

| Current file | Category | Target location | Keep in Git? | Reason |
|---|---|---|---|---|
| `immobilise_audit/v3_immobilise_audit_summary.md` | **KEEP_AUDIT** | `data/quality_reports/vhs/archive/v3_experiments/immobilise_audit/v3_immobilise_audit_summary.md` | ✅ Yes | Summary of the initial 25-IMMOBILISE investigation (old run, before fix). |
| `immobilise_audit/v3_immobilise_driver_label_summary.md` | **KEEP_AUDIT** | same folder | ✅ Yes | Label resolution summary for the 5 driver checkpoints. |
| `immobilise_audit/v3_immobilise_cases.csv` | **KEEP_AUDIT** | same folder | ❌ No | 25 IMMOBILISE inspections from old run. Excluded by `.gitignore`. |
| `immobilise_audit/v3_immobilise_drivers.csv` | **KEEP_AUDIT** | same folder | ❌ No | 29 driver rows. |
| `immobilise_audit/v3_immobilise_driver_distribution.csv` | **KEEP_AUDIT** | same folder | ❌ No | Distribution of 5 driver checkpoints. |
| `immobilise_audit/v3_immobilise_by_previous_decision.csv` | **KEEP_AUDIT** | same folder | ❌ No | V2 decisions for the 25 IMMOBILISE inspections. |
| `immobilise_audit/v2_vs_v3_immobilise_transition.csv` | **KEEP_AUDIT** | same folder | ❌ No | Score transition per inspection V2→V3. |
| `immobilise_audit/v3_immobilise_non_explicit_defect_check.csv` | **KEEP_AUDIT** | same folder | ❌ No | Confirms 0 ambiguous triggers. |
| `immobilise_audit/v3_immobilise_driver_labels.csv` | **KEEP_AUDIT** | same folder | ❌ No | 29 driver rows with resolved labels. |
| `immobilise_audit/v3_immobilise_driver_label_distribution.csv` | **KEEP_AUDIT** | same folder | ❌ No | 5 checkpoints with label + zone + scores. |

### immobilise_fix_comparison/

| Current file | Category | Target location | Keep in Git? | Reason |
|---|---|---|---|---|
| `immobilise_fix_comparison/v3_immobilise_fix_summary.md` | **KEEP_AUDIT** | `data/quality_reports/vhs/final/v3_immobilise_fix_summary.md` | ✅ Yes | Key proof of fix: 8 validation checks all passed. IMMOBILISE 25→13. 12× IMMOBILISE→DEGRADE. Promoted to `final/`. |
| `immobilise_fix_comparison/v3_before_after_decision_distribution.csv` | **KEEP_AUDIT** | `data/quality_reports/vhs/final/` | ❌ No | Before/after decision counts. Regenerable. |
| `immobilise_fix_comparison/v3_before_after_grade_distribution.csv` | **KEEP_AUDIT** | `data/quality_reports/vhs/final/` | ❌ No | Same. |
| `immobilise_fix_comparison/v3_before_after_score_stats.csv` | **KEEP_AUDIT** | `data/quality_reports/vhs/final/` | ❌ No | Same. |
| `immobilise_fix_comparison/v3_before_after_decision_transitions.csv` | **KEEP_AUDIT** | `data/quality_reports/vhs/final/` | ❌ No | Same. |
| `immobilise_fix_comparison/v3_immobilise_fixed_cases.csv` | **KEEP_AUDIT** | `data/quality_reports/vhs/final/` | ❌ No | Per-inspection old/new decision for the 25 formerly-IMMOBILISE cases. |

---

## logs/ — Log files

| Current file | Category | Target location | Keep in Git? | Reason |
|---|---|---|---|---|
| `logs/load_dwh_compute_vhs.log` | **IGNORE_GIT** | — | ❌ No | Runtime log. `logs/` already excluded by `.gitignore`. |
| `logs/load_dwh_compute_vhs_v2.log` | **IGNORE_GIT** | — | ❌ No | Same. |
| `logs/load_dwh_compute_vhs_v3_candidate.log` | **IGNORE_GIT** | — | ❌ No | Same. |
| `logs/load_dwh_audit_vhs_v1.log` | **IGNORE_GIT** | — | ❌ No | Same. |
| `logs/load_dwh_audit_vhs_v2_severe.log` | **IGNORE_GIT** | — | ❌ No | Same. |
| `logs/load_dwh_audit_vhs_v3_immobilise_cases.log` | **IGNORE_GIT** | — | ❌ No | Same. |
| `logs/audit_vhs_v3_immobilise_driver_labels_*.log` | **IGNORE_GIT** | — | ❌ No | Same. |
| `logs/update_dim_checkpoint_v3_immobilizing_flags_*.log` | **IGNORE_GIT** | — | ❌ No | Same. |
| `logs/compare_vhs_v3_candidate_before_after_*.log` | **IGNORE_GIT** | — | ❌ No | Same. |

---

## Summary Counts

| Category | Count |
|----------|-------|
| **KEEP_MAIN** | **5** |
| **KEEP_AUDIT** | **33** |
| **KEEP_MAINTENANCE** | **4** |
| **ARCHIVE_VERSION** | **26** |
| **ARCHIVE_EXPERIMENT** | **21** |
| **IGNORE_GIT** | **16** |
| **REVIEW_MANUALLY** | **1** |
| **Total VHS files audited** | **106** |

---

> **Do not delete yet. Review this matrix first. After approval, run a cleanup script to copy/move files safely.**
