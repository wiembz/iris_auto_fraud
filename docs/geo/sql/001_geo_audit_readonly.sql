-- READ-ONLY GEO AUDIT — do not run write operations.
-- Purpose: diagnostic SELECT queries for the GEO ETL audit.
-- Adapt table or column names when the physical schema differs.

-- 1. List GEO-related columns detected in PostgreSQL metadata.
SELECT
    table_schema,
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema IN ('staging', 'dwh', 'mart')
  AND (
        lower(column_name) LIKE '%geo%'
     OR lower(column_name) LIKE '%region%'
     OR lower(column_name) LIKE '%gouv%'
     OR lower(column_name) LIKE '%deleg%'
     OR lower(column_name) LIKE '%local%'
     OR lower(column_name) LIKE '%cite%'
     OR lower(column_name) LIKE '%cpost%'
     OR lower(column_name) LIKE '%postal%'
     OR lower(column_name) LIKE '%adresse%'
     OR lower(column_name) LIKE '%ville%'
     OR lower(column_name) LIKE '%lieu%'
     OR lower(column_name) LIKE '%agence%'
     OR lower(column_name) LIKE '%intermediaire%'
     OR lower(column_name) LIKE '%iddelega%'
  )
ORDER BY table_schema, table_name, ordinal_position;

-- 2. Global claim GEO staging completeness with explicit output aliases.
SELECT
    COUNT(*) AS total_sinistres,
    COUNT(*) FILTER (
        WHERE regsini IS NULL
           OR btrim(regsini::text) = ''
           OR upper(btrim(regsini::text)) IN ('UNKNOWN', 'INCONNU', 'INCONNUE', 'N/A', 'NA', '-')
    ) AS regsini_incomplet,
    COUNT(*) FILTER (
        WHERE gouvsini IS NULL
           OR btrim(gouvsini::text) = ''
           OR upper(btrim(gouvsini::text)) IN ('UNKNOWN', 'INCONNU', 'INCONNUE', 'N/A', 'NA', '-')
    ) AS gouvsini_incomplet,
    COUNT(*) FILTER (
        WHERE citesini IS NULL
           OR btrim(citesini::text) = ''
           OR upper(btrim(citesini::text)) IN ('UNKNOWN', 'INCONNU', 'INCONNUE', 'N/A', 'NA', '-')
    ) AS citesini_incomplet,
    COUNT(*) FILTER (
        WHERE cpostsini IS NULL
           OR btrim(cpostsini::text) = ''
           OR upper(btrim(cpostsini::text)) IN ('UNKNOWN', 'INCONNU', 'INCONNUE', 'N/A', 'NA', '-')
    ) AS cpostsini_incomplet
FROM staging.stg_sinistres;

-- 3. UNKNOWN values in final dim_geo business fields.
SELECT
    COUNT(*) AS total_rows,
    COUNT(*) FILTER (WHERE pays = 'UNKNOWN') AS pays_unknown,
    COUNT(*) FILTER (WHERE region = 'UNKNOWN') AS region_unknown,
    COUNT(*) FILTER (WHERE gouvernorat = 'UNKNOWN') AS gouvernorat_unknown,
    COUNT(*) FILTER (WHERE localite = 'UNKNOWN') AS localite_unknown,
    COUNT(*) FILTER (WHERE code_postal = 'UNKNOWN') AS code_postal_unknown,
    COUNT(*) FILTER (WHERE geo_key = 'UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN') AS technical_unknown_rows
FROM dwh.dim_geo;

-- 4. Duplicate GEO business keys.
SELECT
    geo_key,
    COUNT(*) AS nb_rows
FROM dwh.dim_geo
GROUP BY geo_key
HAVING COUNT(*) > 1
ORDER BY nb_rows DESC, geo_key;

-- 5. Postal-only bad rows: postal code exists but place remains unknown.
SELECT
    COUNT(*) AS postal_only_bad_rows
FROM dwh.dim_geo
WHERE pays = 'TUNISIE'
  AND region = 'UNKNOWN'
  AND gouvernorat = 'UNKNOWN'
  AND localite = 'UNKNOWN'
  AND code_postal <> 'UNKNOWN';

-- 6. Full geography rows still missing postal code.
SELECT
    region,
    gouvernorat,
    localite,
    COUNT(*) AS nb_rows
FROM dwh.dim_geo
WHERE pays = 'TUNISIE'
  AND region <> 'UNKNOWN'
  AND gouvernorat <> 'UNKNOWN'
  AND localite <> 'UNKNOWN'
  AND code_postal = 'UNKNOWN'
GROUP BY region, gouvernorat, localite
ORDER BY nb_rows DESC, region, gouvernorat, localite;

-- 7. Fact rows without resolved GEO key.
SELECT
    geo_sinistre_sk,
    COUNT(*) AS nb_rows
FROM dwh.fact_sinistre
GROUP BY geo_sinistre_sk
ORDER BY nb_rows DESC;

-- 8. Fact GEO keys absent from dim_geo.
SELECT
    f.geo_sinistre_sk,
    COUNT(*) AS nb_rows
FROM dwh.fact_sinistre f
LEFT JOIN dwh.dim_geo g
       ON g.geo_sk = f.geo_sinistre_sk
WHERE g.geo_sk IS NULL
GROUP BY f.geo_sinistre_sk
ORDER BY nb_rows DESC;

-- 9. Duplicate agency/intermediary codes.
-- Replace column names if the agency dimension uses different names.
SELECT
    code_intermediaire,
    COUNT(*) AS nb_rows
FROM dwh.dim_intermediaire
WHERE code_intermediaire IS NOT NULL
GROUP BY code_intermediaire
HAVING COUNT(*) > 1
ORDER BY nb_rows DESC, code_intermediaire;

-- 10. Detect available agency/region columns before running agency-region controls.
-- In the current DWH, dwh.dim_intermediaire may not contain a `region` column.
-- Run this metadata query first, then adapt the optional agency-region check manually.
SELECT
    table_schema,
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema IN ('staging', 'dwh', 'mart')
  AND (
        lower(column_name) LIKE '%agence%'
     OR lower(column_name) LIKE '%intermediaire%'
     OR lower(column_name) LIKE '%region%'
     OR lower(column_name) LIKE '%iddelega%'
     OR lower(column_name) LIKE '%deleg%'
     OR lower(column_name) IN ('natint', 'idint', 'code_intermediaire', 'nature_intermediaire')
  )
ORDER BY table_schema, table_name, ordinal_position;

-- Optional agency-region control, only after identifying the real table/columns:
-- SELECT
--     <agency_code_column> AS code_agence,
--     COUNT(DISTINCT <region_column>) AS nb_regions,
--     string_agg(DISTINCT <region_column>::text, ' | ' ORDER BY <region_column>::text) AS regions
-- FROM <schema>.<agency_region_table>
-- WHERE <agency_code_column> IS NOT NULL
--   AND <region_column> IS NOT NULL
-- GROUP BY <agency_code_column>
-- HAVING COUNT(DISTINCT <region_column>) > 1
-- ORDER BY nb_regions DESC, code_agence;

-- 11. Intermediary keys present in facts but absent from dim_intermediaire.
SELECT
    f.intermediaire_sk,
    COUNT(*) AS nb_rows
FROM dwh.fact_contrat f
LEFT JOIN dwh.dim_intermediaire i
       ON i.intermediaire_sk = f.intermediaire_sk
WHERE i.intermediaire_sk IS NULL
GROUP BY f.intermediaire_sk
ORDER BY nb_rows DESC;

-- 12. Before/after 2019 GEO coverage if date_survenance_sk is linked to dim_date.
SELECT
    CASE
        WHEN d.date_complete < DATE '2019-01-01' THEN 'BEFORE_2019'
        WHEN d.date_complete >= DATE '2019-01-01' THEN 'FROM_2019'
        ELSE 'DATE_UNKNOWN'
    END AS periode_migration,
    COUNT(*) AS nb_fact_rows,
    COUNT(*) FILTER (WHERE f.geo_sinistre_sk = 0) AS geo_sk_unknown_rows,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE f.geo_sinistre_sk = 0) / NULLIF(COUNT(*), 0),
        2
    ) AS pct_geo_unknown
FROM dwh.fact_sinistre f
LEFT JOIN dwh.dim_date d
       ON d.date_sk = f.date_survenance_sk
GROUP BY periode_migration
ORDER BY periode_migration;

-- 13. Before/after 2019 staging GEO completeness.
-- In staging.stg_sinistres, the available claim occurrence date is dtsurv.
SELECT
    CASE
        WHEN dtsurv::date < DATE '2019-01-01' THEN 'BEFORE_2019'
        WHEN dtsurv::date >= DATE '2019-01-01' THEN 'FROM_2019'
        ELSE 'DATE_UNKNOWN'
    END AS periode,
    COUNT(*) AS total_sinistres,
    COUNT(*) FILTER (
        WHERE regsini IS NULL
           OR btrim(regsini::text) = ''
           OR upper(btrim(regsini::text)) IN ('UNKNOWN', 'INCONNU', 'INCONNUE', 'N/A', 'NA', '-')
    ) AS regsini_incomplet,
    COUNT(*) FILTER (
        WHERE gouvsini IS NULL
           OR btrim(gouvsini::text) = ''
           OR upper(btrim(gouvsini::text)) IN ('UNKNOWN', 'INCONNU', 'INCONNUE', 'N/A', 'NA', '-')
    ) AS gouvsini_incomplet,
    COUNT(*) FILTER (
        WHERE citesini IS NULL
           OR btrim(citesini::text) = ''
           OR upper(btrim(citesini::text)) IN ('UNKNOWN', 'INCONNU', 'INCONNUE', 'N/A', 'NA', '-')
    ) AS citesini_incomplet,
    COUNT(*) FILTER (
        WHERE cpostsini IS NULL
           OR btrim(cpostsini::text) = ''
           OR upper(btrim(cpostsini::text)) IN ('UNKNOWN', 'INCONNU', 'INCONNUE', 'N/A', 'NA', '-')
    ) AS cpostsini_incomplet
FROM staging.stg_sinistres
GROUP BY periode
ORDER BY periode;


-- 14. Confirm whether candidate date/delegation columns exist in staging tables.
SELECT
    table_schema,
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema = 'staging'
  AND table_name IN ('stg_sinistres', 'stg_production')
  AND lower(column_name) IN (
      'date_sinistre', 'dtsurv', 'dtdecsnt', 'dtouvsnt', 'dtcltsnt',
      'iddelega', 'id_delega', 'code_delegation', 'delegation'
  )
ORDER BY table_name, ordinal_position;

-- 15. Delegation completeness in production staging.
-- The codebase maps IDDELEGA from staging.stg_production, not staging.stg_sinistres.
SELECT
    COUNT(*) AS total_production_rows,
    COUNT(*) FILTER (
        WHERE iddelega IS NULL
           OR btrim(iddelega::text) = ''
           OR upper(btrim(iddelega::text)) IN ('UNKNOWN', 'INCONNU', 'INCONNUE', 'N/A', 'NA', '-')
    ) AS iddelega_incomplet
FROM staging.stg_production;

