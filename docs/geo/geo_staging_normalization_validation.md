# Validation de la normalisation GEO staging — stg_sinistres

> **Statut :** VALIDÉE  
> **Date :** 2026-07-05  
> **Branche :** `audit/geo-etl-readonly`  
> **Profil :** `staging.stg_sinistres` — BNA Assurances / IRIS Auto Fraud

---

## Objectif

Vérifier que la normalisation technique GEO intégrée dans `load_sinistres_sa.py` produit
des colonnes `*_norm` correctes dans `staging.stg_sinistres`, sans altérer les colonnes
brutes ni appliquer de correction métier.

Cette validation ne constitue pas une résolution géographique. Elle confirme uniquement
que la brique technique de nettoyage fonctionne conformément à la spécification.

---

## Colonnes validées

| Colonne source | Type source       | Colonne normalisée | Type normalisé | Fonction appliquée       |
|----------------|-------------------|--------------------|----------------|--------------------------|
| `gouvsini`     | text              | `gouvsini_norm`    | text           | `normalize_geo_text`     |
| `citesini`     | text              | `citesini_norm`    | text           | `normalize_geo_text`     |
| `cpostsini`    | double precision  | `cpostsini_norm`   | text           | `normalize_postal_code`  |
| `iddelega`     | bigint            | `iddelega_norm`    | text           | `normalize_numeric_code` |

Toutes les colonnes brutes sont conservées intactes. Les colonnes `*_norm` sont ajoutées
sans suppression ni remplacement.

---

## Volumétrie

- **Total lignes :** 381 893
- **Source :** `enriched_sinistres.xlsx` → `staging.stg_sinistres`
- **Run de référence :** 2026-07-05

---

## Comparaison brut vs normalisé

### Taux de NULL

| Colonne | NULL brut | % brut | NULL normalisé | % normalisé | Écart |
|---------|-----------|--------|----------------|-------------|-------|
| `gouvsini` | 62 465 | 16,4 % | 62 469 | 16,4 % | +4 |
| `citesini` | 25 247 | 6,6 % | 25 281 | 6,6 % | +34 |
| `cpostsini` | 18 924 | 5,0 % | 18 924 | 5,0 % | 0 |
| `iddelega` | 0 | 0,0 % | 0 | 0,0 % | 0 |

### Requête de vérification (read-only)

```sql
SELECT
    COUNT(*)                                        AS total_lignes,
    COUNT(*) FILTER (WHERE gouvsini IS NULL)        AS gouvsini_null_brut,
    COUNT(*) FILTER (WHERE gouvsini_norm IS NULL)   AS gouvsini_norm_null,
    COUNT(*) FILTER (WHERE citesini IS NULL)        AS citesini_null_brut,
    COUNT(*) FILTER (WHERE citesini_norm IS NULL)   AS citesini_norm_null,
    COUNT(*) FILTER (WHERE cpostsini IS NULL)       AS cpostsini_null_brut,
    COUNT(*) FILTER (WHERE cpostsini_norm IS NULL)  AS cpostsini_norm_null,
    COUNT(*) FILTER (WHERE iddelega IS NULL)        AS iddelega_null_brut,
    COUNT(*) FILTER (WHERE iddelega_norm IS NULL)   AS iddelega_norm_null
FROM staging.stg_sinistres;
```

---

## Lecture des écarts

### `gouvsini` — écart +4

Quatre valeurs brutes non-nulles ont été converties en `NULL` par le normaliseur.
Ce sont des tokens non-informatifs reconnus par `_NULL_TOKENS` :
`.`, `-`, `N/A`, `NA`, `--` ou chaînes vides après nettoyage des espaces.

Ces 4 lignes ne portaient aucune information géographique utile. Leur conversion en NULL
est conforme à la spécification.

### `citesini` — écart +34

Trente-quatre valeurs brutes non-nulles ont été converties en `NULL`.
Même cause : tokens non-informatifs (`.`, `-`, `N/A`, etc.) présents dans le champ localité.

La localité est un champ libre plus sujet à la saisie dégradée que le gouvernorat,
ce qui explique un écart plus élevé (+34 contre +4).

### `cpostsini` — écart 0

Tous les nulls étaient déjà des valeurs `NaN` ou `NULL` de type float.
Aucun token texte non-informatif n'a été trouvé. Le normaliseur n'a pas modifié
le compte de nulls — seulement converti les valeurs float de type `1000.0` en texte `"1000"`.

### `iddelega` — écart 0

Couverture complète : 381 893 valeurs présentes, aucune manquante.
Le normaliseur a converti les bigint en chaînes de caractères propres.

---

## Exemples de normalisation technique réussie

### Uniformisation de la casse

| Valeur brute | Valeur normalisée |
|--------------|------------------|
| `tunis` | `TUNIS` |
| `Sfax` | `SFAX` |
| `ben arous` | `BEN AROUS` |
| ` Tunis ` | `TUNIS` |

### Suppression des doubles espaces

| Valeur brute | Valeur normalisée |
|--------------|------------------|
| `BEN  AROUS` | `BEN AROUS` |
| `SIDI  BOUZID` | `SIDI BOUZID` |

### Tokens non-informatifs → NULL

| Valeur brute | Valeur normalisée |
|--------------|------------------|
| `N/A` | `NULL` |
| `-` | `NULL` |
| `.` | `NULL` |
| `""` (chaîne vide) | `NULL` |

### Tokens inconnus → UNKNOWN

| Valeur brute | Valeur normalisée |
|--------------|------------------|
| `INCONNU` | `UNKNOWN` |
| `NON RENSEIGNE` | `UNKNOWN` |
| `INCONNUE` | `UNKNOWN` |

### Codes postaux float Excel → texte propre

| Valeur brute (`cpostsini`) | Valeur normalisée (`cpostsini_norm`) |
|----------------------------|--------------------------------------|
| `1000.0` (float) | `"1000"` |
| `2080.0` (float) | `"2080"` |
| `3000.0` (float) | `"3000"` |

### Distribution top gouvernorats après normalisation

| `gouvsini_norm` | Lignes |
|-----------------|--------|
| `TUNIS` | 90 168 |
| NULL | 62 469 |
| `SFAX` | 41 419 |
| `BEN AROUS` | 31 891 |
| `ARIANA` | 29 323 |
| `SOUSSE` | 20 131 |
| `NABEUL` | 19 704 |
| `MONASTIR` | 14 720 |
| `MANNOUBA` | 12 351 |
| `BIZERTE` | 11 770 |

---

## Valeurs résiduelles à examiner

Ces valeurs sont **conservées intentionnellement** dans les colonnes `*_norm`.
Elles ne sont pas des tokens null ni des tokens inconnus.
Leur traitement relève de `load_dim_geo.py` et de ses référentiels métier.

### Variantes de gouvernorats — à résoudre par `load_dim_geo`

Ces valeurs sont des alias ou des fautes de saisie que `_GOUVERNORAT_ALIASES` de
`load_dim_geo.py` est conçu pour corriger lors de la résolution GEO.

| `gouvsini_norm` | Lignes | Valeur résolue attendue |
|-----------------|--------|-------------------------|
| `MEDNINE` | 271 | MEDENINE |
| `B AROUS` | 106 | BEN AROUS |
| `LA MARSA` | 94 | ARIANA (délégation) |
| `LE KEF` | 42 | KEF |
| `BENAROUS` | 6 | BEN AROUS |
| `JANDOUBA` | 10 | JENDOUBA |
| `TUIS` | 8 | TUNIS |
| `SAFX` | 3 | SFAX |
| `KAIROUEN` | 3 | KAIROUAN |
| `SOSSE` | 2 | SOUSSE |

### Valeurs erronées dans `gouvsini_norm` — audit qualité requis

Ces valeurs ne correspondent pas à un gouvernorat et témoignent d'une saisie incorrecte
dans le champ source. Elles seront classifiées AMBIGUOUS ou UNKNOWN par `load_dim_geo`.

| Type | Exemples | Lignes estimées |
|------|----------|-----------------|
| Codes postaux | `1000`, `1053`, `1001`, `3000` | ~100 |
| Dates (JJMMAAAA) | `02022022`, `06121982`, `20102000` | ~15 |
| Valeurs dégénérées | `A`, `B`, `1`, `2`, `X`, `*` | ~40 |
| Adresses libres | `RTE SILIANA`, `RUE KEF ROHI` | ~10 |
| Valeurs ambiguës | `TUNISIE -` | 7 |

### Requête de contrôle (read-only)

```sql
-- Valeurs dans gouvsini_norm qui ne sont pas des gouvernorats reconnus
SELECT
    gouvsini_norm,
    COUNT(*) AS nb
FROM staging.stg_sinistres
WHERE gouvsini_norm IS NOT NULL
  AND gouvsini_norm NOT IN (
      'TUNIS', 'ARIANA', 'BEN AROUS', 'MANOUBA',
      'NABEUL', 'ZAGHOUAN', 'BIZERTE',
      'BEJA', 'JENDOUBA', 'KEF', 'SILIANA',
      'SOUSSE', 'MONASTIR', 'MAHDIA', 'SFAX',
      'KAIROUAN', 'KASSERINE', 'SIDI BOUZID',
      'GABES', 'MEDENINE', 'TATAOUINE',
      'GAFSA', 'TOZEUR', 'KEBILI'
  )
GROUP BY gouvsini_norm
ORDER BY nb DESC
LIMIT 50;

-- Valeurs UNKNOWN dans gouvsini_norm
SELECT COUNT(*) AS nb_unknown
FROM staging.stg_sinistres
WHERE gouvsini_norm = 'UNKNOWN';

-- Valeurs NULL dans gouvsini_norm
SELECT COUNT(*) AS nb_null
FROM staging.stg_sinistres
WHERE gouvsini_norm IS NULL;
```

---

## Conclusion

La normalisation technique GEO staging est **validée** sur 381 893 lignes.

| Critère | Résultat |
|---------|----------|
| Colonnes `*_norm` créées | ✓ 4/4 |
| Colonnes brutes conservées | ✓ inchangées |
| Tokens non-informatifs → NULL | ✓ +4 gouvsini, +34 citesini |
| Float Excel → texte propre | ✓ cpostsini_norm |
| Aucune correction métier appliquée | ✓ |
| Aucune écriture DWH | ✓ |
| `load_dim_geo.py` non modifié | ✓ |
| `load_fact_sinistre.py` non modifié | ✓ |
| Tests unitaires | ✓ 21/21 passés |

Les valeurs résiduelles non reconnues (aliases, codes postaux erronés, dates) sont
**conservées intentionnellement** pour audit qualité et résolution référentielle.
Elles ne constituent pas un défaut de la normalisation technique — elles constituent
un inventaire exploitable pour la prochaine étape.

---

## Prochaine étape recommandée

**Étape 5 — Comparer la résolution GEO avant/après pré-normalisation**

Relancer `load_dim_geo.py` en environnement TEST sur la table `staging.stg_sinistres`
enrichie. Mesurer si les 38 tokens non-informatifs désormais en NULL staging améliorent
le taux de résolution dans `dwh.dim_geo` (moins de lignes classifiées AMBIGUOUS/UNKNOWN
dues à un bruit technique qui aurait pollué la clé `source_geo_key`).

Requêtes de comparaison read-only après relance `load_dim_geo` en TEST :

```sql
-- Répartition des niveaux de qualité GEO avant/après
SELECT
    geo_quality_level,
    COUNT(*)        AS nb,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct
FROM dwh.dim_geo
GROUP BY geo_quality_level
ORDER BY nb DESC;

-- Lignes résiduelles UNKNOWN dans dim_geo
SELECT
    gouvernorat,
    localite,
    code_postal,
    geo_quality_level,
    COUNT(*) AS nb
FROM dwh.dim_geo
WHERE geo_quality_level = 'UNKNOWN'
GROUP BY gouvernorat, localite, code_postal, geo_quality_level
ORDER BY nb DESC
LIMIT 20;

-- Vérifier qu'aucune valeur brute non-informative n'a pollué source_geo_key
SELECT
    source_geo_key,
    resolved_geo_key,
    COUNT(*) AS nb
FROM (
    SELECT *
    FROM staging.stg_sinistres
) s
WHERE gouvsini_norm IS NULL
  AND gouvsini IS NOT NULL
LIMIT 20;
```
