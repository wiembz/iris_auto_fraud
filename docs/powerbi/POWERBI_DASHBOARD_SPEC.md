# IRIS Claim Attention - Specification du dashboard Power BI (V1 : 5 pages + 1 masquee)

> **Statut :** specification de conception consolidee (a implementer)
> **Public :** management sinistres, analystes, equipe data
> **Principe :** decision-support, wording non accusatoire, filtrage obligatoire par `score_version`
> **Regle de dimensionnement :** une page = une question qu'un utilisateur reel se pose regulierement. La profondeur vient des interactions (drill-through, tooltips, slicers), pas de la multiplication des pages.

## 0. Complementarite avec l'application Angular

Les deux restitutions lisent le meme mart mais ne font pas le meme metier :

| | Angular (operationnel) | Power BI (analytique) |
|---|---|---|
| Utilisateur | Gestionnaire | Management, analystes |
| Geste | Agir sur UN dossier / UNE fiche (worklist, detail client, vehicule, inspection, checklist) | Comprendre le portefeuille (tendances, segments, agregats, gouvernance) |
| Grain | Dossier et fiches individuelles | Agregats -> drill jusqu'a sinistre x garantie (page masquee uniquement) |
| Acces | API Flask read-only | Vues mart dediees, lecture seule |

Regles anti-duplication :

- Power BI n'a **aucun bouton d'action** ni vocation de traitement de dossier ;
- Power BI ne presente **jamais une fiche individuelle** (client, vehicule, inspection) : la fiche vit dans Angular, la cohorte vit dans Power BI ;
- Angular n'embarque **aucune analytique de portefeuille** (pas de recalcul, conforme au roadmap) ;
- La page masquee de drill-through est la seule restitution au grain sinistre x garantie du projet, analytique et sans actions.

## 1. Principes de conception

### 1.1 Storytelling en entonnoir (5 questions)

```text
1. Ou en est le portefeuille ?            -> P1 Vue executive
2. Pourquoi et quels dossiers ?           -> P2 Claim Attention - signaux
3. Qui concentre l'activite ?             -> P3 Clients et recurrence
4. Que dit le contexte technique ?        -> P4 Vehicule et inspections
5. Peut-on se fier a ces chiffres ?       -> P5 Qualite et gouvernance
   (Que dit CE dossier ?                  -> PM Detail dossier, masquee, drill-through)
```

### 1.2 Standards visuels

- **Lecture en Z** : KPI cards en haut a gauche, visuel principal au centre, detail en bas.
- **Densite maitrisee** : maximum 6 visuels par page hors slicers.
- **Semantique couleur unique** (echelle de priorite, palette daltonien-compatible, pas de connotation accusatoire) :
  - Analyse standard : gris-bleu `#8FA6BC`
  - Points a verifier : jaune ocre `#E8B54D`
  - Examen renforce suggere : orange `#D97B29`
  - Examen prioritaire suggere : rouge brique `#B3392F`
  - Confiance / qualite : echelle bleue independante (jamais celle de l'attention).
- **Wording** : uniquement le vocabulaire autorise (signal d'attention, verification suggeree, dossier a examiner). Aucun titre ne mentionne "fraude". Reprendre les libelles metier (`label_business`, `business_explanation`) tels quels : ils sont deja testes non accusatoires. Bandeau permanent en pied de page : *"Aide a l'analyse - la decision finale reste sous la responsabilite du gestionnaire."*
- **Slicers communs** (panneau lateral synchronise) : periode (date sinistre), niveau d'attention, garantie, niveau de confiance. `score_version` est un **filtre de rapport verrouille**, affiche mais non modifiable.
- **Jamais de camembert** pour les niveaux d'attention (distribution ~86/14/0,2 % illisible en secteurs) ; jamais de jauge (aucune cible metier validee) ; pas de carte avant `GEO_READY`.
- **Grains** : P1-P5 au grain **dossier** (regle ADR : MAX des garanties, pas de somme). Seule la page masquee PM descend au grain **sinistre x garantie**. Ne jamais melanger les deux grains dans un meme visuel.
- Mode clair uniquement en V1 (imprimable en comite).

### 1.3 Modele de donnees (etoile Power BI)

```text
dim_date ----------.
dim_garantie ------+--> fact_dossier_attention (grain dossier, V2 dossier candidate)
dim_client --------+--> fact_claim_attention_score (grain sinistre x garantie)
dim_vehicule ------+--> fact_claim_attention_signal_detail (grain signal)
dim_geo (freinee) -+--> fact_post_inspection_attention_signal
                   +--> fact_claim_ml_anomaly_signal
                   +--> fact_inspection_vehicule / fact_inspection_checkpoint
                   '--> fact_vhs (score vehicule)
Tables deconnectees : dim_score_version (filtre verrouille), dim_run (gouvernance)
```

Relations 1-N depuis les dimensions ; `signal_detail` relie a `attention_score` par `claim_sk` + `score_run_id`. Le rapport lit des **vues dediees** (schema `powerbi_v`, lecture seule) et jamais les tables mart brutes.

### 1.4 Garde-fous data (issus des audits du projet)

1. **Clients non identifies** : exclure `client_sk = 0` (et cles UNKNOWN, effet migration 2019) de toutes les cohortes clients ; afficher en contrepartie le KPI "% de sinistres a client non identifie" pour documenter le perimetre.
2. **Definitions de cohortes alignees sur le catalogue** : "client multisinistre" = seuil du catalogue de regles (`HIST_CLIENT_RECURRENCE_12M` : >= 3 dossiers / 12 mois) ; toute autre fenetre (24 mois...) doit etre etiquetee comme telle. Le BI et le score racontent les memes definitions (`threshold_source`).
3. **Appariement vehicule** : la recurrence vehicule et le taux "vehicules inspectes parmi les sinistres" restent des indicateurs de qualite (P5) tant que l'audit d'appariement vehicule du DWH n'est pas termine - pas des KPI de tete.
4. Toute mesure filtre implicitement `score_version` via le filtre verrouille - jamais d'agregation multi-versions ni multi-runs.

## 2. Mesures DAX de base

```dax
Dossiers Scores = DISTINCTCOUNT ( fact_dossier_attention[claim_root_id] )

Score Moyen = AVERAGE ( fact_dossier_attention[attention_score] )
Score Median = MEDIAN ( fact_dossier_attention[attention_score] )

Dossiers Haute Attention =
CALCULATE ( [Dossiers Scores],
    fact_dossier_attention[attention_level]
        IN { "Examen renforce suggere", "Examen prioritaire suggere" } )

% Haute Attention = DIVIDE ( [Dossiers Haute Attention], [Dossiers Scores] )

Points Attribues = SUM ( fact_claim_attention_signal_detail[awarded_points] )

Contribution Famille % =
DIVIDE ( [Points Attribues],
    CALCULATE ( [Points Attribues], ALL ( fact_claim_attention_signal_detail[rule_family] ) ) )

Taux Activation Regle =
DIVIDE (
    DISTINCTCOUNT ( fact_claim_attention_signal_detail[claim_sk] ),
    CALCULATE ( DISTINCTCOUNT ( fact_claim_attention_score[claim_sk] ), ALL () ) )

% Confiance Haute =
DIVIDE (
    CALCULATE ( [Dossiers Scores], fact_dossier_attention[confidence_level] = "HIGH" ),
    [Dossiers Scores] )

-- Clients (toujours hors client_sk = 0)
Clients Identifies =
CALCULATE ( DISTINCTCOUNT ( fact_dossier_attention[client_sk] ),
    fact_dossier_attention[client_sk] <> 0 )

Clients Multisinistres 12M =
CALCULATE ( DISTINCTCOUNT ( smart_features[client_sk] ),
    smart_features[client_claim_count_12m] >= 3,
    smart_features[client_sk] <> 0 )

% Sinistres Client Non Identifie =
DIVIDE (
    CALCULATE ( [Dossiers Scores], fact_dossier_attention[client_sk] = 0 ),
    CALCULATE ( [Dossiers Scores], ALL ( fact_dossier_attention[client_sk] ) ) )

-- Inspections STAFIM
Inspections = DISTINCTCOUNT ( fact_inspection_vehicule[inspection_sk] )
Vehicules Inspectes = DISTINCTCOUNT ( fact_inspection_vehicule[vehicule_sk] )
Taux Checkpoints Renseignes =
DIVIDE (
    CALCULATE ( COUNTROWS ( fact_inspection_checkpoint ),
        NOT ISBLANK ( fact_inspection_checkpoint[checkpoint_value] ) ),
    COUNTROWS ( fact_inspection_checkpoint ) )

Delai Post-Inspection Moyen = AVERAGE ( fact_post_inspection[delay_days] )

-- ML (signal parallele)
Dossiers ML Top 5% =
CALCULATE ( DISTINCTCOUNT ( fact_ml_anomaly[claim_sk] ),
    fact_ml_anomaly[anomaly_percentile] >= 0.95 )

Overlap ML x Metier % =
VAR TopML = CALCULATETABLE ( VALUES ( fact_ml_anomaly[claim_sk] ),
    fact_ml_anomaly[anomaly_percentile] >= 0.95 )
VAR HauteAttention = CALCULATETABLE ( VALUES ( fact_dossier_attention[claim_root_id] ),
    fact_dossier_attention[attention_level]
        IN { "Examen renforce suggere", "Examen prioritaire suggere" } )
RETURN DIVIDE ( COUNTROWS ( INTERSECT ( TopML, HauteAttention ) ), COUNTROWS ( TopML ) )
```

## 3. Pages V1

### P1 - Vue executive : "Ou en est le portefeuille ?"

Grain : dossier. En 10 secondes, le management sait combien de dossiers demandent de l'attention et si la situation evolue. Absorbe l'ancien "portefeuille sinistres" (volumes, montants, garanties, tendances).

| Zone | Visuel | Contenu |
|---|---|---|
| Bandeau KPI | 5 cards | Dossiers scores (231 496) ; % haute attention ; dossiers examen prioritaire ; **score median** (pas la moyenne : distribution tres asymetrique) ; montant declare cumule de la periode |
| Centre gauche | Histogramme colonnes | Distribution du score 0-100 (bins de 5), couleur par niveau - la forme selective du score |
| Centre droit | Barres horizontales 100% | Repartition des 4 niveaux d'attention |
| Bas gauche | Courbe temporelle | Volume de sinistres et volume haute attention par mois, moyenne mobile 3 mois |
| Bas droit | Barres empilees | Niveaux d'attention par garantie (top 8) + montant par garantie en tooltip |

### P2 - Claim Attention, signaux et priorisation : "Pourquoi et quels dossiers ?"

Grain : dossier (details agreges). Le coeur de l'explicabilite. Absorbe l'ancienne page priorisation et l'encart ML.

| Zone | Visuel | Contenu |
|---|---|---|
| Bandeau KPI | 4 cards | Signaux emis ; regles actives ; familles evaluables (3/6 - honnete) ; Overlap ML x haute attention (31,8 %) |
| Centre gauche | Barres horizontales | Contribution de chaque famille au total des points (% du cap consomme en tooltip) |
| Centre droit | Barres horizontales | Taux d'activation par regle (libelle metier `label_business`) |
| Bas gauche | Scatter | Score d'attention (X) x montant (Y), taille = nb garanties, couleur = confiance - repere les hauts-scores / hauts-montants. Drill-through -> PM |
| Bas droit | **Encart ML** : scatter compact | Percentile ML (X) x score metier (Y), 4 quadrants annotes ; la zone "ML seul" = valeur ajoutee du signal parallele. Bandeau : *"Signal d'atypicite statistique (Isolation Forest, percentile). Ni probabilite de fraude, ni decision."* |

Insight a faire ressortir : les hauts scores viennent de la **convergence de plusieurs familles** (effet des plafonds), pas d'une seule regle.

### P3 - Clients et recurrence : "Qui concentre l'activite ?"

Grain : client (cohortes agregees, jamais de fiche individuelle - la fiche client vit dans Angular). Toujours hors `client_sk = 0`.

| Zone | Visuel | Contenu |
|---|---|---|
| Bandeau KPI | 5 cards | Clients avec sinistre ; clients multisinistres (>= 3 / 12 mois, definition du catalogue) ; sinistres moyens par client ; contrats moyens par client ; **% sinistres a client non identifie** (perimetre documente) |
| Centre gauche | Histogramme | Distribution du nombre de sinistres par client (1 / 2 / 3 / 4 / 5+) - la concentration de la recurrence en un regard |
| Centre droit | **Pareto** | X % des clients concentrent Y % du montant cumule - LE visuel de pilotage |
| Bas gauche | Colonnes | Anciennete client au moment du sinistre (< 3 mois / 3-12 mois / 1-3 ans / 3-5 ans / 5+ ans) - descriptif, sans conclusion sur la faible anciennete |
| Bas droit | Barres empilees | Mono vs multisinistres selon niveau d'attention et montant - la contribution des recurrents aux dossiers a examiner |

Pas de variables sensibles (sexe, age) sauf besoin metier valide et usage strictement descriptif.

### P4 - Vehicule et inspections : "Que dit le contexte technique ?"

Grain : inspection / vehicule. Trois questions techniques condensees en une page (le volume du croisement - 148 signaux - ne justifie pas une page dediee). Scission en pages separees seulement si l'usage le demande.

| Zone | Visuel | Contenu |
|---|---|---|
| Bandeau KPI | 5 cards | Inspections ; vehicules inspectes ; % inspections avec defaut ; signaux post-inspection (148) ; delai moyen inspection -> sinistre |
| Centre gauche | **Pareto des defauts** | Top checkpoints non conformes, occurrences, % cumule - quelques defauts concentrent-ils l'essentiel ? |
| Centre droit | Heatmap | Systeme technique (moteur, freinage, suspension, direction, pneumatiques...) x gravite (faible / modere / fort / immobilisant) |
| Bas gauche | Histogramme + barres | Distribution du score VHS 0-100 et repartition des grades A-D (contexte technique du parc, jamais croise avec l'attention dans un meme visuel) |
| Bas droit | Histogramme | Croisement inspection -> sinistre : distribution des delais dans les 3 zones metier (0-7 / 8-30 / 31-90 jours), couleur = confiance (HIGH 25 pts / MEDIUM 15 / LOW 0 en tooltip) |

Notes de bas de page : *"Cette page decrit la couverture et les defauts techniques observes. Elle ne constitue pas une analyse de fraude."* + *"Scenario B (inspection -> avenant) : readiness-only, 0 point."*

### P5 - Qualite et gouvernance : "Peut-on se fier a ces chiffres ?"

La page qui differencie un systeme gouverne d'un prototype. A montrer au jury.

| Zone | Visuel | Contenu |
|---|---|---|
| Bandeau KPI | 4 cards | % confiance haute ; % comparaison affichable (84 %) ; familles evaluables (3/6) ; % sinistres a client non identifie |
| Centre gauche | Barres empilees | Niveaux de confiance par garantie et par periode (reperer les segments fragiles) |
| Centre droit | Matrice | Evaluabilite par famille : evaluable / non evaluable + raison (COMPLETENESS : compteurs documentaires absents ; GEOGRAPHY : referentiel en cours ; DATA_QUALITY : confiance seulement) |
| Bas gauche | Cards gouvernance | `score_version`, `score_run_id`, `rule_catalog_hash` (8 premiers caracteres), date de calcul, nb regles actives |
| Bas droit | Table | Etat de validation des regles : rule_code, threshold_source, validated_by (null = candidat) - miroir du catalogue r2. + indicateurs STAFIM : checkpoints manquants, vehicules non apparies, codes non mappes, dates invalides |

### PM - Detail dossier (page masquee, drill-through) : "Que dit ce dossier ?"

Grain : **sinistre x garantie** - seule restitution du projet a ce grain. Accessible uniquement par drill-through depuis P1/P2 (invisible dans la navigation). Analytique, sans aucune action.

| Zone | Visuel | Contenu |
|---|---|---|
| Bandeau | Cards | Score dossier (MAX garanties), niveau, confiance, date sinistre, nb garanties |
| Centre gauche | **Waterfall** | Decomposition du score : points attribues par famille (caps visibles) -> score final. Le visuel signature de l'explicabilite (detail = score, garanti par les tests) |
| Centre droit | Table | Signaux actives : regle, libelle metier, points bruts vs attribues, `business_explanation` |
| Bas gauche | Cards contextuelles | Post-inspection si present (delai, confiance) ; percentile ML si disponible ; VHS du vehicule - chaque card etiquetee **"contexte, sans points"** |
| Bas droit | Frise temporelle | Debut contrat -> inspection eventuelle -> sinistre -> declaration |

## 4. Navigation et interactions

- Boutons de navigation persistants (bandeau gauche), ordre narratif P1 -> P5.
- Drill-through unique : P1 (histogramme) et P2 (scatter) -> PM.
- Tooltips personnalises sur tout visuel agrege : nb dossiers + score median + top famille.
- Signets : "Vue management" (P1 + P5) / "Vue analyste" (P2-P4).

## 5. Roadmap des extensions (hors V1, documentees mais non construites)

| Extension | Condition d'activation |
|---|---|
| Page Geographie et agences (cartes, gouvernorats) | Decision `GEO_READY` (referentiel dim_geo stabilise et audite) |
| Scission P4 en pages STAFIM / VHS / croisement dediees | Volume d'usage ou de donnees le justifiant |
| Page ML dediee (stabilite inter-runs, comparaison HBOS) | Apres validation metier du signal ML |
| Page Performance du traitement humain (delais de revue, backlog, decisions, pertinence des suggestions) | Existence de `mart.fact_claim_human_review` (boucle human-in-the-loop) - fournira aussi les labels du futur ML supervise |

Formulation soutenance : *"Le dashboard V1 compte 5 pages construites sur les donnees validees ; son extension - geographie, revue humaine - suit le rythme de validation des donnees sous-jacentes, exactement comme le score."*

## 6. Ordre de construction

1. Vues SQL `powerbi_v.*` (dossier, scores garantie, details signaux, clients, inspections, post-inspection, ML, gouvernance).
2. Modele + mesures DAX de base (section 2).
3. Pages : P1 -> P2 -> PM -> P5 -> P3 -> P4.
4. Checklist wording (vocabulaire autorise) avant toute diffusion.
5. Diffusion limitee avec bandeau "version candidate" tant que le statut est BUSINESS_VALIDATION_PARTIAL.
