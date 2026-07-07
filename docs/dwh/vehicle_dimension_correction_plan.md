# Vehicle Dimension Correction Plan

Date: 2026-07-08  
Status: documentation-first plan, no ETL implementation yet  
Scope: DWH vehicle linkage prerequisite for the BNA-priority post-inspection attention signal

## 1. Executive Summary

The post-inspection workstream is a business-priority module for BNA Assurances. Its purpose is to identify situations that require prioritized human verification after a STAFFIM inspection, such as:

- inspection followed by a claim on a potentially related vehicle area;
- inspection followed by an endorsement or coverage movement.

This module can only be defensible if IRIS can reliably link:

```text
inspection -> vehicle -> claim / contract movement
```

The current blocker is DWH vehicle coverage. `dwh.dim_vehicule` currently contains only 280 vehicles, while claim-side staging data contains 128,032 normalized distinct immatriculations. Because `dwh.fact_sinistre` resolves `vehicule_sk` by looking up claim-side immatriculations in `dwh.dim_vehicule`, most claims remain linked to technical key `0`.

Conclusion:

```text
Reliable vehicle linkage is a prerequisite. The vehicle dimension must be corrected and governed before creating mart.fact_post_inspection_attention_signal.
```

This document is a plan only. It does not authorize database writes or ETL changes by itself.

## 2. Current DWH Issue

Measured audit results:

| Metric | Value | Interpretation |
|---|---:|---|
| `dwh.dim_vehicule` rows | 280 | dimension coverage is very small |
| `dwh.fact_sinistre` rows | 381,893 | central claim fact volume |
| `dwh.fact_sinistre.vehicule_sk = 0` | 380,968 | vehicle key missing for almost all claims |
| `staging.stg_sinistres` rows | 381,893 | same source volume as claim fact |
| `staging.stg_sinistres` rows with non-empty `immat` | 377,970 | claim source has vehicle identifiers |
| normalized distinct claim immatriculations | 128,032 | broad claim-side vehicle universe |
| empty after immatriculation normalization | 0 | normalization does not erase non-empty values |
| claim immatriculations matched to `dwh.dim_vehicule` | 925 | current dimension matches only a tiny subset |
| claim immatriculations not matched to `dwh.dim_vehicule` | 377,045 | lookup failure explains `vehicule_sk = 0` |

The source contains vehicle identifiers. The issue is that `dwh.dim_vehicule` does not govern the claim-side vehicle universe.

## 3. Root Cause Hypothesis

Current code references indicate:

- `etl/dwh/load_dim_vehicule.py` builds `dwh.dim_vehicule` from `staging.stg_inspection`.
- `etl/dwh/load_fact_sinistre.py` reads `staging.stg_sinistres.immat`.
- `etl/dwh/load_fact_sinistre.py` maps that immatriculation to `dwh.dim_vehicule`.
- If the normalized claim immatriculation is not present in `dwh.dim_vehicule`, the resulting `vehicule_sk` becomes `0`.

This explains the measured gap:

```text
dwh.dim_vehicule ~= STAFFIM inspection vehicles
staging.stg_sinistres.immat ~= claim-side vehicle identifiers
```

Since `dwh.dim_vehicule` is mostly inspection-driven today, claim-side immatriculations usually fail the lookup.

## 4. Proposed Target Design

`dwh.dim_vehicule` should become a global vehicle dimension for IRIS automobile analysis.

Target sources:

| Source | Identifier | Purpose |
|---|---|---|
| `staging.stg_inspection` | `immatriculation` | STAFFIM inspected vehicles, may include VIN/motorisation |
| `staging.stg_sinistres` | `immat` | claim-side vehicle identifiers |
| future contract/production source, if available | vehicle identifier TBD | contract-side vehicle linkage |

Target grain:

```text
one row per normalized immatriculation
```

Target key:

```text
vehicule_sk = DWH surrogate key
```

Target treatment:

- missing immatriculations are excluded from the normal vehicle member set and reported;
- invalid-like immatriculations are excluded or flagged in a quality report;
- claim-only vehicles are kept even if VIN and motorisation are missing;
- inspection vehicles and claim vehicles with the same normalized immatriculation merge into one dimension member.

## 5. Normalization Strategy

A single shared immatriculation normalization function should be defined and reused.

Required consumers:

| Consumer | Required use |
|---|---|
| `etl/dwh/load_dim_vehicule.py` | build normalized vehicle dimension keys |
| `etl/dwh/load_fact_inspection_vehicule.py` | compute `immatriculation_norm` and join `vehicule_sk` |
| `etl/dwh/load_fact_inspection_checkpoint.py` | reproduce inspection key/linkage logic |
| `etl/dwh/load_fact_sinistre.py` | resolve claim-side `vehicule_sk` |
| future post-inspection linkage audit | compare inspection and claim vehicles consistently |

Normalization rule candidate:

```text
UPPER(value)
TRIM(value)
remove characters outside A-Z and 0-9
treat empty result as missing
treat invalid-like values as missing or non-joinable
```

The SQL expression used during audit is only an approximation:

```sql
UPPER(REGEXP_REPLACE(TRIM(immat), '[^A-Z0-9]', '', 'g'))
```

Production ETL should use one Python function, not several ad hoc variants spread across loaders.

## 6. Deduplication Strategy

The target dimension should keep one vehicle member per normalized immatriculation.

Deduplication rules:

- if an immatriculation exists in both inspection and claim sources, create one `dim_vehicule` row;
- prefer non-null descriptive attributes from inspection when available, such as VIN and motorisation;
- do not discard claim-only vehicles because VIN or motorisation is missing;
- preserve source coverage indicators for auditability.

Recommended source indicators:

| Column | Meaning |
|---|---|
| `source_has_inspection` | vehicle observed in `staging.stg_inspection` |
| `source_has_claim` | vehicle observed in `staging.stg_sinistres` |
| `source_has_contract` | future flag if a contract-side vehicle source exists |
| `source_record_count` | total contributing source rows |
| `vehicle_quality_flag` | normalized quality category for the dimension member |

VIN and motorisation handling:

- inspection side may provide VIN and motorisation;
- claim side may only provide immatriculation;
- claim-only vehicles should still be valid dimension members;
- if VIN conflicts appear later, they should be reported, not silently resolved.

## 7. Recommended DWH Changes

Plan only. Do not implement without approval.

Recommended changes:

1. Extend `dwh.dim_vehicule` input sources from inspection-only to inspection + claim-side immatriculations.
2. Add or reuse a shared normalization utility for immatriculation.
3. Add quality reports for:
   - missing immatriculation;
   - invalid-like immatriculation;
   - empty after normalization;
   - duplicate normalized immatriculation before deduplication;
   - source coverage by inspection/claim/contract.
4. Consider optional dimension columns:

| Candidate column | Purpose |
|---|---|
| `immatriculation_norm` | explicit normalized key, if separate from display `immatriculation` |
| `source_has_inspection` | source lineage |
| `source_has_claim` | source lineage |
| `source_has_contract` | future source lineage |
| `source_record_count` | auditability |
| `vehicle_quality_flag` | quality segmentation |

Compatibility note:

If the physical table schema changes, dependent loaders and marts must be reviewed. If schema expansion is too risky, the same indicators can first be exported in quality reports rather than added as columns.

## 8. Reload Order

Future execution order after approval:

1. Inspect `git status` and confirm exact files to modify.
2. Back up the current database or confirm a restore point.
3. Update the shared immatriculation normalization utility.
4. Update `etl/dwh/load_dim_vehicule.py`.
5. Reload `dwh.dim_vehicule`.
6. Reload `dwh.fact_inspection_vehicule`.
7. Reload `dwh.fact_inspection_checkpoint`.
8. Reload `dwh.fact_sinistre`.
9. Rerun vehicle linkage quality checks.
10. Rerun `notebooks/validation_scoring/02_post_inspection_signal_readiness.ipynb`.
11. Decide whether `mart.fact_post_inspection_attention_signal` can be created.

Important:

- do not reload VHS unless explicitly required and approved;
- do not modify Claim Attention Score V1 unless explicitly required and approved;
- do not create the post-inspection mart before the vehicle linkage checks pass.

## 9. Validation Checks

The checks below are read-only SQL examples to run after implementation.

### 9.1 Vehicle Dimension Coverage

```sql
SELECT
    COUNT(*) AS total_vehicules,
    COUNT(*) FILTER (WHERE vehicule_sk = 0) AS zero_key_rows,
    COUNT(DISTINCT immatriculation) AS distinct_immatriculations
FROM dwh.dim_vehicule;
```

Expected direction:

```text
dim_vehicule row count should increase significantly.
zero_key_rows should remain 0.
```

### 9.2 Duplicate Normalized Immatriculations

Use the production normalization function in ETL reports where possible. For SQL audit approximation:

```sql
WITH normalized AS (
    SELECT
        UPPER(REGEXP_REPLACE(TRIM(immatriculation), '[^A-Z0-9]', '', 'g')) AS immat_norm,
        COUNT(*) AS rows
    FROM dwh.dim_vehicule
    WHERE immatriculation IS NOT NULL
      AND TRIM(immatriculation) <> ''
    GROUP BY 1
)
SELECT *
FROM normalized
WHERE rows > 1
ORDER BY rows DESC, immat_norm;
```

Expected result:

```text
0 duplicate normalized immatriculations.
```

### 9.3 Claim Vehicle Linkage Coverage

```sql
SELECT
    COUNT(*) AS total_claim_rows,
    COUNT(*) FILTER (WHERE vehicule_sk IS NULL OR vehicule_sk = 0) AS missing_vehicule_sk,
    COUNT(*) FILTER (WHERE vehicule_sk IS NOT NULL AND vehicule_sk <> 0) AS valid_vehicule_sk
FROM dwh.fact_sinistre;
```

Expected direction:

```text
fact_sinistre vehicule_sk = 0 should decrease strongly.
```

### 9.4 Inspection Vehicle Linkage Stability

```sql
SELECT
    COUNT(*) AS total_inspections,
    COUNT(*) FILTER (WHERE vehicule_sk IS NULL OR vehicule_sk = 0) AS missing_vehicule_sk,
    COUNT(*) FILTER (WHERE immatriculation_norm IS NULL OR TRIM(immatriculation_norm) = '') AS missing_immat_norm
FROM dwh.fact_inspection_vehicule;
```

Expected direction:

```text
inspection vehicle linkage should remain stable or improve.
```

### 9.5 Claim Source Immatriculation Coverage

```sql
SELECT
    COUNT(*) AS total_stg_sinistres,
    COUNT(*) FILTER (WHERE immat IS NULL OR TRIM(immat) = '') AS missing_immat,
    COUNT(DISTINCT UPPER(REGEXP_REPLACE(TRIM(immat), '[^A-Z0-9]', '', 'g')))
        FILTER (WHERE immat IS NOT NULL AND TRIM(immat) <> '') AS distinct_immat_normalized
FROM staging.stg_sinistres;
```

Expected direction:

```text
input source coverage should remain consistent with the baseline audit.
```

### 9.6 VHS and Claim Attention Guardrails

Validation policy:

- VHS results must remain unchanged unless explicitly re-run;
- Claim Attention Score V1 row counts must remain unchanged unless intentionally re-run;
- if re-run intentionally, compare row counts and distributions before/after.

### 9.7 Post-Inspection Readiness

Rerun:

```text
notebooks/validation_scoring/02_post_inspection_signal_readiness.ipynb
```

Validation expectations:

- candidate links should be recalculated using real date parsing;
- do not use `YYYYMMDD + 90` as a date interval;
- readiness should move from partial/blocking toward measurable readiness if linkage improves.

## 10. Acceptance Criteria

The correction can be considered successful when:

- `dwh.dim_vehicule` includes claim-side immatriculations;
- `dwh.fact_sinistre.vehicule_sk` coverage improves materially;
- STAFFIM inspections still have strong `vehicule_sk` coverage;
- no destructive effect is observed on VHS artifacts;
- no destructive effect is observed on Claim Attention Score V1 artifacts;
- post-inspection readiness moves from blocked/partial toward measurable readiness;
- all corrections are traceable through quality reports and run logs.

## 11. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Surrogate keys change after rebuilding `dim_vehicule` | dependent facts may need reload | control reload order and reload all dependent facts |
| Inconsistent normalization across loaders | weak or contradictory linkage | use one shared Python normalization function |
| Claim-only vehicles lack VIN/motorisation | dimension members may look incomplete | keep them with quality flags; do not discard them |
| Physical schema changes break downstream code | ETL or BI regressions | prefer additive columns; test dependent scripts |
| Weak staging bridge used directly in final mart | non-governed linkage in business output | use staging bridge only for audit until DWH dimension is corrected |
| Physical foreign keys added too early | reload friction and failures | do not create physical FKs immediately |
| Accusatory interpretation of signals | business and governance risk | keep attention/prioritization wording only |

## 12. Recommended Next Step

After this document is reviewed, implement the correction in a separate small commit.

Before implementation:

1. Inspect `git status`.
2. List the exact files to modify.
3. Confirm the DWH reload window and backup/restore approach.
4. Confirm no database writes are allowed until explicitly approved.

Likely implementation files, pending review:

```text
etl/utils/vehicle_normalization.py       # new shared normalization utility, or equivalent existing utility
etl/dwh/load_dim_vehicule.py             # extend input sources and reports
etl/dwh/load_fact_inspection_vehicule.py # consume shared normalization
etl/dwh/load_fact_inspection_checkpoint.py # consume shared normalization indirectly/consistently
etl/dwh/load_fact_sinistre.py            # consume shared normalization
tests/test_vehicle_normalization.py      # focused normalization tests
```

Do not use:

```text
git add .
```

Use targeted staging commands only after review.
