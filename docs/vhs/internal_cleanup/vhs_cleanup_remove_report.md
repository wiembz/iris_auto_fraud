# VHS Cleanup — Remove Superseded Originals

> Generated : 2026-07-03 18:52 UTC  
> Script    : `scripts/project_cleanup/remove_vhs_superseded_originals.py`  
> Backup    : `C:\Users\wiem\Downloads\Projet PFE\ArchiveVHS\backup_before_delete_20260703_184748`  

---

## Guard Validation

| Check | Result |
|-------|--------|
| Cleanup copy report exists | OK |
| Copy report contains ALL CHECKS PASSED | OK |
| Copy report contains no-delete statement | OK |
| ArchiveVHS backup folder exists | OK |
| backup_manifest.md contains ALL CHECKS PASSED | OK |
| backup_manifest.md contains compute script statement | OK |
| compute_vhs_v3_candidate.py intact | OK |
| No NEVER_DELETE files in deletion list | OK |
| **Guard validation overall** | **PASSED** |

---

## Files Deleted

| File | Status |
|------|--------|
| `etl/mart/compute_vhs.py` | DELETED |
| `etl/mart/compute_vhs_v2.py` | DELETED |
| `etl/mart/audit_vhs_v1.py` | DELETED |
| `etl/mart/audit_vhs_v2_severe_cases.py` | DELETED |
| `etl/mart/audit_vhs_t1_criticality.py` | DELETED |
| `etl/mart/audit_vhs_v3_immobilise_cases.py` | DELETED |
| `etl/mart/audit_vhs_v3_immobilise_driver_labels.py` | DELETED |
| `etl/mart/compare_vhs_v3_candidate_before_after_immobilizing_fix.py` | DELETED |
| `etl/mart/update_dim_checkpoint_v3_immobilizing_flags.py` | DELETED |
| `scoring/compute_vhs.py` | DELETED |

---

## Files Intentionally Kept

| File | Reason |
|------|--------|
| `etl/mart/compute_vhs_v3_candidate.py` | Official production compute script — never a removable original |
| `etl/mart/load_dim_checkpoint.py` | Active ETL script — not VHS-specific |
| `etl/mart/__init__.py` | Package init — required |
| `etl/mart/audits/*` | New target location — kept as evidence |
| `etl/mart/maintenance/*` | New target location — kept |
| `etl/mart/archive/*` | New target location — kept for traceability |
| `docs/vhs/*` | Documentation and audit trail |
| `docs/diagrams/*` | Technical diagrams |
| `data/quality_reports/vhs/final/*` | Final V3 reports |
| `data/quality_reports/vhs/dim_checkpoint_review.csv` | REVIEW_MANUALLY — kept pending investigation |

---

## Post-Delete Verification

| File | Check | Result |
|------|-------|--------|
| `etl/mart/compute_vhs.py` | original gone | OK |
| `etl/mart/compute_vhs_v2.py` | original gone | OK |
| `etl/mart/audit_vhs_v1.py` | original gone | OK |
| `etl/mart/audit_vhs_v2_severe_cases.py` | original gone | OK |
| `etl/mart/audit_vhs_t1_criticality.py` | original gone | OK |
| `etl/mart/audit_vhs_v3_immobilise_cases.py` | original gone | OK |
| `etl/mart/audit_vhs_v3_immobilise_driver_labels.py` | original gone | OK |
| `etl/mart/compare_vhs_v3_candidate_before_after_immobilizing_fix.py` | original gone | OK |
| `etl/mart/update_dim_checkpoint_v3_immobilizing_flags.py` | original gone | OK |
| `scoring/compute_vhs.py` | original gone | OK |
| `etl/mart/archive/v1/compute_vhs_v1.py` | copy exists | OK |
| `etl/mart/archive/v2/compute_vhs_v2.py` | copy exists | OK |
| `etl/mart/archive/v1/audit_vhs_v1.py` | copy exists | OK |
| `etl/mart/archive/v2/audit_vhs_v2_severe_cases.py` | copy exists | OK |
| `etl/mart/audits/audit_vhs_t1_criticality.py` | copy exists | OK |
| `etl/mart/audits/audit_vhs_v3_immobilise_cases.py` | copy exists | OK |
| `etl/mart/audits/audit_vhs_v3_immobilise_driver_labels.py` | copy exists | OK |
| `etl/mart/audits/compare_vhs_v3_candidate_before_after_immobilizing_fix.py` | copy exists | OK |
| `etl/mart/maintenance/update_dim_checkpoint_v3_immobilizing_flags.py` | copy exists | OK |
| `etl/mart/archive/v1/compute_vhs_v1_scoring_copy.py` | copy exists | OK |
| `etl/mart/compute_vhs_v3_candidate.py` | structure intact | OK |
| `etl/mart/audits/audit_vhs_t1_criticality.py` | structure intact | OK |
| `etl/mart/audits/audit_vhs_v3_immobilise_cases.py` | structure intact | OK |
| `etl/mart/audits/audit_vhs_v3_immobilise_driver_labels.py` | structure intact | OK |
| `etl/mart/audits/compare_vhs_v3_candidate_before_after_immobilizing_fix.py` | structure intact | OK |
| `etl/mart/maintenance/update_dim_checkpoint_v3_immobilizing_flags.py` | structure intact | OK |
| `etl/mart/archive/v1/compute_vhs_v1.py` | structure intact | OK |
| `etl/mart/archive/v1/audit_vhs_v1.py` | structure intact | OK |
| `etl/mart/archive/v1/compute_vhs_v1_scoring_copy.py` | structure intact | OK |
| `etl/mart/archive/v2/compute_vhs_v2.py` | structure intact | OK |
| `etl/mart/archive/v2/audit_vhs_v2_severe_cases.py` | structure intact | OK |

---

## Syntax Checks

| File | Result |
|------|--------|
| `etl/mart/compute_vhs_v3_candidate.py` | OK |
| `etl/mart/audits/audit_vhs_t1_criticality.py` | OK |
| `etl/mart/audits/audit_vhs_v3_immobilise_cases.py` | OK |
| `etl/mart/audits/audit_vhs_v3_immobilise_driver_labels.py` | OK |
| `etl/mart/audits/compare_vhs_v3_candidate_before_after_immobilizing_fix.py` | OK |
| `etl/mart/maintenance/update_dim_checkpoint_v3_immobilizing_flags.py` | OK |
| `etl/mart/archive/v1/compute_vhs_v1.py` | OK |
| `etl/mart/archive/v2/compute_vhs_v2.py` | OK |

---

## Safety Statements

- **Only explicitly listed superseded originals were deleted.**
- **No database operation was performed.**
- **compute_vhs_v3_candidate.py remains the official active VHS script.**
- No wildcard or folder deletion was used.
- No CSV files were deleted.
- No docs or diagrams were modified.

---

## Final Result

**ALL CHECKS PASSED**

> **Recommendation:** Cleanup-remove completed safely. The VHS project structure is now clean. Keep ArchiveVHS backup until the end of the PFE.