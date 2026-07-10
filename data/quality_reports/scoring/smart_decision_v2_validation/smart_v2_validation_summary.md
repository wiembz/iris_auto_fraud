# Smart Decision Support V2 read-only validation

This validation reads existing DWH/mart data and computes V2 candidate outputs in memory only.
No PostgreSQL write, ETL load, table creation, or score replacement is performed.

- Loaded claim rows: 381893
- V2 score rows: 381893
- Evaluation status: PARTIALLY_EVALUABLE
- Evaluable families: CHRONOLOGY,COMPARISON,HISTORY
- Non-evaluable families: COMPLETENESS,DATA_QUALITY,GEOGRAPHY
- Fully evaluable claims: 0
- Partially evaluable claims: 381893
- Displayable comparison rate: 0.8395597719780148

## Grain audit
- Distinct claim root ids: 231496
- Multi-guarantee claim roots: 119041
- Claim roots with multiple V2 scores: 31341
- Claim roots with multiple V2 levels: 13889
- Business decision required: dossier-level worklist vs sinistre-garantie grain.

## Validation checks
- score_out_of_range_rows: 0
- duplicate_v2_score_claim_rows: 0
- null_attention_level_rows: 0
- accusatory_wording_rows: 0
- v1_missing_comparison_rows: 0
- grain_decision_needed: True
- business_validation_status: TECHNICAL_VALIDATION_OK_BUSINESS_VALIDATION_PARTIAL

## Business interpretation
V2 is technically calculable on the DWH volume, but remains a candidate parallel score.
It must not replace V1 until the business grain, missing V2 families, confidence rules, and thresholds are validated.
