# IRIS Smart Decision Support Roadmap

## Objectif

IRIS Smart Decision Support renforce la plateforme IRIS comme aide a l'analyse des dossiers sinistres automobiles. Le systeme priorise, explique et documente des situations a verifier. Il ne produit pas de conclusion automatique et ne remplace pas la decision du gestionnaire.

## Perimetre inclus

- Stabilisation du socle GEO avant tout signal geographique avance.
- Features metier V2 candidates separees de Claim Attention V1.
- Catalogue de regles metier configurable, pondere et desactivable.
- Score Claim Attention V2 candidate explicable et plafonne par famille.
- Syntheses deterministes basees sur templates metier controles.
- Checklist dynamique et actions suggerees comme aide a la revue.
- Tests de donnees, tests unitaires et garde-fous de langage non accusatoire.

## Perimetre exclu

- Modification du moteur VHS.
- Remplacement ou reecriture de Claim Attention V1.
- Recalcul temps reel depuis Angular ou Flask.
- Geocodage externe ou calcul GPS avant validation GEO.
- Integration forcee du signal ML dans le score principal.
- Decision automatique, preuve, accusation ou probabilite de fraude.

## Ordre d'implementation

1. Conserver le backend read-only utile, notamment l'endpoint agrege de revue dossier.
2. Consolider la decision GEO a partir des artefacts existants.
3. Construire `compute_claim_smart_features_v2_candidate.py` en lecture de features V1 et donnees candidates disponibles.
4. Ajouter le catalogue configurable `rules_v2_candidate.json`.
5. Construire le moteur `compute_claim_attention_score_v2_candidate.py` sans modifier les sorties V1.
6. Ajouter les syntheses deterministes, checklist et actions suggerees.
7. Reprendre le frontend seulement apres validation metier du contenu affiche.

## Gouvernance

Chaque moteur candidat doit exposer un `run_id`, une version, une date de calcul, une reference de donnees et des regles activees. Les resultats doivent etre reproductibles, auditables et accompagnes d'explications metier.

## Regle de decision humaine

Les elements produits par IRIS constituent une aide a l'analyse. Ils sont soumis a l'appreciation du gestionnaire. La decision finale reste humaine.

## Wording autorise

- Dossier a examiner.
- Signal d'attention.
- Verification complementaire.
- Atypicite statistique candidate.
- Contexte a verifier.
- Analyse standard.

## Wording interdit

- Fraude confirmee.
- Preuve de fraude.
- Client fraudeur.
- Coupable.
- Suspect confirme.
- Prediction de fraude.

