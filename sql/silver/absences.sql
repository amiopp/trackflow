-- Silver: conformed absences
-- * standardises free-text reasons
-- * drops rows with unusable dates and orphans (employee not in HR master)
-- * de-duplicates on absence_id

DROP TABLE IF EXISTS silver_absences;

CREATE TABLE silver_absences AS
WITH typed AS (
    SELECT
        TRIM(absence_id)                     AS absence_id,
        TRIM(employee_id)                    AS employee_id,
        {{ parse_date('start_date') }}       AS start_date,
        {{ parse_date('end_date') }}         AS end_date,
        LOWER(TRIM(reason))                  AS reason
    FROM bronze_hr_absences
),
dedup AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY absence_id ORDER BY absence_id) AS rn
    FROM typed
)
SELECT d.absence_id, d.employee_id, d.start_date, d.end_date, d.reason
FROM dedup d
JOIN silver_employees e ON e.employee_id = d.employee_id
WHERE d.rn = 1
  AND d.start_date IS NOT NULL
  AND d.end_date   IS NOT NULL
  AND d.end_date  >= d.start_date;
