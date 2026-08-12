# Résumé d audit read-only — préparation scoring dossier IRIS

- **Run date:** 2026-07-07 11:42:51
- **Connection status:** SUCCESS
- **Best central claim table candidate:** `dwh.fact_sinistre`

## Synthèse par domaine

| Area | Status | Main finding | Next action |
|---|---|---|---|
| Claim central table | READY | Candidate: dwh.fact_sinistre | Validate grain and auto scope. |
| Client recurrence | READY | Client column: client_sk | Validate historical windows. |
| Vehicle recurrence | NOT_READY | `vehicule_sk` exists but key `0` coverage is high (380,968 / 381,893). | Defer from V1 score points; keep readiness flags. |
| Third-party / driver | TO_AUDIT | Candidate tables audited. | Keep P3 if incomplete. |
| Chronology | PARTIAL | Declaration delay is READY after integer date-key conversion; contract-start features require fact_contrat join; recent-change features remain TO_AUDIT. | Use only implemented chronology features in V1. |
| Amount | READY | Amount column: montant_evaluation; V1 compares positive amounts within code_garantie. | Claim-type grouping remains TO_AUDIT. |
| GEO | TO_AUDIT | `geo_sinistre_sk` available with 21,245 missing technical keys. | Keep P2/readiness only until GEO scoring rules are validated. |
| VHS | TO_AUDIT | VHS candidate tables: 5 | Use as optional limited technical signal. |
| Data quality / confidence | READY | Confidence audit corrected: key `0` is missing and migration cutoff uses integer `20190101`. | Separate confidence from attention score. |

## Exports générés
- `data\quality_reports\scoring\data_readiness\claim_scoring_amount_by_guarantee.csv`
- `data\quality_reports\scoring\data_readiness\claim_scoring_amount_quality.csv`
- `data\quality_reports\scoring\data_readiness\claim_scoring_chronology_readiness.csv`
- `data\quality_reports\scoring\data_readiness\claim_scoring_claim_table_candidates.csv`
- `data\quality_reports\scoring\data_readiness\claim_scoring_client_recurrence_readiness.csv`
- `data\quality_reports\scoring\data_readiness\claim_scoring_confidence_readiness.csv`
- `data\quality_reports\scoring\data_readiness\claim_scoring_data_readiness_summary.md`
- `data\quality_reports\scoring\data_readiness\claim_scoring_date_quality.csv`
- `data\quality_reports\scoring\data_readiness\claim_scoring_geo_readiness.csv`
- `data\quality_reports\scoring\data_readiness\claim_scoring_key_coverage.csv`
- `data\quality_reports\scoring\data_readiness\claim_scoring_signal_readiness_matrix.csv`
- `data\quality_reports\scoring\data_readiness\claim_scoring_signal_readiness_summary.csv`
- `data\quality_reports\scoring\data_readiness\claim_scoring_table_inventory.csv`
- `data\quality_reports\scoring\data_readiness\claim_scoring_third_party_driver_readiness.csv`
- `data\quality_reports\scoring\data_readiness\claim_scoring_vehicle_recurrence_readiness.csv`
- `data\quality_reports\scoring\data_readiness\claim_scoring_vhs_linkage_readiness.csv`

## Recommandation
Le passage à l’implémentation du score V1 ne doit être effectué qu’après validation des familles P1 et documentation des limites P2/P3.

Ce notebook est read-only. Aucun score n a été calculé, aucune table n a été créée et aucune écriture en base n a été effectuée.