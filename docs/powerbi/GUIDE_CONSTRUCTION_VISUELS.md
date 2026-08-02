# Guide de construction pas-à-pas — 5 pages Power BI Desktop

> À suivre directement dans Power BI Desktop (fichier irisdash2.pbix, déjà ouvert).
> Pour chaque visuel : type exact à choisir dans le volet Visualisations, puis champs
> à glisser dans quel emplacement. Les noms de champs sont ceux du modèle actuel
> (déjà renommés en vocabulaire métier).

## Avant de commencer

1. Crée 5 pages vides, renomme-les dans cet ordre : `Vue Générale`, `Vue Dossiers`, `Vue Clients`, `Vue Véhicule`, `Vue Qualité et Gouvernance` (clic droit sur l'onglet en bas → Renommer).
2. Sur chaque page, ajoute un titre de page en haut (zone de texte) : le titre en gras + le sous-titre en italique dessous (voir chaque section).
3. Palette de couleurs à utiliser partout où "Catégorie De Priorité" apparaît :
   - Analyse standard → `#8FA6BC` (gris-bleu)
   - Points à vérifier → `#E8B54D` (jaune ocre)
   - Examen renforcé suggéré → `#D97B29` (orange)
   - Examen prioritaire suggéré → `#B3392F` (rouge brique)

---

## PAGE 1 — Vue Générale

**Titre :** Vue Générale du Portefeuille
**Sous-titre :** Comment va le portefeuille en ce moment ?

### Bandeau (5 cartes) — zone haute
Visuel : **Carte** (une carte par mesure, alignées horizontalement)
1. Champ : `Dossiers Scores` — étiquette "Dossiers Sinistres"
2. Champ : `Pct Vigilance Elevee` — étiquette "% en Vigilance Élevée" (format %)
3. Champ : `Dossiers Prioritaires` — étiquette "Dossiers Prioritaires"
4. Champ : `Score Median` — étiquette "Priorité Moyenne"
5. Champ : `Montant Sinistres` — étiquette "Montant Total"

### Centre gauche — Histogramme
Visuel : **Graphique en histogramme** (Histogram, dans les visuels natifs ou "Histogram chart" si activé)
- Champ analysé : `Dossiers[Niveau De Priorite Dossier]`
- Nombre de bins : 20 (colonnes de 5)
- Titre du visuel : "Comment se Répartissent les Dossiers ?"

### Centre droit — Barres 100%
Visuel : **Graphique à barres empilées 100%** (100% Stacked Bar Chart)
- Axe Y : `Dossiers[Categorie De Priorite Dossier]`
- Valeurs : `Dossiers Scores`
- Couleur par : `Categorie De Priorite Dossier` (appliquer la palette ci-dessus)
- Titre : "Répartition par Catégorie de Priorité"

### Bas gauche — Courbe temporelle
Visuel : **Graphique en courbes** (Line Chart)
- Axe X : `Calendrier[Mois Annee]` — **trier par** `Calendrier[Annee Mois Tri]` (clic droit sur l'axe → Trier par → Annee Mois Tri) pour avoir un ordre chronologique correct
- Valeurs : `Dossiers Scores` et `Dossiers Vigilance Elevee` (deux courbes)
- Titre : "Évolution dans le Temps"

### Bas droit — Barres par garantie
Visuel : **Graphique à barres groupées** (Clustered Bar Chart)
- Axe Y : `Sinistres par Garantie[Code Garantie]`
- Valeurs : `Dossiers Vigilance Elevee Garantie`
- Info-bulle : ajouter `Montant Garanties Vigilance Elevee`
- Filtre visuel : Top 8 par `Dossiers Vigilance Elevee Garantie`
- Titre : "Quelles Garanties sont les Plus Concernées ?"

---

## PAGE 2 — Vue Dossiers

**Titre :** Dossiers à Examiner
**Sous-titre :** Quels dossiers, et pourquoi ?

### Bandeau (4 cartes)
1. `Points Attention Emis` — "Points Relevés"
2. `Dossiers Avec Point Attention` — "Dossiers avec un Point d'Attention"
3. `Pct Dossiers Niveau` — "% sur le Portefeuille" *(placer ce visuel dans une matrice avec Categorie De Priorite Dossier en ligne, pas en carte seule — cette mesure n'a de sens que par catégorie)*
4. `Dossiers ML Top 5 Pct` — "Recoupement avec l'Analyse Statistique"

### Centre gauche — Barres par famille
Visuel : **Barres horizontales** (Clustered Bar Chart)
- Axe Y : `Points d'Attention Detailles[Famille De Point Attention]`
- Valeurs : `Points Attribues`
- Trier décroissant
- Titre : "Quelles Familles de Critères Reviennent le Plus ?"

### Centre droit — Barres par critère précis
Visuel : **Barres horizontales**
- Axe Y : `Points d'Attention Detailles[Libelle Point Attention]`
- Valeurs : Nombre d'occurrences (Nombre de lignes de la table, ou créer une mesure "Nombre de Criteres" = COUNTROWS si besoin)
- Filtre : Top 8
- Titre : "Quels Critères Précis sont les Plus Fréquents ?"

### Bas gauche — Nuage de points
Visuel : **Nuage de points** (Scatter Chart)
- Axe X : `Dossiers[Niveau De Priorite Dossier]`
- Axe Y : `Dossiers[Montant Dossier]`
- Taille des bulles : `Dossiers[Nb Garanties Distinctes]`
- Légende (couleur) : `Dossiers[Fiabilite Analyse]`
- Titre : "Priorité vs Montant : Où Regarder en Premier ?"

### Bas droit — Encart statistique
Visuel : **Nuage de points** (compact)
- Axe X : `Detection Atypicite IA[Indice Ecart Statistique]`
- Axe Y : score métier lié (relier via `Cle Sinistre`, utiliser `Sinistres par Garantie[Niveau De Priorite]`)
- Titre : "Un Second Regard Statistique"
- **Ajouter un bandeau texte en dessous** : *"Complément d'analyse automatisé — ne remplace pas le jugement du gestionnaire."*

---

## PAGE 3 — Vue Clients

**Titre :** Clients et Récurrence
**Sous-titre :** Qui concentre l'activité ?

### Bandeau (5 cartes)
1. `Clients Identifies` — "Clients Identifiés"
2. `Clients Multisinistres 12M` — "Clients Récurrents"
3. `Pct Clients Multi` — "% Récurrents"
4. `Montant Cumule Clients` — "Montant Cumulé"
5. `Pct Client Inconnu` — "% Client Non Identifié"

### Centre gauche — Histogramme
Visuel : **Barres groupées** (Clustered Column Chart)
- Axe X : `Clients[Tranche De Sinistres]`
- Valeurs : Nombre de clients (COUNTROWS(Clients) — créer une mesure simple si besoin)
- Titre : "Combien de Sinistres par Client ?"

### Centre droit — Courbe de concentration
Visuel : **Graphique en courbes**
- Axe X : `Clients[Groupe Concentration]` (trier par `Ordre Decile Pareto`, colonne masquée mais utilisable comme tri)
- Valeurs : `Pct Montant Cumule`
- Titre : "Qui Concentre le Plus d'Activité ?"

### Bas gauche — Ancienneté
Visuel : **Barres groupées**
- Axe X : `Clients[Anciennete Historique Client]` *(colonne créée pendant cette session)*
- Valeurs : Nombre de clients
- Titre : "Depuis Combien de Temps sont-ils Clients ?"

### Bas droit — Récurrents vs priorité
Visuel : **Barres empilées 100%**
- Axe Y : `Clients[Client Multisinistre 12 Mois]`
- Valeurs : `Dossiers Scores` (via la relation Dossiers→Clients)
- Couleur par : `Dossiers[Categorie De Priorite Dossier]`
- Titre : "Les Clients Récurrents ont-ils Plus de Dossiers Prioritaires ?"

---

## PAGE 4 — Vue Véhicule

**Titre :** État des Véhicules
**Sous-titre :** Que disent les contrôles techniques ?

### Bandeau (5 cartes)
1. `Inspections` — "Contrôles Effectués"
2. `Pct Inspections Avec Defaut` — "% avec un Défaut"
3. `Points Attention Post Inspection` — "Points Relevés après Contrôle"
4. `Delai Moyen Inspection Sinistre` — "Délai Moyen Contrôle → Sinistre"
5. `Etat Technique Moyen` — "État Moyen du Parc"

### Centre gauche — Barres des défauts
Visuel : **Barres horizontales**
- Axe Y : `Defauts Inspection[Point De Controle]`
- Valeurs : `Defauts Observes`
- Filtre : Top 8
- Titre : "Quels Points de Contrôle Posent le Plus Problème ?"

### Centre droit — Grille des zones
Visuel : **Tableau ou Matrice** avec mise en forme conditionnelle (dégradé de couleur)
- Lignes : `Defauts Inspection[Zone Controlee]`
- Valeurs : `Nb Defauts` et `Nb Defauts Critiques`
- Mise en forme conditionnelle (dégradé) sur `Nb Defauts Critiques`
- Titre : "Où se Situent les Défauts ?"

### Bas gauche — État du parc
Visuel : **Histogramme + Barres** (deux visuels côte à côte)
- Histogramme : `Etat Technique Vehicule[Score Etat Technique]`
- Barres : `Etat Technique Vehicule[Etat Vehicule]` (axe) x nombre de véhicules
- Titre : "Comment se Répartit l'État des Véhicules ?"

### Bas droit — Délai contrôle→sinistre
Visuel : **Histogramme / Barres groupées**
- Axe X : `Point d'Attention Post Inspection[Libelle Tranche Delai]` *(colonne créée pendant cette session — utiliser celle-ci, pas `Tranche De Delai` qui est masquée)*
- Valeurs : Nombre de cas
- Couleur : `Fiabilite Analyse`
- Titre : "Combien de Temps entre le Contrôle et le Sinistre ?"

---

## PAGE 5 — Vue Qualité et Gouvernance

**Titre :** Fiabilité des Données
**Sous-titre :** Sur quoi peut-on s'appuyer ?

### Bandeau (4 cartes)
1. `Pct Fiabilite Elevee` — "Fiabilité de l'Analyse"
2. `Statut Version` — "Version du Modèle Utilisée"
3. `Gouvernance[Date Calcul]` (Max) — "Date du Dernier Calcul"
4. `Dossiers Couverts` — "Couverture des Données"

### Centre — Table qualité
Visuel : **Table**
- Colonnes : `Indicateurs Qualite[Pct Dates Invalides]`, `Pct Vehicule Manquant`, `Pct Immatriculation Manquante`, `Pct Client Inconnu`
- Titre : "Ce qui est Validé, Ce qui Reste Prudent par Choix"
- **Ne jamais écrire "problème" dans les libellés** — formuler en positif (voir le speech préparé)

### Bas — Cartes de traçabilité
Visuel : **Table ou cartes multiples**
- Champs : `Gouvernance[Libelle Composant]`, `Version`, `Identifiant Run`, `Date Calcul`
- Titre : "Traçabilité du Calcul"
- **Filtrer la ligne vide** : ajouter un filtre visuel "Libelle Composant n'est pas vide"

**Ne pas ajouter** : aucun visuel ni carte sur la fiabilité géographique (`Gouvernorat`/`Région`) sur cette page ni ailleurs — choix assumé et déjà validé.

---

## Après construction : slicers communs (à ajouter sur les 5 pages, panneau latéral)

- `Calendrier[Date]` (slicer période, format plage de dates)
- `Dossiers[Categorie De Priorite Dossier]`
- `Sinistres par Garantie[Code Garantie]`
- `Dossiers[Fiabilite Analyse]`
- Filtre verrouillé (affiché, non modifiable) : `Version du Score[Version Score]` — ajouter comme slicer mais verrouiller via Format → Interactions ou simplement ne pas le rendre interactif.

## Navigation

Ajoute 5 boutons de navigation en haut de chaque page (Insertion → Boutons → Vierge), un par page, dans l'ordre Vue Générale → Vue Dossiers → Vue Clients → Vue Véhicule → Vue Qualité et Gouvernance. Chaque bouton : action "Page", cible = la page correspondante.
