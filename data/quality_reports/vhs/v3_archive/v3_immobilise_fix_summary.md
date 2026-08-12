# VHS V3 Candidate — Before/After Immobilizing Fix Comparison

> Generated: 2026-07-03 18:13 UTC  
> Old run: `VHS_BALANCED_V3_CANDIDATE_20260702_190239`  
> New run: `VHS_BALANCED_V3_CANDIDATE_20260703_181257`  
> Script: `etl/mart/compare_vhs_v3_candidate_before_after_immobilizing_fix.py`  
> **READ-ONLY** — no data was modified.

---

## 1. Context

VHS_BALANCED_V3_CANDIDATE correctly fixed ambiguous value mapping
(PROPOSITION FAITE, NON → no longer BROKEN), but introduced 25 IMMOBILISE
cases (vs 1 in V2). A read-only audit identified 5 driver checkpoints,
all with `is_immobilizing=true` and `valeur_controle = Contrôle non OK`.

---

## 2. Why the Fix Was Needed

IMMOBILISE ('Usage deconseille') should remain rare.
Business decision: only **motor oil level** (`Contrôle du niveau huile moteur`)
should automatically trigger IMMOBILISE.

The 4 other T2_CRITICAL checkpoints should produce **DEGRADE** via
`is_critical_functional=true` and the CRITICAL_FUNCTIONAL hard cap (65),
not IMMOBILISE (cap 50).

---

## 3. Checkpoints Changed

| Action | checkpoint_code |
|--------|-----------------|
| **KEPT** is_immobilizing=true | `sous_le_capot_controle_du_niveau_huile_moteur` |
| SET is_immobilizing=false | `sous_le_capot_controle_etat_des_courroies_d_accessoires` |
| SET is_immobilizing=false | `sous_le_capot_controle_du_niveau_du_liquide_de_refroidi` |
| SET is_immobilizing=false | `sous_le_vehicule_controle_etancheite_tous_fluides` |
| SET is_immobilizing=false | `sous_le_capot_controle_batterie_etat_fixation_et_charge` |

---

## 4. Decision Distribution

| Decision | Before | After | Delta |
|----------|--------|-------|-------|
| OK | 89 | 89 | = 0 |
| DEGRADE | 121 | 133 | ↑ 12 |
| IMMOBILISE | 25 | 13 | ↓ 12 |
| CRITIQUE | 51 | 51 | = 0 |

---

## 5. IMMOBILISE Count

| Metric | Value |
|--------|-------|
| IMMOBILISE before | **25** |
| IMMOBILISE after  | **13** |
| Decrease          | **12** |
| Previously IMMOBILISE inspections | **25** |

---

## 6. Grade Distribution

| Grade | Before | After | Delta |
|-------|--------|-------|-------|
| A | 95 | 95 | = 0 |
| B | 11 | 11 | = 0 |
| C | 129 | 129 | = 0 |
| D | 51 | 51 | = 0 |

---

## 7. Decision Transitions

| From | To | Count |
|------|-----|-------|
| IMMOBILISE | DEGRADE | 12 |

---

## 8. Validation Checks

| Check | Status | Detail |
|-------|--------|--------|
| Old IMMOBILISE count = 25 | ✅ | actual = 25 |
| New IMMOBILISE count < old | ✅ | before=25  after=13 |
| CRITIQUE count stable (delta ≤ 1) | ✅ | before=51  after=51  delta=0 |
| Grade D count stable (delta ≤ 1) | ✅ | before=51  after=51  delta=0 |
| No IMMOBILISE → OK transitions | ✅ | IMMOBILISE → OK = 0 |
| Fixed cases mostly become DEGRADE (≥ 80%) | ✅ | 12/12 = 100% |
| Fixed cases retain has_critical_functional=true | ✅ | 12/12 retain cf |
| Total inspections stable | ✅ | before=286  after=286 |

**Overall:** ✅ ALL CHECKS PASSED

---

## 9. Recommendation

> **VHS_BALANCED_V3_CANDIDATE was corrected to avoid excessive automatic**
> **'Usage deconseille' decisions.**
>
> Only motor oil level defects remain automatically immobilizing.
> Other under-the-hood critical defects remain serious and are classified
> as **DEGRADE** with a critical functional hard cap (65), preserving the
> risk signal without over-escalating the decision.

IMMOBILISE decreased from 25 to 13.
25 previously IMMOBILISE inspections were reviewed:
- IMMOBILISE → DEGRADE : 12
- IMMOBILISE → OK      : 0
