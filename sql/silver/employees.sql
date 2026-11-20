-- Silver: conformed employees
-- * trims / normalises department casing
-- * parses three date formats found in the HR export (ISO, dd/mm/yyyy, yyyymmdd)
-- * removes duplicate export rows (keeps one row per employee_id)

DROP TABLE IF EXISTS silver_employees;

CREATE TABLE silver_employees AS
WITH typed AS (
    SELECT
        TRIM(employee_id)                                   AS employee_id,
        TRIM(full_name)                                     AS full_name,
        CASE LOWER(TRIM(department))
            WHEN 'operations'        THEN 'Operations'
            WHEN 'maintenance'       THEN 'Maintenance'
            WHEN 'customer service'  THEN 'Customer Service'
            WHEN 'security'          THEN 'Security'
            WHEN 'support functions' THEN 'Support Functions'
            ELSE 'Unknown'
        END                                                 AS department,
        UPPER(TRIM(contract_type))                          AS contract_type,
        {{ parse_date('hire_date') }}                       AS hire_date,
        {{ parse_date('exit_date') }}                       AS exit_date,
        NULLIF(LOWER(TRIM(exit_type)), '')                  AS exit_type,
        _batch_id
    FROM bronze_hr_employees
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY employee_id ORDER BY _batch_id DESC) AS rn
    FROM typed
    WHERE employee_id <> ''
)
SELECT employee_id, full_name, department, contract_type, hire_date, exit_date, exit_type
FROM ranked
WHERE rn = 1;
