# Business Rule Catalog V2 Candidate

## Objectif

Le catalogue V2 formalise les regles metier sous une forme configurable, testable et explicable. Il alimente le score `IRIS_CLAIM_ATTENTION_V2_CANDIDATE` sans remplacer la V1.

## Format de configuration

Le catalogue est stocke dans :

```text
config/claim_attention/rules_v2_candidate.json
```

Decision : le fichier utilise JSON, car le projet ne declare pas de parseur YAML Python. Cela evite une dependance inutile et rend la validation au chargement deterministe.

## Structure d'une regle

Chaque regle contient :

- `rule_code` : identifiant stable.
- `rule_family` : famille de plafonnement.
- `version` : version de la regle.
- `label_business` : libelle metier affiche.
- `description` : explication technique courte.
- `attention_level` : formulation metier prudente.
- `required_fields` : champs obligatoires pour evaluer la regle.
- `condition` : condition declarative.
- `points` : poids brut candidat.
- `family_cap` : plafond de famille de la regle.
- `suggested_action_code` : action de revue associee.
- `business_explanation` : texte explicatif non accusatoire.
- `is_active` : activation ou desactivation.

## Validation au chargement

Le chargement refuse :

- famille absente de `family_caps` ;
- `is_active` non booleen ;
- points ou plafonds negatifs ;
- pointage superieur au plafond de regle ;
- operateur non autorise ;
- condition mal structuree ;
- champ de condition absent de `required_fields` ;
- champ `requires` non declare ;
- action suggeree inconnue ;
- version de score incoherente ;
- formulation accusatoire.

## Familles actives initiales

- `CHRONOLOGY`
- `HISTORY`
- `COMPARISON`
- `COMPLETENESS`
- `DATA_QUALITY`

`GEOGRAPHY` reste reserve tant que la decision GEO n'est pas `GEO_READY`.

## Plafonds

- Chronologie : 25 points.
- Historique : 20 points.
- Comparaison : 20 points.
- Completeness : 15 points.
- GEO : 10 points, non actif en `GEO_PARTIAL`.
- Data quality : 0 point, impact confiance uniquement.

## Gouvernance

Les regles sont candidates. Toute modification de seuil, poids ou wording doit etre versionnee et testee. Le score reste une aide a la priorisation, pas une conclusion automatique.
