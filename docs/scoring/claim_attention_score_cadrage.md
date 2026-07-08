# Claim Attention Score IRIS - Rapport de cadrage

> **Statut :** document de cadrage fonctionnel, technique et academique  
> **Perimetre :** aide a la priorisation des dossiers sinistres automobiles  
> **Principe :** decision-support, explicabilite, tracabilite, decision humaine finale

## 1. Resume executif

Le Claim Attention Score IRIS est un dispositif d'aide a la priorisation des
dossiers sinistres automobiles pour BNA Assurances. Il ne constitue ni un score
de fraude, ni une preuve, ni une decision automatique.

Son objectif est d'aider les gestionnaires, analystes et responsables a :

- identifier les dossiers necessitant une attention particuliere ;
- comprendre les raisons du signalement ;
- documenter les limites de confiance ;
- orienter les verifications metier ;
- conserver une tracabilite des signaux et versions.

Le score repose sur une architecture en couches :

```text
Couche 1 - Signaux inspection x sinistre
Couche 2 - Regles metier deterministes
Couche finale - Score de priorisation enrichi par signaux metier
Couche future - Modele d'aide a la priorisation apres labels humains
```

Le vocabulaire autorise est :

```text
signal d'attention
point a verifier
verification suggeree
priorisation
aide a l'analyse
```

Le vocabulaire a eviter est :

```text
fraude detectee
preuve de fraude
client fraudeur
decision automatique
violation confirmee
```

## 2. Positionnement metier

Le Claim Attention Score repond a la question :

```text
Quels dossiers doivent etre examines en priorite, et pourquoi ?
```

Il ne repond pas a :

```text
Ce dossier est-il frauduleux ?
```

La sortie attendue est un niveau d'attention :

```text
Analyse standard
Points a verifier
Examen renforce suggere
Examen prioritaire suggere
```

Chaque signal produit par IRIS reste soumis a l'appreciation du gestionnaire.
Le systeme propose, classe, explique et documente. Il ne decide pas.

Formulation recommandee dans les interfaces :

```text
Les elements presentes constituent une aide a l'analyse. La decision finale
reste sous la responsabilite du gestionnaire.
```

## 3. Fondement sectoriel et reglementaire

Le cadrage IRIS s'inscrit dans une logique de gouvernance, de tracabilite et de
prudence. Les references sectorielles ci-dessous justifient l'existence de
controles data structures, sans autoriser une conclusion automatique.

### 3.1 Cadre CGA et assurance automobile

Le site du Comite General des Assurances reference le Code des assurances et les
rubriques relatives a l'assurance automobile. La page assurance automobile
mentionne la loi n deg 2005-86 du 15 aout 2005, avec des objectifs tels que
l'indemnisation equitable, la transaction amiable et la reduction des delais de
reglement.

Implication IRIS :

```text
IRIS peut documenter des controles de coherence contrat, garantie, chronologie,
delais et historique assurantiel.
```

Limite :

```text
IRIS ne conclut pas a une violation reglementaire.
```

### 3.2 Reference FTUSA

Le CGA presente la FTUSA comme une association professionnelle regroupant des
entreprises d'assurances et de reassurance de droit tunisien, habilitee a
soumettre a l'autorite de tutelle des questions interessant la profession.

Formulation prudente :

```text
Les regles metier IRIS s'appuient sur le cadre reglementaire tunisien, les
pratiques contractuelles de l'assurance automobile et les references
sectorielles disponibles.
```

### 3.3 Gouvernance data

Le CGA a publie en 2025 un reglement portant sur la creation d'une plateforme
dediee a la collecte automatique des donnees devant etre transmises au Comite
General des Assurances par les entreprises d'assurance, de reassurance et les
structures du secteur.

Implication IRIS :

```text
Un systeme data gouverne, versionne, controle et auditable est coherent avec
l'evolution du secteur.
```

## 4. Architecture globale

Architecture logique :

```text
Claim Attention Score IRIS
|
|-- Couche 1 : Signaux inspection x sinistre
|   |-- Inspection -> Sinistre
|   |-- Inspection -> Avenant, apres validation complementaire
|
|-- Couche 2 : Regles metier deterministes
|   |-- Client
|   |-- Contrat
|   |-- Garantie
|   |-- Montant
|   |-- Chronologie
|   |-- Vehicule
|   |-- Tiers / conducteur
|   |-- Geographie, apres audit
|   |-- Qualite des donnees
|
|-- Couche de synthese : Score de priorisation enrichi
|
`-- Couche future : Modele d'aide a la priorisation apres labels humains
```

Principe d'integration :

```text
features -> signaux detailles -> score versionne -> restitution metier
```

Les couches ne doivent pas etre melangees dans une boite noire. Chaque signal
doit rester explicable, versionne et relie a ses sources.

## 5. Etat actuel IRIS

| Composant | Statut | Commentaire |
|---|---|---|
| VHS | Stable | Ne pas modifier dans cette phase |
| Claim Attention Score V1 Candidate | Stable baseline | Score deterministe explicable V1 |
| Feature mart V1 | Stable candidate | Base claim-level pour score et regles |
| Post-inspection Scenario A | Stable candidate | GO technique, mart separe |
| Post-inspection Scenario B | PARTIAL | Readiness-only, pas de points |
| Business Rule Signals V1 | Stable candidate | Signaux deterministes, points candidats |
| Hybrid Score V1 Candidate | Candidate a valider | Score configurable et pondere |
| Couche ML / IA | Future | Apres labels humains uniquement |

Le score hybride ne remplace pas le V1 officiel. Il doit toujours etre filtre
par :

```text
score_version = IRIS_CLAIM_ATTENTION_HYBRID_V1_CANDIDATE
```

dans Power BI, Angular ou toute restitution metier.

## 6. Couche 1 - Signaux inspection x sinistre

### 6.1 Objectif

La couche 1 identifie des situations ou un sinistre ou un mouvement contrat
survient apres une inspection STAFFIM du meme vehicule.

Elle croise :

```text
inspection STAFFIM
defauts techniques documentes
vehicule
sinistre
garantie
montant
delai
avenant eventuel
```

### 6.2 Scenario A - Inspection -> Sinistre

Statut :

```text
GO technique
```

Regle :

```text
Inspection STAFFIM avant sinistre, meme vehicule, delai reel 0-90 jours,
anomalie inspection documentee si disponible.
```

Niveaux de delai :

| Delai | Lecture metier |
|---:|---|
| 0-7 jours | Chronologie post-inspection courte |
| 8-30 jours | Signal post-inspection a examiner |
| 31-90 jours | Contexte technique a examiner avec prudence |

Sorties metier :

```text
Signal post-inspection a examiner
Verification prioritaire suggeree
Contexte technique documente
```

### 6.3 Scenario B - Inspection -> Avenant

Statut :

```text
PARTIAL / readiness-only
```

Ce scenario est metierement interessant, mais il ne doit pas donner de points
tant que le DWH ne permet pas de prouver la nature exacte du mouvement :

```text
garantie ajoutee
garantie supprimee
produit change
formule changee
couverture modifiee
prime modifiee avec justification
```

Sortie autorisee :

```text
Mouvement contrat a verifier
Chronologie avenant-sinistre a examiner
```

Sortie interdite :

```text
couverture opportuniste confirmee
```

### 6.4 Place du VHS

Le VHS peut etre utilise comme contexte technique. Il ne doit pas devenir une
probabilite de fraude, une preuve, ni un signal accusatoire.

## 7. Couche 2 - Regles metier deterministes

La couche 2 transforme des regles de gestion, des controles contractuels, des
pratiques sinistres et des references sectorielles en signaux data
verifiables.

Table actuelle :

```text
mart.fact_claim_business_rule_signal
```

Version actuelle :

```text
IRIS_CLAIM_BUSINESS_RULE_SIGNAL_V1_CANDIDATE
```

### 7.1 Familles actives

Familles deja actives dans le candidat :

| Famille | Statut | Role |
|---|---|---|
| Recurrence client | Active | Historique sinistres client |
| Montant atypique | Active | Comparaison montant / garantie |
| Chronologie | Active | Coherence des dates et delais |
| Qualite donnees | Active a 0 point | Reduit la confiance, pas l'attention |

### 7.2 Familles a completer progressivement

| Famille | Statut recommande | Condition d'activation |
|---|---|---|
| Contrat | A auditer | Avenants et statuts fiables |
| Garantie | A auditer | Couverture et garanties historisees |
| Vehicule | A auditer apres correction DWH | Recurrence vehicule fiable |
| Tiers / conducteur | A auditer | Couverture et qualite des cles |
| Geographie | A activer apres audit GEO | Referentiel GEO stable |
| Documents | Futur | GED ou workflow disponible |

### 7.3 Regles qualite donnees

Les regles qualite donnees ne doivent jamais ajouter de points metier. Elles
abaissent ou documentent la confiance.

Exemples :

```text
client_sk = 0
contrat_sk = 0
vehicule_sk = 0
dates invalides
UNKNOWN geographique
effet migration 2019
```

## 8. Score de priorisation enrichi

Le score hybride actuel est une version candidate configurable et ponderee.

Version :

```text
IRIS_CLAIM_ATTENTION_HYBRID_V1_CANDIDATE
```

Configuration :

```text
config/scoring/claim_attention_hybrid_v1_candidate.json
```

Le fichier JSON controle :

```text
poids par regle
poids par famille
plafonds par famille
plafond global
points post-inspection Scenario A
```

Le score final est borne :

```text
0 <= attention_score <= 100
```

Bareme :

| Score | Niveau |
|---:|---|
| 0-24 | Analyse standard |
| 25-49 | Points a verifier |
| 50-74 | Examen renforce suggere |
| 75-100 | Examen prioritaire suggere |

Statut de validation :

```text
GO technique apres tests et audit notebook
PARTIAL metier tant que les ponderations ne sont pas validees avec BNA
```

## 9. Tables mart

Tables actuelles :

```text
mart.fact_claim_scoring_features
mart.fact_claim_business_rule_signal
mart.fact_post_inspection_attention_signal
mart.fact_claim_attention_score
mart.fact_claim_attention_signal_detail
```

Table future recommandee :

```text
mart.fact_claim_human_review
```

Colonnes possibles :

```text
review_sk
claim_sk
review_status
review_decision
review_reason_code
manager_comment
reviewed_by
reviewed_at
created_at
```

Labels prudents :

```text
Dossier valide apres examen
Complement demande
Transmission a revue approfondie
Dossier non prioritaire apres revue
```

## 10. Explicabilite metier

Chaque dossier doit afficher une synthese lisible.

Exemple :

```text
IRIS a releve plusieurs elements pouvant justifier une verification
complementaire : une chronologie courte, un montant superieur aux dossiers
comparables et une recurrence client sur les derniers mois.
```

Exemples par signal :

```text
Le montant estime est superieur aux dossiers comparables pour la meme garantie.
Un examen du chiffrage est suggere.
```

```text
Un sinistre est survenu peu apres une inspection STAFFIM du meme vehicule. Des
elements techniques documentes peuvent justifier une verification prioritaire.
```

```text
Le client presente plusieurs sinistres sur une periode courte. Cet historique
peut justifier une verification complementaire du dossier.
```

## 11. Qualite et validation

Controles bloquants :

| Controle | Effet |
|---|---|
| Doublon sur grain score | Blocage |
| Score hors 0-100 | Blocage |
| Attention level nul | Blocage |
| Detail points != score | Blocage |
| Business explanation vide | Blocage |
| Vocabulaire accusatoire | Blocage |
| Scenario B donnant des points | Blocage |

Controles de confiance :

| Controle | Effet |
|---|---|
| Dates invalides | Exclusion ou confiance basse |
| Cles critiques manquantes | Confidence LOW ou NOT_READY |
| Source partielle | Limitation documentee |
| Hausse brutale volume signal | Revue metier |

Rapports attendus :

```text
score_distribution_summary.csv
signal_family_distribution.csv
attention_level_distribution.csv
confidence_distribution.csv
duplicate_grain_check.csv
rule_activation_summary.csv
not_ready_reasons.csv
validation_summary.md
```

Notebook de validation :

```text
notebooks/validation_scoring/03_claim_attention_hybrid_score_validation.ipynb
```

## 12. Gouvernance

Chaque composant doit avoir une version et un run ID.

Versions actuelles :

```text
IRIS_CLAIM_ATTENTION_V1_CANDIDATE
IRIS_CLAIM_ATTENTION_FEATURES_V1_CANDIDATE
IRIS_POST_INSPECTION_SIGNAL_V1_CANDIDATE
IRIS_CLAIM_BUSINESS_RULE_SIGNAL_V1_CANDIDATE
IRIS_CLAIM_ATTENTION_HYBRID_V1_CANDIDATE
```

Format run ID :

```text
VERSION_YYYYMMDD_HHMMSS
```

Chaque run doit journaliser :

```text
nombre de lignes lues
nombre de signaux produits
nombre de dossiers scores
nombre de doublons
nombre d'exclusions
distribution des niveaux
resume validation
```

## 13. Couche future - Human-in-the-loop et modele avance

La couche avancee doit rester une perspective controlee.

Nom recommande :

```text
Modele d'aide a la priorisation
```

Nom a eviter :

```text
IA de detection de fraude
```

Condition prealable :

```text
Collecter des revues humaines fiables dans mart.fact_claim_human_review.
```

Approches possibles :

| Niveau | Approche | Statut |
|---:|---|---|
| 1 | Score deterministe explicable | Actuel |
| 2 | Modele supervise apres labels humains | Futur |
| 3 | Detection atypique non supervisee | Exploration seulement |

Sorties autorisees :

```text
Profil atypique a examiner
Priorite estimee pour revue
Dossier propose a l'analyse
```

Sorties interdites :

```text
Fraude detectee par IA
Client fraudeur
Preuve algorithmique
```

## 14. Roadmap recommandee

### Phase 1 - Stabilisation actuelle

```text
Claim Attention Score V1
Regles client / montant / chronologie
Validation technique
Rapports qualite
```

### Phase 2 - Couche 1

```text
Mart post-inspection Scenario A
Audit Scenario B
Explications metier
```

### Phase 3 - Couche 2 complete

```text
Familles contrat, garantie, vehicule, tiers
Audits de couverture
Activation progressive au score
```

### Phase 4 - GEO

```text
Audit geographique
Correction DWH GEO
Activation regles GEO
```

### Phase 5 - Interface

```text
Dashboard Power BI
Ecran detail dossier Angular
Panneau decision
Commentaires gestionnaire
```

### Phase 6 - IA future

```text
Collecte labels humains
Jeu d'apprentissage
Modele supervise explicable
Evaluation metier
```

## 15. Decision de cadrage

La meilleure architecture IRIS est :

```text
un score global prudent
+
des signaux detailles separes
+
des explications metier lisibles
+
une gouvernance humaine
```

Formulation finale recommandee :

```text
Le Claim Attention Score IRIS agrege des signaux deterministes issus de
l'historique client, contrat, vehicule, garantie, montant, chronologie et
inspection STAFFIM afin de proposer un niveau d'attention metier. Chaque signal
est explicable, tracable et soumis a la decision finale du gestionnaire. Le
score ne constitue pas une preuve de fraude et ne remplace pas l'analyse
humaine.
```

## 16. Livrables techniques

Livrables principaux :

```text
docs/scoring/claim_attention_score_cadrage.md
docs/scoring/claim_business_rule_signal_specification.md
docs/scoring/post_inspection_signal_rules_v1.md
config/scoring/claim_attention_hybrid_v1_candidate.json
etl/mart/compute_claim_attention_score_v1_candidate.py
etl/mart/compute_claim_business_rule_signals_v1_candidate.py
etl/mart/compute_post_inspection_attention_signal_v1_candidate.py
etl/mart/compute_claim_attention_hybrid_score_v1_candidate.py
tests/test_claim_attention_score_v1.py
tests/test_claim_business_rule_signals_v1.py
tests/test_post_inspection_attention_signal_v1.py
tests/test_claim_attention_hybrid_score_v1.py
notebooks/validation_scoring/03_claim_attention_hybrid_score_validation.ipynb
data/quality_reports/scoring/
```

Commits recommandes :

```text
1. Claim Attention Score V1
2. Post-inspection signals
3. Business rules layer
4. Hybrid score candidate
5. Documentation and validation notebooks
```

Ne jamais utiliser :

```text
git add .
```

## 17. References

- CGA - Code des assurances : https://www.cga.gov.tn/index.php?L=0&id=28
- CGA - Assurance Automobile : https://www.cga.gov.tn/index.php?L=0&id=117
- CGA - Federation Tunisienne des Societes des Assurances : https://www.cga.gov.tn/index.php?L=0&id=64
- CGA - Reglement N deg 02/2025, collecte automatique des donnees : https://www.cga.gov.tn/index.php?L=0&cHash=234067885baaef799a6589af9f7ad5b3&id=144&tx_ttnews%5Btt_news%5D=409
