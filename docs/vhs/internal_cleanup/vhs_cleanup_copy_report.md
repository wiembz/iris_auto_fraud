# VHS Cleanup — Copy-Only Report

> Generated: 2026-07-03 18:38 UTC  
> Script: `scripts/project_cleanup/apply_vhs_cleanup_copy_only.py`  
> **No files were deleted or moved. This was copy-only cleanup.**

---

## Summary

| Metric | Value |
|--------|-------|
| Folders created | 10 |
| Files copied OK | 20 / 20 |
| Files verified at target | 20 / 20 |
| Syntax checks passed | 10 / 10 |
| Missing source files | 0 |
| Failed copies | 0 |
| Compute script intact | ✅ Yes |
| **Overall result** | **✅ ALL CHECKS PASSED** |

---

## Folders Created

- `etl\mart\audits`
- `etl\mart\maintenance`
- `etl\mart\archive\v1`
- `etl\mart\archive\v2`
- `data\quality_reports\vhs\final`
- `data\quality_reports\vhs\archive\v1`
- `data\quality_reports\vhs\archive\v2`
- `data\quality_reports\vhs\archive\v3_experiments`
- `data\quality_reports\vhs\archive\v3_experiments\immobilise_audit`
- `data\quality_reports\vhs\archive\v3_experiments\staffim_comment_analysis`

---

## Files Copied

| Source | Target | Verified |
|--------|--------|----------|
| `etl/mart/audit_vhs_t1_criticality.py` | `etl/mart/audits/audit_vhs_t1_criticality.py` | ✅ |
| `etl/mart/audit_vhs_v3_immobilise_cases.py` | `etl/mart/audits/audit_vhs_v3_immobilise_cases.py` | ✅ |
| `etl/mart/audit_vhs_v3_immobilise_driver_labels.py` | `etl/mart/audits/audit_vhs_v3_immobilise_driver_labels.py` | ✅ |
| `etl/mart/compare_vhs_v3_candidate_before_after_immobilizing_fix.py` | `etl/mart/audits/compare_vhs_v3_candidate_before_after_immobilizing_fix.py` | ✅ |
| `etl/mart/update_dim_checkpoint_v3_immobilizing_flags.py` | `etl/mart/maintenance/update_dim_checkpoint_v3_immobilizing_flags.py` | ✅ |
| `etl/mart/compute_vhs.py` | `etl/mart/archive/v1/compute_vhs_v1.py` | ✅ |
| `etl/mart/audit_vhs_v1.py` | `etl/mart/archive/v1/audit_vhs_v1.py` | ✅ |
| `scoring/compute_vhs.py` | `etl/mart/archive/v1/compute_vhs_v1_scoring_copy.py` | ✅ |
| `etl/mart/compute_vhs_v2.py` | `etl/mart/archive/v2/compute_vhs_v2.py` | ✅ |
| `etl/mart/audit_vhs_v2_severe_cases.py` | `etl/mart/archive/v2/audit_vhs_v2_severe_cases.py` | ✅ |
| `data/quality_reports/vhs/vhs_balanced_v3_candidate/vhs_v3_audit_summary.md` | `data/quality_reports/vhs/final/vhs_v3_audit_summary.md` | ✅ |
| `data/quality_reports/vhs/vhs_balanced_v3_candidate/vhs_v2_vs_v3_comparison_summary.md` | `data/quality_reports/vhs/final/vhs_v2_vs_v3_comparison_summary.md` | ✅ |
| `data/quality_reports/vhs/vhs_balanced_v3_candidate/dim_checkpoint_update/dim_checkpoint_immobilizing_update_summary.md` | `data/quality_reports/vhs/final/dim_checkpoint_immobilizing_update_summary.md` | ✅ |
| `data/quality_reports/vhs/vhs_balanced_v3_candidate/immobilise_fix_comparison/v3_immobilise_fix_summary.md` | `data/quality_reports/vhs/final/v3_immobilise_fix_summary.md` | ✅ |
| `data/quality_reports/vhs/audit_vhs_v1/vhs_audit_summary.md` | `data/quality_reports/vhs/archive/v1/vhs_audit_summary.md` | ✅ |
| `data/quality_reports/vhs/vhs_v1_vs_v2_summary.md` | `data/quality_reports/vhs/archive/v2/vhs_v1_vs_v2_summary.md` | ✅ |
| `data/quality_reports/vhs/audit_vhs_v2_severe_cases/v2_severe_cases_audit_summary.md` | `data/quality_reports/vhs/archive/v2/v2_severe_cases_audit_summary.md` | ✅ |
| `data/quality_reports/vhs/staffim_comment_analysis/staffim_comment_analysis_summary.md` | `data/quality_reports/vhs/archive/v3_experiments/staffim_comment_analysis_summary.md` | ✅ |
| `data/quality_reports/vhs/vhs_balanced_v3_candidate/immobilise_audit/v3_immobilise_audit_summary.md` | `data/quality_reports/vhs/archive/v3_experiments/immobilise_audit/v3_immobilise_audit_summary.md` | ✅ |
| `data/quality_reports/vhs/vhs_balanced_v3_candidate/immobilise_audit/v3_immobilise_driver_label_summary.md` | `data/quality_reports/vhs/archive/v3_experiments/immobilise_audit/v3_immobilise_driver_label_summary.md` | ✅ |

---

## Syntax / Import Check

All Python copies are checked for syntax validity using `py_compile`.
The original scripts are NOT imported or executed.

| File | Result | Note |
|------|--------|------|
| `etl/mart/audits/audit_vhs_t1_criticality.py` | ✅ OK |  |
| `etl/mart/audits/audit_vhs_v3_immobilise_cases.py` | ✅ OK |  |
| `etl/mart/audits/audit_vhs_v3_immobilise_driver_labels.py` | ✅ OK |  |
| `etl/mart/audits/compare_vhs_v3_candidate_before_after_immobilizing_fix.py` | ✅ OK |  |
| `etl/mart/maintenance/update_dim_checkpoint_v3_immobilizing_flags.py` | ✅ OK |  |
| `etl/mart/archive/v1/compute_vhs_v1.py` | ✅ OK |  |
| `etl/mart/archive/v1/audit_vhs_v1.py` | ✅ OK |  |
| `etl/mart/archive/v1/compute_vhs_v1_scoring_copy.py` | ✅ OK |  |
| `etl/mart/archive/v2/compute_vhs_v2.py` | ✅ OK |  |
| `etl/mart/archive/v2/audit_vhs_v2_severe_cases.py` | ✅ OK |  |

---

## Guard — Official Compute Script

| File | Status |
|------|--------|
| `etl/mart/compute_vhs_v3_candidate.py` | ✅ Present at original location |

---

## CSV Files

CSV files are **not copied** in this step.
They are excluded from Git by `.gitignore` (pattern: `*.csv`).
All CSVs are regenerable by re-running the relevant scripts against the database.
If CSV copies are needed for archival, handle in a separate dedicated step.

---

## Files Requiring Manual Review

| File | Reason | Suggested Action |
|------|--------|-----------------|
| `data/quality_reports/vhs/dim_checkpoint_review.csv` | Not produced by any identified VHS script — could be a manual DB export or early draft | Open the file, check columns and row count. If it is a valid checkpoint export, move to `archive/v1/`. If outdated and unused, delete after confirming no script depends on it. |

---

## Next Steps

1. Review this report and confirm all checks passed.
2. Open the copied files at their new locations to spot-check content.
3. Investigate any failed or missing items before proceeding.
4. When satisfied, run the **explicit deletion step** (a separate script) to remove
   the original `etl/mart/*.py` files that have been superseded.
   That step requires explicit approval and is NOT part of this script.

> **Recommendation:** Review `docs/vhs/vhs_cleanup_copy_report.md`. If all checks
> passed, the project now has a clean copied structure. Do not delete old files yet.
> Run a second explicit cleanup-remove step only after manual approval.