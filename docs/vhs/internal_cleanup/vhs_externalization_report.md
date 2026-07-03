# VHS Archive Externalization Report

> Generated  : 2026-07-03 19:28 UTC  
> Script     : `scripts/project_cleanup/externalize_vhs_archives_to_archivevhs.py`  
> Destination: `C:\Users\wiem\Downloads\Projet PFE\ArchiveVHS\project_internal_archives_removed_20260703_192817`  

---

## Safety Statements

- **VHS audit and archive material was externalized to ArchiveVHS.**
- **compute_vhs_v3_candidate.py remains the only active VHS compute script inside IRIS_AUTO_FRAUD.**
- **No database operation was performed.**
- No wildcard deletion was used.
- No business logic was modified.
- Copy verified before any removal.

---

## Guard Validation

| Guard | Result |
|-------|--------|
| ArchiveVHS folder exists | OK |
| cleanup_remove_report exists and contains ALL CHECKS PASSED | OK |
| compute_vhs_v3_candidate.py intact | OK |
| load_dim_checkpoint.py intact | OK |
| vhs_calculation_method.md intact | OK |
| diagrams intact | OK |
| data/quality_reports/vhs/final/ intact | OK |

---

## Folders Copied to ArchiveVHS

External target: `project_internal_archives_removed_20260703_192817/`

| Source (project) | Destination (ArchiveVHS) | Label | Status | Files |
|------------------|--------------------------|-------|--------|-------|
| `etl/mart/audits` | `etl_mart_audits` | V3 audit scripts | OK | 4 |
| `etl/mart/maintenance` | `etl_mart_maintenance` | maintenance scripts | OK | 1 |
| `etl/mart/archive` | `etl_mart_archive` | V1/V2 compute archives | OK | 5 |
| `data/quality_reports/vhs/archive` | `quality_reports_archive` | VHS report archive | OK | 6 |
| `data/quality_reports/vhs/audit_t1_criticality` | `quality_reports_audits/audit_t1_criticality` | T1 criticality audit reports | OK | 6 |
| `data/quality_reports/vhs/vhs_balanced_v3_candidate` | `quality_reports_experiments/vhs_balanced_v3_candidate` | V3 candidate run reports | OK | 27 |
| `data/quality_reports/vhs/staffim_comment_analysis` | `quality_reports_experiments/staffim_comment_analysis` | STAFFIM analysis reports | OK | 9 |
| `data/quality_reports/vhs/audit_vhs_v1` | `quality_reports_experiments/audit_vhs_v1` | V1 audit reports | OK | 10 |
| `data/quality_reports/vhs/audit_vhs_v2_severe_cases` | `quality_reports_experiments/audit_vhs_v2_severe_cases` | V2 severe cases audit reports | OK | 7 |
| `scripts/project_cleanup` | `cleanup_scripts` | project cleanup scripts | OK | 4 |

---

## Folders Removed from Project

| Folder | Result |
|--------|--------|
| `etl/mart/audits` | REMOVED |
| `etl/mart/maintenance` | REMOVED |
| `etl/mart/archive` | REMOVED |
| `data/quality_reports/vhs/archive` | REMOVED |
| `data/quality_reports/vhs/audit_t1_criticality` | REMOVED |
| `data/quality_reports/vhs/vhs_balanced_v3_candidate` | REMOVED |
| `data/quality_reports/vhs/staffim_comment_analysis` | REMOVED |
| `data/quality_reports/vhs/audit_vhs_v1` | REMOVED |
| `data/quality_reports/vhs/audit_vhs_v2_severe_cases` | REMOVED |
| `scripts/project_cleanup` | REMOVED |

---

## Folders Intentionally Kept in Project

| Path | Reason |
|------|--------|
| `etl/mart/compute_vhs_v3_candidate.py` | Official active VHS compute script |
| `etl/mart/load_dim_checkpoint.py` | Active ETL — not a VHS archive |
| `etl/mart/__init__.py` | Python package init |
| `docs/vhs/` | VHS documentation and cleanup audit trail |
| `docs/diagrams/` | Technical diagrams |
| `data/quality_reports/vhs/final/` | Final V3 validated reports |
| `data/quality_reports/vhs/dim_checkpoint_review.csv` | Pending manual review |

---

## Post-Remove Verification

| File/Folder | Check | Result |
|-------------|-------|--------|
| `etl/mart/compute_vhs_v3_candidate.py` | must exist | OK |
| `etl/mart/load_dim_checkpoint.py` | must exist | OK |
| `etl/mart/__init__.py` | must exist | OK |
| `docs/vhs/vhs_calculation_method.md` | must exist | OK |
| `docs/vhs/vhs_cleanup_copy_report.md` | must exist | OK |
| `docs/vhs/vhs_cleanup_remove_report.md` | must exist | OK |
| `docs/diagrams/vhs_calculation_flow.mmd` | must exist | OK |
| `docs/diagrams/vhs_mapping_rules.mmd` | must exist | OK |
| `data/quality_reports/vhs/final` | must exist | OK |
| `data/quality_reports/vhs/dim_checkpoint_review.csv` | must exist | OK |
| `etl/mart/audits` | must be gone | OK |
| `etl/mart/maintenance` | must be gone | OK |
| `etl/mart/archive` | must be gone | OK |
| `data/quality_reports/vhs/archive` | must be gone | OK |
| `data/quality_reports/vhs/audit_t1_criticality` | must be gone | OK |
| `data/quality_reports/vhs/vhs_balanced_v3_candidate` | must be gone | OK |
| `data/quality_reports/vhs/staffim_comment_analysis` | must be gone | OK |
| `data/quality_reports/vhs/audit_vhs_v1` | must be gone | OK |
| `data/quality_reports/vhs/audit_vhs_v2_severe_cases` | must be gone | OK |

---

## Syntax Checks

| File | Result |
|------|--------|
| `etl/mart/compute_vhs_v3_candidate.py` | OK |
| `etl/mart/load_dim_checkpoint.py` | OK |

---

## Final Result: **ALL CHECKS PASSED**

> **Recommendation:** VHS archive externalization completed safely.
> IRIS_AUTO_FRAUD now contains only the active VHS compute script,
> final documentation, and final reports.
> Keep ArchiveVHS until the end of the PFE.