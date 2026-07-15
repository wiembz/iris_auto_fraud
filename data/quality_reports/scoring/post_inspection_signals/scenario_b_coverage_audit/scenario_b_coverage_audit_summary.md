# Scenario B coverage audit

- Run timestamp UTC: `2026-07-08 11:35:39+0000`
- Scope: read-only audit of Inspection -> Avenant / contract movement feasibility.
- Safety: no Claim Attention Score integration, no VHS modification, no ML.

## Decision

Scenario B readiness: **PARTIAL**

Timing inspection -> avenant is measurable, but coverage/guarantee change is not proven on 0-90d candidate links.

## Key measurements

- Inspection -> avenant links 0-90d: 51
- 0-7d: 4
- 8-30d: 14
- 31-90d: 33
- Distinct inspections: 49
- Distinct contracts: 49
- Observable product/prime change links 0-90d: 0
- Missing produit_sk rows in fact_contrat: 67914

## Interpretation

The timing link is measurable, but current DWH fields do not prove that an endorsement changed a guarantee or coverage related to documented inspection defects.
Scenario B must remain readiness/context-only until a contract-guarantee history or equivalent source is validated.

## Generated reports

- `scenario_b_candidate_column_inventory.csv`
- `scenario_b_candidate_links_sample.csv`
- `scenario_b_contract_movement_summary.csv`
- `scenario_b_dim_garantie_profile.csv`
- `scenario_b_linkage_summary.csv`
- `scenario_b_observable_change_link_summary.csv`
- `scenario_b_observable_change_summary.csv`
- `scenario_b_product_distribution.csv`
- `scenario_b_readiness_decision.csv`
- `scenario_b_source_column_inventory.csv`
