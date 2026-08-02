# IRIS — Dashboard Gestionnaire : Pages, visuels et dictionnaire métier

> Version finale post-nettoyage vocabulaire (Niveau De Priorite / Categorie De Priorite /
> Vigilance Elevee / Fiabilite Analyse / Etat Vehicule / Groupe Client...).
> 5 pages, aucune page masquée. Langage 100% gestionnaire, aucun jargon technique visible.

---

## 0. Flux de lecture (5 pages, aucune cachée)

```
1. Vue Générale               → "Comment va le portefeuille en ce moment ?"
2. Vue Dossiers                → "Quels dossiers examiner en priorité, et pourquoi ?"
3. Vue Clients                 → "Quels clients concentrent l'activité ?"
4. Vue Véhicule                → "Que dit l'état technique des véhicules ?"
5. Vue Qualité et Gouvernance   → "Peut-on se fier aux chiffres présentés ?"
```

Navigation libre entre les 5 pages (boutons persistants, pas d'ordre imposé au-delà de la première lecture).
Pas de drill-through, pas de fiche individuelle, pas de page masquée.

**Slicers communs** (panneau latéral, sur toutes les pages) : `Calendrier[Date]` (période), `Categorie De Priorite`, `Code Garantie`, `Fiabilite Analyse`.
**Filtre verrouillé** (affiché, non modifiable) : `Version du Score`.

---

## 1. Vue Générale
**Titre de page :** *Vue Générale du Portefeuille*
**Sous-titre :** *Comment va le portefeuille en ce moment ?*

Grain : Dossiers.

| Zone | Visuel | Titre du visuel | Champs / mesures |
|---|---|---|---|
| Bandeau (5 cartes) | KPI | "Dossiers Sinistres" · "% en Vigilance Élevée" · "Dossiers Prioritaires" · "Priorité Moyenne" · "Montant Total" | `Dossiers Scores`, `Pct Vigilance Elevee`, `Dossiers Prioritaires`, `Score Median`, `Montant Sinistres` |
| Centre gauche | Histogramme | "Comment se Répartissent les Dossiers ?" | `Dossiers[Niveau De Priorite Dossier]` (par tranche de 5) |
| Centre droit | Barres 100% | "Répartition par Catégorie de Priorité" | `Dossiers[Categorie De Priorite Dossier]`, mesure `Dossiers Scores` |
| Bas gauche | Courbe | "Évolution dans le Temps" | Axe `Calendrier[Mois Annee]`, mesures `Dossiers Scores`, `Dossiers Vigilance Elevee` |
| Bas droit | Barres | "Quelles Garanties sont les Plus Concernées ?" | `Sinistres par Garantie[Code Garantie]` (top 8), mesures `Dossiers Vigilance Elevee Garantie`, `Montant Garanties Vigilance Elevee` (info-bulle) |

Cartes avec tendance (comparaison au mois précédent) : `Dossiers Scores M-1`, `Pct Prioritaires M-1`, `Montant Sinistres M-1`.

---

## 2. Vue Dossiers
**Titre :** *Dossiers à Examiner*
**Sous-titre :** *Quels dossiers, et pourquoi ?*

Grain : Dossiers (avec détail des critères).

| Zone | Visuel | Titre du visuel | Champs / mesures |
|---|---|---|---|
| Bandeau (4 cartes) | KPI | "Points Relevés" · "Dossiers avec un Point d'Attention" · "% sur le Portefeuille" · "Recoupement avec l'Analyse Statistique" | `Points Attention Emis`, `Dossiers Avec Point Attention`, `Pct Dossiers Niveau`, `Dossiers ML Top 5 Pct` |
| Centre gauche | Barres | "Quelles Familles de Critères Reviennent le Plus ?" | `Points d'Attention Detailles[Famille De Point Attention]`, mesure `Points Attribues` |
| Centre droit | Barres | "Quels Critères Précis sont les Plus Fréquents ?" | `Points d'Attention Detailles[Libelle Point Attention]` |
| Bas gauche | Nuage de points | "Priorité vs Montant : Où Regarder en Premier ?" | X = `Niveau De Priorite Dossier`, Y = `Montant Dossier`, taille = `Nb Garanties Distinctes`, couleur = `Fiabilite Analyse` |
| Bas droit | Encart | "Un Second Regard Statistique" | X = `Indice Ecart Statistique`, Y = priorité métier. Bandeau : *"Complément d'analyse automatisé — ne remplace pas le jugement du gestionnaire."* |

---

## 3. Vue Clients
**Titre :** *Clients et Récurrence*
**Sous-titre :** *Qui concentre l'activité ?*

Grain : Clients (jamais de fiche individuelle).

| Zone | Visuel | Titre du visuel | Champs / mesures |
|---|---|---|---|
| Bandeau (5 cartes) | KPI | "Clients Identifiés" · "Clients Récurrents" · "% Récurrents" · "Montant Cumulé" · "% Client Non Identifié" | `Clients Identifies`, `Clients Multisinistres 12M`, `Pct Clients Multi`, `Montant Cumule Clients`, `Pct Client Inconnu` |
| Centre gauche | Histogramme | "Combien de Sinistres par Client ?" | `Clients[Tranche De Sinistres]` (1/2/3/4/5+) |
| Centre droit | Courbe cumulée | "Qui Concentre le Plus d'Activité ?" | `Clients[Groupe Concentration]`, mesure `Pct Montant Cumule` |
| Bas gauche | Colonnes | "Depuis Combien de Temps sont-ils Clients ?" | Ancienneté calculée depuis `Clients[Date Premier Sinistre]` |
| Bas droit | Barres | "Les Clients Récurrents ont-ils Plus de Dossiers Prioritaires ?" | `Clients[Groupe Client]` croisé avec `Categorie De Priorite Dossier` et `Montant Dossier` |

---

## 4. Vue Véhicule
**Titre :** *État des Véhicules*
**Sous-titre :** *Que disent les contrôles techniques ?*

Grain : Inspections / Véhicules.

| Zone | Visuel | Titre du visuel | Champs / mesures |
|---|---|---|---|
| Bandeau (5 cartes) | KPI | "Contrôles Effectués" · "% avec un Défaut" · "Points Relevés après Contrôle" · "Délai Moyen Contrôle → Sinistre" · "État Moyen du Parc" | `Inspections`, `Pct Inspections Avec Defaut`, `Points Attention Post Inspection`, `Delai Moyen Inspection Sinistre`, `Etat Technique Moyen` |
| Centre gauche | Barres | "Quels Points de Contrôle Posent le Plus Problème ?" | `Defauts Inspection[Point De Controle]`, mesure `Defauts Observes` |
| Centre droit | Grille couleur | "Où se Situent les Défauts ?" | `Defauts Inspection[Zone Controlee]` × sévérité |
| Bas gauche | Histogramme + barres | "Comment se Répartit l'État des Véhicules ?" | `Etat Technique Vehicule[Score Etat Technique]`, `Etat Technique Vehicule[Etat Vehicule]` |
| Bas droit | Histogramme | "Combien de Temps entre le Contrôle et le Sinistre ?" | `Point d'Attention Post Inspection[Tranche De Delai]`, couleur = `Fiabilite Analyse` |

---

## 5. Vue Qualité et Gouvernance
**Titre :** *Fiabilité des Données*
**Sous-titre :** *Sur quoi peut-on s'appuyer ?*

Page volontairement sobre : présente la rigueur du système, jamais formulée comme un défaut.

| Zone | Visuel | Titre du visuel | Champs / mesures |
|---|---|---|---|
| Bandeau (4 cartes) | KPI | "Fiabilité de l'Analyse" · "Version du Modèle Utilisée" · "Date du Dernier Calcul" · "Couverture des Données" | `Pct Fiabilite Elevee`, `Statut Version`, `Gouvernance[Date Calcul]`, `Dossiers Couverts` |
| Centre | Table | "Ce qui est Validé, Ce qui Reste Prudent par Choix" | `Indicateurs Qualite` (`Pct Dates Invalides`, `Pct Vehicule Manquant`, `Pct Immatriculation Manquante`) — formulé positivement, jamais "problème" |
| Bas | Cartes | "Traçabilité du Calcul" | `Version`, `Identifiant Run`, `Date Calcul`, nombre de règles actives |

Aucune donnée géographique de fiabilité affichée sur cette page (ni ailleurs) — `Gouvernorat`/`Région` restent des axes d'analyse descriptifs normaux sur les autres pages, sans indicateur de qualité associé.

---

## 6. Dictionnaire complet — état final

### Tables

| Table |
|---|
| Sinistres par Garantie |
| Dossiers |
| Clients |
| Points d'Attention Detailles |
| Detection Atypicite IA |
| Inspections Vehicules |
| Defauts Inspection |
| Etat Technique Vehicule |
| Point d'Attention Post Inspection |
| Gouvernance |
| Indicateurs Qualite |
| Version du Score |
| Calendrier |
| Indicateurs Cles (mesures) |
| Configuration Run — masquée (technique) |

### Vocabulaire clé (concept → nom final)

| Concept | Nom final |
|---|---|
| Score numérique 0-100 | Niveau De Priorite / Niveau De Priorite Dossier |
| Catégorie (Standard / À vérifier / Renforcé / Prioritaire) | Categorie De Priorite / Categorie De Priorite Dossier |
| Fiabilité de l'analyse (ex "confiance") | Fiabilite Analyse |
| Les 2 catégories hautes combinées | Vigilance Elevee |
| La catégorie la plus haute seule | Prioritaires |
| Critère de règle métier (ex "signal") | Point d'Attention |
| Signal statistique parallèle (ML) | Detection Atypicite IA / Indice Ecart Statistique |
| Concentration des sinistres/montants (ex "Pareto") | Groupe Client / Groupe Concentration |
| État du véhicule (ex "VHS") | Etat Vehicule / Etat Technique / Recommandation |

### Colonnes et mesures masquées (techniques, jamais visibles côté gestionnaire)

Toutes les clés de jointure (`Cle *`), identifiants de run/version, aides de tri (`Ordre *`), indicateurs internes du moteur (`Plafond Applique`, `Nb Penalites`, `Code Scenario`, `Code Point Attention`, `Score Brut Atypicite`, `Score IA`), colonnes de binning (`Tranche Score`, `Mois Complet Donnees`, `Est Dernier Mois Clos`, `Mois Sinistre`).

### 117 mesures réparties en 9 dossiers d'affichage

`01 Portefeuille` · `02 Comparaison M-1` · `03 Points d'Attention et priorisation` · `04 Clients et récurrence` · `05 Véhicule et inspections` · `06 Qualité et gouvernance` · `07 Seuils et cibles` · `08 Mise en forme conditionnelle` · `09 Technique interne`

---

## 7. Points encore ouverts

- **3 mesures de seuil quasi-identiques** (`Seuil Fiabilite Elevee`, `Objectif Fiabilite Elevee`, `Cible Fiabilite Elevee`, toutes à 0.80) — à vérifier dans Power BI Desktop lesquelles sont réellement utilisées avant fusion.
- **Page Qualité et Gouvernance** : `Gouvernance[Composant]` contient encore des codes système (`CLAIM_ATTENTION`, `POST_INSPECTION`...) — à reformuler si besoin en labels métier au moment de construire le visuel.
