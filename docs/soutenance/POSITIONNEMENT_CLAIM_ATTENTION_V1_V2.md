# Positionnement Claim Attention V1 (prod) vs V2 (candidat)

> Vérifié le 07/08/2026 directement contre le code et la base de données —
> pas seulement documenté, contrôlé.

## Le fait en une phrase

**V1 est en production ; V2 est un candidat qui n'a jamais écrit une seule
ligne en base.** C'est une gouvernance de mise en production, pas une
excuse pour un travail inachevé.

## Preuves vérifiées

1. **V1 est ce que l'API sert réellement** : `backend/config.py`
   (`DEFAULT_SCORE_VERSION = "IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE"`).
   Confirmé en base : `mart.fact_claim_attention_score` ne contient que 3
   variantes de V1 (`..._V1_CANDIDATE`, `..._HYBRID_V1_CANDIDATE`,
   `..._HYBRID_ML_V1_CANDIDATE`) — **aucune ligne `V2` n'existe dans cette
   table**, à aucune date.

2. **V2 est architecturalement en lecture seule** : les scripts
   `etl/mart/compute_claim_attention_score_v2_candidate.py`,
   `compute_claim_attention_dossier_v2_candidate.py`,
   `compute_claim_business_rules_v2_candidate.py` sont des bibliothèques de
   calcul en mémoire (DataFrame in/out), **sans aucune instruction
   `INSERT`/`to_sql` vers une table `mart.*`**. Le seul point d'entrée
   exécutable est `validate_claim_attention_dossier_v2_readonly.py`, dont le
   nom même l'indique : il ne produit que des rapports CSV
   (`data/quality_reports/scoring/claim_dossier_v2_validation/`), jamais
   d'écriture en base. On ne pourrait pas « pousser V2 en prod par accident »
   — il faudrait écrire du code d'écriture qui n'existe pas.

3. **Le catalogue de règles V2 est explicitement non-validé métier** :
   `config/claim_attention/rules_v2_candidate.json` (6 règles) — **0 règle
   sur 6** porte un `validated_by` renseigné (vérifié aujourd'hui). Chaque
   règle porte aussi `threshold_source` et `grain` (GUARANTEE/DOSSIER) pour
   la traçabilité — la structure est prête pour la validation métier, mais
   la validation elle-même n'a pas eu lieu.

4. **Dernière validation en lecture seule (10/07/2026, à rafraîchir si le
   temps le permet)** : sur 231 496 dossiers, la distribution V2 candidate
   donne 191 605 « Analyse standard », 39 855 « Points à vérifier », 36
   « Examen renforcé suggéré ». Le test golden dossier de référence (score
   exact 67, "Examen renforcé suggéré", top-3 raisons figées) passe
   toujours (31 tests contenant "v2" verts au 07/08/2026).

## Pourquoi c'est une force, pas une faiblesse

Techniquement, rien n'empêchait de basculer `DEFAULT_SCORE_VERSION` vers V2
— le code tourne, les tests passent. Le choix de ne pas le faire tant que
BNA Assurances n'a pas validé les seuils et le grain des règles métier est
une **décision de gouvernance produit délibérée**, pas un blocage technique.
C'est le même principe que la pause humaine sur le DAG Airflow (§2.4) :
IRIS peut faire plus que ce qu'il fait, et choisit de ne pas le faire sans
validation humaine.

## Phrase jury

> « V2 est un candidat complet et testé — mais il n'a jamais écrit une
> seule ligne en base de données. Ce n'est pas un oubli : c'est une
> architecture qui rend la promotion en production impossible sans un acte
> délibéré, et cet acte n'aura lieu qu'après validation des seuils par BNA
> Assurances. »

## Si le jury pose la question piège

**« Pourquoi ne pas avoir juste validé V2 vous-même, vous aviez les
données ? »** — Parce que les seuils de règles métier (montants, délais,
récurrences) engagent la responsabilité de BNA Assurances vis-à-vis de ses
assurés ; les fixer sans mandat métier serait usurper une décision qui ne
m'appartient pas. La traçabilité (`threshold_source`, `validated_by`) est
justement construite pour que cette validation soit possible plus tard,
sans réécrire le catalogue.
