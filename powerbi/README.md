# Dashboard Power BI IRIS - iris_auto_fraudDASH

Construction **manuelle** dans Power BI Desktop (edition Report Server),
publication sur **Power BI Report Server on-premises**. Aucun mode projet
PBIP, aucune dependance Fabric/cloud.

> Le format projet `.pbip` (dossiers `.Report` / `.SemanticModel`, mode
> "developer") est une fonctionnalite Fabric absente de Power BI Desktop RS.
> Ce n'est pas un choix de confidentialite a arbitrer : ce format ne s'ouvre
> tout simplement pas dans l'edition RS. On construit donc directement le
> `.pbix`, qui lui est nativement supporte par Report Server.

## Ce qui existe deja (ne pas refaire)

- `etl/powerbi/create_powerbi_views.py` + `.sql` : 13 vues **`powerbi_v.*`**
  deja creees et testees sur le DWH PostgreSQL (231 496 dossiers, gouvernance
  complete). Si elles n'existent pas encore : `python etl/powerbi/create_powerbi_views.py`.
- `docs/powerbi/POWERBI_DASHBOARD_SPEC.md` : la specification complete
  (KPIs, visuels, mesures DAX, wording, garde-fous) pour les 5 pages + 1
  masquee. Ce README en est la version "mode d'emploi" pas-a-pas.

Power BI ne doit **jamais** lire les tables `mart.*` ou `dwh.*` directement,
uniquement le schema `powerbi_v`.

## Etape 1 - Nouveau rapport et connexion

1. Ouvrir **Power BI Desktop (edition Report Server)**.
2. Accueil > Obtenir les donnees > **PostgreSQL**.
   - Serveur : `localhost:5432` (ou l'hote reel du DWH)
   - Base de donnees : `iris_auto_fraud`
   - Mode de connexion : **Import** (pas DirectQuery - les vues sont deja
     legeres et Report Server planifie l'actualisation)
   - Si le connecteur reclame Npgsql : Fichier > Options > Parametres
     globaux > Versions du gestionnaire de donnees > installer Npgsql.
3. Dans le navigateur, ouvrir uniquement le schema **`powerbi_v`** et cocher
   les 13 vues : `v_score_version_config`, `v_current_run`,
   `v_claim_attention_guarantee`, `v_dossier_attention`, `v_signal_detail`,
   `v_client_cohort`, `v_inspection`, `v_inspection_checkpoint_defect`,
   `v_vhs_score`, `v_post_inspection_signal`, `v_ml_anomaly`,
   `v_quality_kpis`, `v_governance`.
4. Charger.

## Etape 2 - Modele (vue Modele)

Creer ces relations (glisser-deposer entre colonnes) :

| De | Vers | Cardinalite |
|---|---|---|
| `v_claim_attention_guarantee[claim_root_id]` | `v_dossier_attention[claim_root_id]` | N:1 |
| `v_signal_detail[claim_root_id]` | `v_dossier_attention[claim_root_id]` | N:1 |
| `v_ml_anomaly[claim_root_id]` | `v_dossier_attention[claim_root_id]` | N:1 |
| `v_dossier_attention[client_sk]` | `v_client_cohort[client_sk]` | N:1 |
| `v_post_inspection_signal[claim_sk]` | `v_claim_attention_guarantee[claim_sk]` | N:1 |

`v_inspection`, `v_inspection_checkpoint_defect`, `v_vhs_score`, `v_governance`,
`v_quality_kpis`, `v_score_version_config`, `v_current_run` restent des tables
independantes (pas de relation requise pour la V1).

## Etape 3 - Colonnes calculees utiles (optionnel mais recommande)

Dans `v_dossier_attention`, Nouvelle colonne :

```dax
score_bin = INT('v_dossier_attention'[dossier_attention_score] / 5) * 5

claim_month =
IF(
    ISBLANK('v_dossier_attention'[claim_date]), BLANK(),
    DATE(YEAR('v_dossier_attention'[claim_date]), MONTH('v_dossier_attention'[claim_date]), 1)
)
```

Dans `v_client_cohort` :

```dax
tranche_sinistres =
IF('v_client_cohort'[dossier_count] >= 5, "5+", FORMAT('v_client_cohort'[dossier_count], "0"))
```

## Etape 4 - Mesures DAX

Creer une table cachee `_Mesures` (Accueil > Entrer des donnees, une seule
colonne vide) pour ranger toutes les mesures proprement, puis copier ces
mesures (clic droit sur `_Mesures` > Nouvelle mesure) :

```dax
Dossiers Scores = DISTINCTCOUNT('v_dossier_attention'[claim_root_id])

Dossiers Haute Attention =
CALCULATE([Dossiers Scores],
    'v_dossier_attention'[dossier_attention_level]
        IN {"Examen renforce suggere", "Examen prioritaire suggere"})

Pct Haute Attention = DIVIDE([Dossiers Haute Attention], [Dossiers Scores])

Score Median = MEDIAN('v_dossier_attention'[dossier_attention_score])

Montant Sinistres = SUM('v_dossier_attention'[dossier_claim_amount])

Pct Confiance Haute =
DIVIDE(
    CALCULATE([Dossiers Scores], 'v_dossier_attention'[confidence_level] = "HIGH"),
    [Dossiers Scores])

Lignes Garantie = COUNTROWS('v_claim_attention_guarantee')

Signaux Emis = COUNTROWS('v_signal_detail')

Points Attribues = SUM('v_signal_detail'[points])

Dossiers Avec Signal = DISTINCTCOUNT('v_signal_detail'[claim_root_id])

Clients Identifies = COUNTROWS('v_client_cohort')

Clients Multisinistres 12M =
CALCULATE(COUNTROWS('v_client_cohort'), 'v_client_cohort'[is_multiclaim_12m] = TRUE())

Montant Cumule Clients = SUM('v_client_cohort'[total_claim_amount])

Inspections = COUNTROWS('v_inspection')

Pct Inspections Avec Defaut =
DIVIDE(
    CALCULATE(COUNTROWS('v_inspection'), 'v_inspection'[defect_count] > 0),
    COUNTROWS('v_inspection'))

Defauts Observes = SUM('v_inspection_checkpoint_defect'[defect_count])

Inspections VHS = COUNTROWS('v_vhs_score')

Score VHS Moyen = AVERAGE('v_vhs_score'[vhs_final_score])

Signaux Post Inspection = COUNTROWS('v_post_inspection_signal')

Delai Moyen Inspection Sinistre = AVERAGE('v_post_inspection_signal'[days_inspection_to_claim])

Dossiers ML Top 5 Pct =
CALCULATE(DISTINCTCOUNT('v_ml_anomaly'[claim_sk]), 'v_ml_anomaly'[anomaly_percentile_score] >= 0.95)

Pct Client Inconnu = MAX('v_quality_kpis'[pct_unknown_client])
Pct Dates Invalides = MAX('v_quality_kpis'[pct_invalid_dates])
Pct Migration 2019 = MAX('v_quality_kpis'[pct_migration_2019])
```

Appliquer les formats : pourcentages -> `0,00%` ; scores/montants -> `# ##0`.

## Etape 5 - Theme du rapport

Affichage > Personnaliser le theme actuel > Couleurs, ou importer un theme
JSON avec ces couleurs (Affichage > Parcourir les themes > Parcourir) :

```json
{
  "name": "IrisTheme",
  "dataColors": ["#8FA6BC", "#E8B54D", "#D97B29", "#B3392F",
                 "#2C6E8F", "#7BA88F", "#5B6E82", "#C9A66B"]
}
```

Semantique fixe pour toutes les pages : Analyse standard = gris-bleu
`#8FA6BC`, Points a verifier = ocre `#E8B54D`, Examen renforce = orange
`#D97B29`, Examen prioritaire = rouge brique `#B3392F`. Confiance/qualite :
degrade bleu separe (`#2C6E8F`), jamais la meme echelle que l'attention.

## Etape 6 - Construire les pages (une par une)

Detail complet (visuels, champs exacts, zone de l'ecran) dans
`docs/powerbi/POWERBI_DASHBOARD_SPEC.md`, section 3. Resume par page :

### P1 - Vue executive
5 cartes KPI (`Dossiers Scores`, `Pct Haute Attention`, `Dossiers Haute
Attention`, `Score Median`, `Montant Sinistres`) + histogramme
`score_bin` x `Dossiers Scores` + barres 100% `dossier_attention_level` +
courbe `claim_month` x `Dossiers Scores`/`Dossiers Haute Attention` + barres
empilees `code_garantie` x `attention_level`.

### P2 - Claim Attention, signaux
Cartes (`Signaux Emis`, `Points Attribues`, `Dossiers Avec Signal`,
`Dossiers ML Top 5 Pct`) + barres `signal_family` x `Points Attribues` +
barres `signal_label` x `Dossiers Avec Signal` + nuage de points
`dossier_attention_score` x `dossier_claim_amount` + nuage de points
`anomaly_percentile_score` x score dossier (via relation ML->dossier).
Zone de texte : *"Signal d'atypicite statistique (Isolation Forest,
percentile). Ni probabilite de fraude, ni decision."*

### P3 - Clients et recurrence
Cartes (`Clients Identifies`, `Clients Multisinistres 12M`, `Montant Cumule
Clients`, `Pct Client Inconnu`) + histogramme `tranche_sinistres` +
barres `is_multiclaim_12m` x `Dossiers Haute Attention` + table triee par
`total_claim_amount` (Pareto de concentration).

### P4 - Vehicule et inspections
Cartes (`Inspections`, `Pct Inspections Avec Defaut`, `Score VHS Moyen`,
`Signaux Post Inspection`, `Delai Moyen Inspection Sinistre`) + Pareto
`checkpoint_libelle` x `Defauts Observes` + colonnes `safety_grade` x
`Inspections VHS` + colonnes `delay_bucket` x `Signaux Post Inspection` +
table du croisement inspection -> sinistre.

### P5 - Qualite et gouvernance
Cartes (`Pct Confiance Haute`, `Pct Client Inconnu`, `Pct Dates Invalides`,
`Pct Migration 2019`) + barres empilees `code_garantie` x
`confidence_level` + table `v_governance` (component, version, run_id,
row_count) + zone de texte methodologique.

### PM - Detail dossier (masquee, drill-through)
Creer la page, puis **Format de la page > Visibilite de la page > Masquer**.
Glisser `v_dossier_attention[claim_root_id]` dans le volet "Ajouter des
champs d'extraction" pour l'activer comme cible de drill-through. Contenu :
graphique cascade (waterfall) `signal_family` x `Points Attribues`, table des
signaux avec `business_explanation`, table des garanties du dossier.
Une fois active, clic droit sur un point de P1/P2 > Explorer > PM.

## Etape 7 - Enregistrer et publier

1. Fichier > Enregistrer sous > `iris_auto_fraudDASH.pbix` dans ce dossier.
2. Publication Report Server : Fichier > Enregistrer une copie > **Power BI
   Report Server**, choisir le dossier du portail cible, ou uploader
   directement le `.pbix` via le portail web du serveur.
3. Sur le serveur, planifier l'actualisation des donnees (identifiants
   PostgreSQL stockes cote serveur, pas dans le fichier).

## Regles de gouvernance a respecter pendant la construction

- Le rapport ne lit QUE les vues `powerbi_v.*`, jamais les tables `mart.*`/`dwh.*`.
- La version de score est verrouillee cote SQL
  (`powerbi_v.v_score_version_config`) : pour changer de version (Hybrid,
  V2 quand valides metier), modifier cette vue en base, pas le rapport.
- Wording non accusatoire : reprendre les libelles du mart tels quels
  (`signal_label`, `business_explanation`) - deja testes. Aucun titre de
  visuel ne mentionne la fraude.
- Bandeau permanent en bas de chaque page : *"Aide a l'analyse - la decision
  finale reste sous la responsabilite du gestionnaire."*
- Pas de carte geographique tant que la decision `GEO_READY` n'est pas prise.
- Diffusion limitee avec mention "version candidate" tant que le statut est
  `BUSINESS_VALIDATION_PARTIAL`.
