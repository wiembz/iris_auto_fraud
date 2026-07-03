# VHS Cleanup Plan

> Generated: 2026-07-03  
> Reference: `docs/vhs/vhs_file_decision_matrix.md`  
> **No files were moved or deleted during the creation of this plan.**  
> All operations below are proposals only. Execute only after review and approval.

---

## Current situation

The VHS development went through 3 versions plus multiple audit cycles.
All files currently live at the same level inside `etl/mart/`, which mixes
production code, old versions, audit scripts, and maintenance scripts.
Report outputs are scattered across several nested folders under
`data/quality_reports/vhs/` with no clear separation between historical
data, active V3 outputs, and experiment artefacts.

**Final validated state:**
- Official compute script: `etl/mart/compute_vhs_v3_candidate.py`
- Final run: `VHS_BALANCED_V3_CANDIDATE_20260703_181257`
- Distribution: OK=89 / DEGRADE=133 / IMMOBILISE=13 / CRITIQUE=51
- Audit issues: 0 — PROPOSITION FAITE→BROKEN=0 — NON→BROKEN=0
- dim_checkpoint fix applied and validated (4 rows updated, all 8 checks passed)

---

## 1. Final files to keep in main project

These files are part of the clean production structure and must remain
accessible at the top level (no deep nesting).

### Scripts

```
etl/mart/compute_vhs_v3_candidate.py           ← production engine
```

### Documentation

```
docs/vhs/vhs_calculation_method.md            ← V3 full specification
docs/vhs/vhs_file_decision_matrix.md          ← this audit (auto-generated)
docs/vhs/vhs_cleanup_plan.md                  ← this plan (auto-generated)
docs/diagrams/vhs_calculation_flow.mmd        ← full calculation flowchart
docs/diagrams/vhs_mapping_rules.mmd           ← value→status mapping diagram
```

### Key reports (markdown only — CSVs excluded by .gitignore)

```
data/quality_reports/vhs/final/
  vhs_v3_audit_summary.md                     ← final run summary
  vhs_v2_vs_v3_comparison_summary.md          ← V2→V3 narrative
  dim_checkpoint_immobilizing_update_summary.md  ← dim_checkpoint change log
  v3_immobilise_fix_summary.md               ← fix validation (8 checks passed)
```

---

## 2. Files to move to etl/mart/audits/

Read-only audit scripts that proved specific decisions during V3 development.
Not part of normal execution but must be kept as evidence.

```
etl/mart/audits/
  audit_vhs_t1_criticality.py                 ← T1 classification audit
  audit_vhs_v3_immobilise_cases.py            ← initial 25-IMMOBILISE investigation
  audit_vhs_v3_immobilise_driver_labels.py    ← driver checkpoint label resolution
  compare_vhs_v3_candidate_before_after_immobilizing_fix.py  ← fix validation
```

---

## 3. Files to move to etl/mart/maintenance/

Scripts that modify reference data. Not executed in normal pipeline runs.
Must be kept traceable with their output reports.

```
etl/mart/maintenance/
  update_dim_checkpoint_v3_immobilizing_flags.py   ← the dim_checkpoint fix
```

---

## 4. Files to move to etl/mart/archive/

Old compute engines and their associated audits. Kept for traceability.
Must never be executed on the current database.

```
etl/mart/archive/
  v1/
    compute_vhs_v1.py               ← renamed from compute_vhs.py
    audit_vhs_v1.py
    compute_vhs_v1_scoring_copy.py  ← renamed from scoring/compute_vhs.py
  v2/
    compute_vhs_v2.py
    audit_vhs_v2_severe_cases.py
```

---

## 5. Report files to reorganise under data/quality_reports/vhs/

### Create data/quality_reports/vhs/final/

Move here the key outputs of the final corrected V3 run:

```
data/quality_reports/vhs/final/
  vhs_v3_audit_summary.md                           ← from vhs_balanced_v3_candidate/
  vhs_v2_vs_v3_comparison_summary.md                ← from vhs_balanced_v3_candidate/
  dim_checkpoint_immobilizing_update_summary.md      ← from dim_checkpoint_update/
  v3_immobilise_fix_summary.md                      ← from immobilise_fix_comparison/
  [CSVs: decision, grade, status, tier, ambiguous, comparison, before/after]
```

### Create data/quality_reports/vhs/archive/v1/

```
data/quality_reports/vhs/archive/v1/
  vhs_audit_summary.md               ← from audit_vhs_v1/
  vhs_business_rule_audit_v1.csv     ← renamed from vhs_business_rule_audit.csv
  [all other audit_vhs_v1/ CSVs]
```

### Create data/quality_reports/vhs/archive/v2/

```
data/quality_reports/vhs/archive/v2/
  vhs_v1_vs_v2_summary.md            ← keep as markdown
  v2_severe_cases_audit_summary.md   ← from audit_vhs_v2_severe_cases/
  vhs_business_rule_audit_v2.csv
  vhs_v1_vs_v2_comparison.csv
  [all other V2 CSVs]
```

### Create data/quality_reports/vhs/archive/v3_experiments/

```
data/quality_reports/vhs/archive/v3_experiments/
  staffim_comment_analysis_summary.md   ← from staffim_comment_analysis/
  immobilise_audit/                     ← move whole folder here
    v3_immobilise_audit_summary.md
    v3_immobilise_driver_label_summary.md
    [all other immobilise audit CSVs]
  [all staffim_comment_analysis/ CSVs]
```

### Keep in place

```
data/quality_reports/vhs/audit_t1_criticality/   ← still relevant for V3
```

---

## 6. Files to exclude from Git (already or newly)

Most of these are already covered by the existing `.gitignore`.
No changes needed unless noted.

| Pattern | Already ignored? | Action |
|---------|-----------------|--------|
| `logs/` | ✅ Yes | No change needed |
| `*.log` | ✅ Yes | No change needed |
| `__pycache__/` | ✅ Yes | No change needed |
| `*.pyc` | ✅ Yes (via `*.py[cod]`) | No change needed |
| `notebooks/` | ✅ Yes | No change needed — entire folder excluded |
| `*.csv` | ✅ Yes | CSVs excluded; `.md` in quality_reports kept |
| `data/tmp/` | ❌ Not present yet | Add if a tmp folder is created |

**Proposed .gitignore additions** (add to `.gitignore` after review):

```gitignore
# =========================
# VHS — additional exclusions
# =========================
data/tmp/
data/raw/
data/interim/
*.bak
*.tmp

# Notebook outputs written to wrong paths
notebooks/data/
```

> Note: `data/raw/`, `data/interim/` are already in `.gitignore` but added here
> for clarity. The important new addition is `notebooks/data/` to catch
> notebook outputs that accidentally write to a subfolder of `notebooks/`.

---

## 7. Files requiring manual review

| File | Reason | Suggested action |
|------|--------|-----------------|
| `data/quality_reports/vhs/dim_checkpoint_review.csv` | Not produced by any identified VHS script. Could be a manual export from the DB, an intermediate file, or an early draft of `mart.dim_checkpoint`. | Open the file, check its columns and row count. If it's a manual export of the checkpoint reference, keep and move to `archive/v1/`. If it's outdated, delete after confirming no script depends on it. |

---

## 8. Safe order of operations

Execute the steps in this exact order. Do not skip steps.

**Step 1 — Create target folders**

```bash
mkdir -p etl/mart/audits
mkdir -p etl/mart/maintenance
mkdir -p etl/mart/archive/v1
mkdir -p etl/mart/archive/v2
mkdir -p data/quality_reports/vhs/final
mkdir -p data/quality_reports/vhs/archive/v1
mkdir -p data/quality_reports/vhs/archive/v2
mkdir -p data/quality_reports/vhs/archive/v3_experiments/immobilise_audit
mkdir -p data/quality_reports/vhs/archive/v3_experiments/staffim_comment_analysis
```

**Step 2 — Copy files to target locations (do NOT move yet)**

Copy, not move. The original files must remain in place until all
copies are verified and import paths confirmed working.

```bash
# Audit scripts
cp etl/mart/audit_vhs_t1_criticality.py                           etl/mart/audits/
cp etl/mart/audit_vhs_v3_immobilise_cases.py                      etl/mart/audits/
cp etl/mart/audit_vhs_v3_immobilise_driver_labels.py              etl/mart/audits/
cp etl/mart/compare_vhs_v3_candidate_before_after_immobilizing_fix.py  etl/mart/audits/

# Maintenance scripts
cp etl/mart/update_dim_checkpoint_v3_immobilizing_flags.py        etl/mart/maintenance/

# Archive V1
cp etl/mart/compute_vhs.py                                        etl/mart/archive/v1/compute_vhs_v1.py
cp etl/mart/audit_vhs_v1.py                                       etl/mart/archive/v1/
cp scoring/compute_vhs.py                                          etl/mart/archive/v1/compute_vhs_v1_scoring_copy.py

# Archive V2
cp etl/mart/compute_vhs_v2.py                                     etl/mart/archive/v2/
cp etl/mart/audit_vhs_v2_severe_cases.py                          etl/mart/archive/v2/
```

**Step 3 — Verify imports still work**

The audit scripts use this import pattern:
```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dwh"))
import dwh_utils
```

After copying to `etl/mart/audits/`, `parent.parent` resolves to `etl/`.
The `dwh/` sibling folder is at `etl/dwh/` — the import still works.

After copying to `etl/mart/maintenance/`, same reasoning — still works.

After copying to `etl/mart/archive/v1/` and `archive/v2/`, the same
`parent.parent` resolves to `etl/` — still works.

> **Verify by running a dry-run import check before deleting originals:**
> ```bash
> python -c "import sys; sys.path.insert(0,'etl/dwh'); import dwh_utils; print('OK')"
> ```

**Step 4 — Verify compute_vhs_v3_candidate.py still runs**

```bash
python etl/mart/compute_vhs_v3_candidate.py --dry-run
```

(or use a read-only check — import only, do not insert to DB)

```bash
python -c "import sys; sys.path.insert(0,'etl/mart'); import compute_vhs_v3_candidate; print('import OK')"
```

**Step 5 — Reorganise report files**

Copy final V3 reports to `data/quality_reports/vhs/final/`:

```bash
cp "data/quality_reports/vhs/vhs_balanced_v3_candidate/vhs_v3_audit_summary.md"          "data/quality_reports/vhs/final/"
cp "data/quality_reports/vhs/vhs_balanced_v3_candidate/vhs_v2_vs_v3_comparison_summary.md" "data/quality_reports/vhs/final/"
cp "data/quality_reports/vhs/vhs_balanced_v3_candidate/dim_checkpoint_update/dim_checkpoint_immobilizing_update_summary.md" "data/quality_reports/vhs/final/"
cp "data/quality_reports/vhs/vhs_balanced_v3_candidate/immobilise_fix_comparison/v3_immobilise_fix_summary.md" "data/quality_reports/vhs/final/"
```

**Step 6 — Update .gitignore**

Add the proposed block from Section 6 above.

**Step 7 — After full validation, remove duplicated originals**

Only after confirming:
- All copies are in correct locations
- All imports work
- compute_vhs_v3_candidate.py is importable from its original location
- Audit scripts run correctly from their new locations

Remove the originals from `etl/mart/` (leave only `compute_vhs_v3_candidate.py`
and utility scripts in the root of `etl/mart/`).

---

## Final target structure (after cleanup)

```
etl/
└── mart/
    ├── __init__.py
    ├── load_dim_checkpoint.py
    ├── compute_vhs_v3_candidate.py          ← KEEP_MAIN
    │
    ├── audits/
    │   ├── audit_vhs_t1_criticality.py      ← KEEP_AUDIT
    │   ├── audit_vhs_v3_immobilise_cases.py ← KEEP_AUDIT
    │   ├── audit_vhs_v3_immobilise_driver_labels.py  ← KEEP_AUDIT
    │   └── compare_vhs_v3_candidate_before_after_immobilizing_fix.py  ← KEEP_AUDIT
    │
    ├── maintenance/
    │   └── update_dim_checkpoint_v3_immobilizing_flags.py  ← KEEP_MAINTENANCE
    │
    └── archive/
        ├── v1/
        │   ├── compute_vhs_v1.py
        │   ├── audit_vhs_v1.py
        │   └── compute_vhs_v1_scoring_copy.py
        └── v2/
            ├── compute_vhs_v2.py
            └── audit_vhs_v2_severe_cases.py

docs/
├── vhs/
│   ├── vhs_calculation_method.md            ← KEEP_MAIN
│   ├── vhs_file_decision_matrix.md          ← this audit
│   └── vhs_cleanup_plan.md                  ← this plan
└── diagrams/
    ├── vhs_calculation_flow.mmd              ← KEEP_MAIN
    └── vhs_mapping_rules.mmd                 ← KEEP_MAIN

data/quality_reports/vhs/
├── final/                                    ← NEW folder
│   ├── vhs_v3_audit_summary.md
│   ├── vhs_v2_vs_v3_comparison_summary.md
│   ├── dim_checkpoint_immobilizing_update_summary.md
│   ├── v3_immobilise_fix_summary.md
│   └── [V3 CSVs — local only, not in Git]
│
├── audit_t1_criticality/                     ← KEEP_AUDIT (in place)
│   ├── t1_audit_summary.md
│   └── [CSVs — local only]
│
└── archive/                                  ← NEW folder
    ├── v1/
    │   ├── vhs_audit_summary.md
    │   └── [V1 CSVs — local only]
    ├── v2/
    │   ├── vhs_v1_vs_v2_summary.md
    │   ├── v2_severe_cases_audit_summary.md
    │   └── [V2 CSVs — local only]
    └── v3_experiments/
        ├── staffim_comment_analysis_summary.md
        └── immobilise_audit/
            ├── v3_immobilise_audit_summary.md
            ├── v3_immobilise_driver_label_summary.md
            └── [CSVs — local only]

notebooks/
└── archive/                                  ← move notebook here
    └── 04_staffim_comment_analysis_for_vhs.ipynb
```

---

## Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Broken import in audit scripts after move | Low | Low | Verify with `sys.path` check before deleting originals |
| compute_vhs_v3_candidate.py stops working | Very low | High | Never touch this file; verify import after any folder change |
| Loss of audit evidence | Low | Medium | Copy-then-verify before delete; use git history as backup |
| CSV data loss | Low | Low | CSVs are regenerable by re-running scripts against DB |
| Markdown loss | Very low | Medium | Tracked in Git; use git history as safety net |

---

> **Recommendation:** Do not delete yet. Review the decision matrix at
> `docs/vhs/vhs_file_decision_matrix.md` first. After approval, run a
> second cleanup script to copy/move files safely following the order
> defined in Step 8 above.
