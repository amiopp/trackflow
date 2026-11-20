-- Silver: daily fleet availability per line (one row per date x line)

DROP TABLE IF EXISTS silver_fleet_availability;

CREATE TABLE silver_fleet_availability AS
SELECT
    {{ parse_date('date') }}                       AS service_date,
    UPPER(TRIM(line))                              AS line_code,
    CAST(vehicles_required  AS INTEGER)            AS vehicles_required,
    MIN(CAST(vehicles_available AS INTEGER), CAST(vehicles_required AS INTEGER)) AS vehicles_available
FROM bronze_fleet_availability
WHERE {{ parse_date('date') }} IS NOT NULL
GROUP BY 1, 2, 3;
