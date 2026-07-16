# KPIs de soutenance — IRIS Auto Fraud

> Valeurs mesurées le 15/07/2026 sur la base de production locale.
> Runs de référence : `IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE_20260713_222301` (sinistres)
> et `VHS_BALANCED_V4_CANDIDATE_20260714_061541` (véhicules).

## Principe de sélection

Un jury pose trois questions ; chaque famille de KPIs répond à l'une d'elles :

| Question du jury | Famille de KPIs |
|---|---|
| « À quoi ça sert concrètement ? » | A. KPIs métier (pilotage) |
| « Peut-on faire confiance aux données ? » | B. KPIs qualité de données |
| « Le modèle est-il rigoureux ? » | C. KPIs modèle |

Règle de présentation : **3 à 4 KPIs maximum sur la slide principale** (famille A),
les familles B et C en slides d'appui ou en annexe.

---

## A. KPIs métier — pilotage stratégique

### A1. Taux de ciblage prioritaire — **0,20 %**
- **Formule** : dossiers « Examen prioritaire » / dossiers auto scorés = 752 / 367 464
- **Pourquoi stratégique** : c'est le KPI fondateur du projet. Un service anti-fraude ne peut
  pas relire 367 464 dossiers ; IRIS en isole 752, soit une file de travail humainement
  traitable (~3 dossiers/jour ouvré sur un an pour un gestionnaire).
- **Phrase jury** : « IRIS transforme un volume impossible à auditer en une file de travail
  de 752 dossiers, sans écarter le reste : 15 % supplémentaires restent sous vigilance graduée. »

### A2. Exposition financière sous vigilance — **40,7 M TND (5,7 % de l'exposition)**
- **Formule** : Σ montants des dossiers « prioritaire + renforcé » / Σ montants totaux
  = (1,96 M + 38,8 M) / 711,9 M TND
- **Pourquoi stratégique** : traduit le score en langage financier — 4,2 % des dossiers
  concentrent 40,7 M TND d'exposition à examiner. C'est l'argument budgétaire du projet :
  même un faible taux de fraude évitée sur ce périmètre couvre le coût de la plateforme.
- **Phrase jury** : « Le ciblage concentre l'effort humain là où se trouve l'argent :
  40,7 millions de dinars d'exposition sur seulement 4,2 % des dossiers. »

### A3. Pyramide d'attention (distribution du triage)
| Niveau | Dossiers | Part | Exposition (TND) |
|---|---|---|---|
| Examen prioritaire | 752 | 0,20 % | 1 963 955 |
| Examen renforcé | 14 613 | 3,98 % | 38 783 501 |
| Points à vérifier | 56 900 | 15,5 % | 138 587 467 |
| Analyse standard | 295 199 | 80,3 % | 532 541 177 |
- **Pourquoi stratégique** : montre que le système est **gradué** et non binaire
  (fraude/pas fraude). Aucun dossier n'est « acquitté » par la machine : la décision
  finale reste humaine (principe human-in-the-loop).
- **Phrase jury** : « La pyramide garantit qu'aucun dossier n'est écarté par l'algorithme ;
  elle hiérarchise l'ordre de passage devant le gestionnaire. »

### A4. Taux de véhicules inspectés nécessitant une action — **67,3 %**
- **Formule** : décisions VHS ≠ OK / inspections scorées = (116 + 25 + 50) / 284
  (DÉGRADÉ 116, IMMOBILISÉ 25, CRITIQUE 50 — score santé moyen 66/100)
- **Pourquoi stratégique** : relie l'état technique du véhicule au risque sinistre —
  un véhicule déjà dégradé avant sinistre est un contexte précieux pour la revue du dossier.
- **Phrase jury** : « Le VHS ajoute une dimension que le dossier seul ne montre pas :
  l'état réel du véhicule constaté en atelier, résumé en un score 0–100. »

---

## B. KPIs qualité de données — confiance

### B1. Indice de confiance des dossiers scorés — **80,2 % HIGH**
- **Formule** : répartition du `confidence_level` calculé par dossier
  (HIGH 294 713 · MEDIUM 72 736 · LOW 15)
- **Pourquoi stratégique** : le système **auto-évalue** la fiabilité de chaque score selon
  la complétude des jointures (clés manquantes, dimensions inconnues). Un score n'est jamais
  présenté sans son niveau de confiance — honnêteté algorithmique.
- **Phrase jury** : « Chaque score est accompagné de sa propre fiabilité : 80 % des dossiers
  sont scorés sur données complètes, et les 20 % restants sont signalés comme tels au gestionnaire. »

### B2. Couverture référentielle du DWH — **100 % (0 clé orpheline)**
- **Formule** : lignes de faits avec FK résolue / lignes de faits totales, après audit
  (381 893 sinistres · 447 585 contrats · 461 882 clients · 128 035 véhicules)
- **Pourquoi stratégique** : c'est le socle. Prouvé par un **audit automatisé rejouable**
  (`etl/dwh/audit_etl_quality_completeness.py`) intégré comme gate au pipeline : le chargement
  échoue si la qualité régresse.
- **Phrase jury** : « La qualité n'est pas vérifiée une fois : elle est un portail bloquant
  du pipeline, rejoué à chaque chargement. »

### B3. Traçabilité des scores — **100 % versionnés, 0 écrasement**
- **Formule** : tout score porte (score_version, score_run_id) ; les décisions humaines
  sont en append-only avec lien de correction (`corrects_decision_id`).
- **Pourquoi stratégique** : exigence d'auditabilité assurantielle — on peut rejouer
  l'historique complet : quel score, quelle version du moteur, qui a décidé quoi, et
  quelles corrections ont eu lieu, sans qu'aucune donnée n'ait jamais été modifiée.
- **Phrase jury** : « Toute décision — machine ou humaine — est datée, versionnée et
  corrigeable sans effacement : le dossier est défendable devant un auditeur. »

---

## C. KPIs modèle — rigueur technique

### C1. Cohérence score / réalité physique (VHS V4) — **100 %**
- **Formule** : véhicules à score 0 qui sont effectivement non roulants / véhicules à score 0
  = 4/4 (en V3 : 8 des 21 véhicules à 0 roulaient encore — incohérence corrigée)
- **Pourquoi stratégique** : montre la démarche d'**itération critique** V3 → V4 :
  détection d'une saturation d'échelle, correction par plafonds par système fonctionnel
  (fin du double comptage frein/suspension) et plancher roulable à 5 points.
- **Phrase jury** : « Nous avons détecté que l'échelle saturait à zéro, diagnostiqué le
  double comptage par système mécanique, et corrigé : en V4, un score nul signifie
  toujours un véhicule hors d'état de rouler. »

### C2. Architecture de score hybride — 3 étages validés séparément
- **Formule** : score final = règles métier (explicables) + signaux post-inspection
  + anomalie ML (Isolation Forest), chaque étage ayant son run et son rapport de validation.
- **Pourquoi stratégique** : répond à l'objection classique « boîte noire » — le ML
  n'est qu'un étage complémentaire ; chaque signal affiché au gestionnaire est traçable
  à une règle documentée (catalogue V2 : seuils sourcés, grain validé, golden tests).
- **Phrase jury** : « Le gestionnaire ne voit jamais un score brut : il voit les raisons,
  chacune rattachée à une règle du catalogue ou à un facteur ML explicité. »

### C3. Non-régression automatisée — **183 tests verts**
- **Formule** : suite pytest couvrant parsing de dates, règles métier (golden tests),
  API en lecture seule (scan anti-écriture), chargeurs de dimensions.
- **Pourquoi stratégique** : garantit que les scores publiés ne dérivent pas silencieusement
  quand le code évolue — dont un test qui interdit structurellement toute écriture SQL
  hors du chemin de validation humaine.
- **Phrase jury** : « La contrainte lecture seule de l'API n'est pas une convention :
  c'est un test qui fait échouer la build si on la viole. »

### C4. Performance de restitution — **< 100 ms par page**
- **Formule** : latence de l'endpoint `/api/summary` mesurée à 83 ms après indexation
  composite et purge des runs obsolètes (contre ~4 s avant optimisation).
- **Pourquoi stratégique** : condition d'adoption — un outil de triage lent n'est pas
  utilisé. Montre la maîtrise de la chaîne complète (index PostgreSQL → API → Angular).
- **Phrase jury** : « L'écran du gestionnaire répond en moins de 100 millisecondes
  sur 367 000 dossiers scorés. »

---

## Slide de synthèse recommandée (« IRIS en 4 chiffres »)

| | |
|---|---|
| **367 464** | sinistres auto analysés automatiquement |
| **0,20 %** | ciblés en examen prioritaire — une file de travail humaine réaliste |
| **40,7 M TND** | d'exposition financière concentrée sous vigilance |
| **100 %** | des scores traçables : version, run, décision humaine corrigeable sans effacement |

## Pièges à éviter à l'oral

1. **Ne pas annoncer un « taux de fraude détectée »** : sans vérité terrain labellisée,
   ce chiffre n'existe pas — IRIS mesure un *taux de ciblage*, pas un taux de détection.
   L'assumer explicitement est une force académique, pas une faiblesse.
2. **Ne pas présenter le score comme une décision** : le vocabulaire officiel est
   « attention suggérée » ; la décision est toujours humaine et auditée.
3. **Toujours donner le dénominateur** : « 752 dossiers » ne veut rien dire seul ;
   « 752 sur 367 464 » raconte l'histoire.
4. Si le jury demande la validation externe : V4 VHS et le score hybride sont des
   **candidats** en attente de validation métier BNA — dire « candidat validé
   techniquement, en attente de validation métier » est la réponse exacte.
