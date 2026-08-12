# dim_checkpoint Update — V3 Immobilizing Flags

> Generated: 2026-07-03 18:12 UTC  
> Script: `etl/mart/update_dim_checkpoint_v3_immobilizing_flags.py`  
> Table modified: `mart.dim_checkpoint`  

---

## Context

VHS_BALANCED_V3_CANDIDATE produced 25 IMMOBILISE cases (vs 1 in V2).
Audit confirmed all 25 are triggered by 5 checkpoints with
`is_immobilizing=true` and `valeur_controle = Contrôle non OK`.

Business decision: only the **motor oil level** defect should
automatically trigger IMMOBILISE ('Usage deconseille').
The other four T2_CRITICAL checkpoints should remain serious
(BROKEN → DEGRADE via `is_critical_functional=true`) but must
not cause automatic IMMOBILISE.

---

## Changes Applied

**Rows updated:** 4 (expected 4)

| checkpoint_code | libelle | zone | tier | before is_immobilizing | after is_immobilizing | is_critical_functional |
|---|---|---|---|---|---|---|
| `sous_le_capot_controle_du_niveau_huile_moteur` | Controle du niveau huile moteur | SOUS_CAPOT | T2_CRITICAL | True | True ← **unchanged** | True |
| `sous_le_capot_controle_etat_des_courroies_d_accessoires` | Controle etat des courroies d accessoires | SOUS_CAPOT | T2_CRITICAL | True | False | True |
| `sous_le_capot_controle_du_niveau_du_liquide_de_refroidi` | Controle du niveau du liquide de refroidi | SOUS_CAPOT | T2_CRITICAL | True | False | True |
| `sous_le_vehicule_controle_etancheite_tous_fluides` | Controle etancheite tous fluides | SOUS_VEHICULE | T2_CRITICAL | True | False | True |
| `sous_le_capot_controle_batterie_etat_fixation_et_charge` | Controle batterie etat fixation et charge | SOUS_CAPOT | T2_CRITICAL | True | False | True |

---

## Validation

| Check | Result |
|-------|--------|
| Motor oil is_immobilizing remains TRUE | ✅ |
| 4 updated rows is_immobilizing = FALSE | ✅ |
| All 5 rows is_critical_functional = TRUE | ✅ |
| All 5 rows tier = T2_CRITICAL | ✅ |
| Overall validation | ✅ PASSED |

---

## Next Step

Re-run `etl/mart/compute_vhs_v3_candidate.py` to produce a new
`VHS_BALANCED_V3_CANDIDATE` run with the corrected `is_immobilizing` flags.

Then run `etl/mart/compare_vhs_v3_candidate_before_after_immobilizing_fix.py`
to compare IMMOBILISE counts before and after this fix.
