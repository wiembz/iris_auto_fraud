# Changelog du catalogue de regles Claim Attention V2

Ce fichier trace toute modification du catalogue
`config/claim_attention/rules_v2_candidate.json` : qui, quand, quoi, pourquoi.
Il complete la gouvernance technique existante (`catalog_version`,
`rule_catalog_hash` SHA-256 journalise dans chaque ligne de detail de score).

Regle de gouvernance : toute modification de seuil, de points, de plafond, de
wording ou d'activation doit ajouter une entree ici, faire tourner les tests
(`tests/test_claim_business_rules_v2.py`, `tests/test_claim_attention_score_v2.py`)
et rester une proposition candidate tant que `validated_by` est null.

---

## 2026-07-12 - Revision r2 - Tracabilite de validation et grain

- **Auteur :** equipe projet IRIS (PFE)
- **Hash catalogue (SHA-256) :** `ab01fba14833aec9cda30bae79cdb0a7904215ee3f32010e9f3919fc32734452`
- **Impact score :** aucun (aucun seuil, point, plafond ou condition modifie ;
  changement de metadonnees uniquement, verifie par les tests golden).

### Modifications

- Ajout sur chaque regle des champs de tracabilite de validation :
  - `threshold_source` : origine du seuil (statistique candidate, controle
    deterministe, classification qualite) ;
  - `validated_by` / `validated_on` : null tant que la regle n'est pas validee
    par le metier BNA. Coherent avec le statut global
    `BUSINESS_VALIDATION_PARTIAL`.
- Ajout du champ `grain` (`GUARANTEE` ou `DOSSIER`) sur chaque regle. Toutes
  les regles actuelles s'appliquent au grain `sinistre x garantie`
  (`GUARANTEE`) ; l'agregation dossier reste regie par
  `docs/architecture/ADR_CLAIM_DECISION_GRAIN.md` (MAX des garanties, pas de
  somme, pas de bonus multi-garanties).
- Le validateur (`validate_rule_catalog`) rend ces champs obligatoires et
  controle leurs valeurs : toute regle future sans grain declare ou sans
  origine de seuil est refusee au chargement.

### Motivation

- Distinguer explicitement, regle par regle, ce qui est valide metier de ce
  qui reste candidat statistique.
- Empecher qu'une future regle reintroduise silencieusement une ambiguite de
  grain (dossiers dupliques dans la worklist avec des priorites
  contradictoires).

---

## 2026-07 - Revision r1 - Catalogue initial V2 candidate

- **Auteur :** equipe projet IRIS (PFE)
- **Hash catalogue :** non journalise dans ce fichier (anterieur a sa
  creation) ; le hash de chaque run reste disponible dans la colonne
  `rule_catalog_hash` des details de score produits par les validations.

### Contenu initial

- 6 regles actives : `CHR_DECLARATION_DELAY_HIGH`,
  `CHR_CLAIM_BEFORE_CONTRACT_START`, `HIST_CLIENT_RECURRENCE_12M`,
  `COMP_AMOUNT_ABOVE_SIMILAR_MEDIAN`, `COMP_CRITICAL_DOCUMENT_MISSING`,
  `DATA_QUALITY_LIMITED`.
- Plafonds par famille : CHRONOLOGY 25, HISTORY 20, COMPARISON 20,
  COMPLETENESS 15, GEOGRAPHY 10 (reserve), DATA_QUALITY 0, OTHER 10.
- Tous les seuils sont candidats, en attente de calibration BNA.

### Note de dimensionnement des plafonds (etat r1/r2)

| Famille | Regles actives | Points max cumulables | Plafond | Plafond effectif ? |
|---|---:|---:|---:|---|
| CHRONOLOGY | 2 | 32 | 25 | Oui, coupe reellement (teste) |
| HISTORY | 1 | 12 | 20 | Non atteint (famille mono-regle) |
| COMPARISON | 1 | 15 | 20 | Non atteint (famille mono-regle) |
| COMPLETENESS | 1 | 15 | 15 | Sature par une seule regle (choix conservateur temporaire) |
| GEOGRAPHY | 0 | 0 | 10 | Reserve tant que la decision GEO n'est pas GEO_READY |
| DATA_QUALITY | 1 | 0 | 0 | Par principe : la qualite reduit la confiance, jamais l'attention |

Les plafonds HISTORY et COMPARISON sont dimensionnes pour accueillir de
futures regles independantes dans ces familles ; ils ne sont pas recalibres
tant que la calibration metier BNA n'a pas eu lieu.
