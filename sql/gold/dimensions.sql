-- Gold: conformed dimensions for the star schemas

DROP TABLE IF EXISTS gold_dim_date;

CREATE TABLE gold_dim_date AS
WITH RECURSIVE d(day) AS (
    SELECT DATE('{{ start_date }}')
    UNION ALL
    SELECT DATE(day, '+1 day') FROM d WHERE day < DATE('{{ end_date }}')
)
SELECT
    CAST(STRFTIME('%Y%m%d', day) AS INTEGER)       AS date_key,
    day                                            AS full_date,
    CAST(STRFTIME('%Y', day) AS INTEGER)           AS year,
    CAST(STRFTIME('%m', day) AS INTEGER)           AS month,
    STRFTIME('%Y-%m', day)                         AS year_month,
    CAST(STRFTIME('%w', day) AS INTEGER)           AS day_of_week,     -- 0 = Sunday
    CASE WHEN STRFTIME('%w', day) IN ('0', '6') THEN 0 ELSE 1 END AS is_working_day
FROM d;

DROP TABLE IF EXISTS gold_dim_employee;

CREATE TABLE gold_dim_employee AS
SELECT
    ROW_NUMBER() OVER (ORDER BY employee_id)       AS employee_key,
    employee_id, full_name, department, contract_type, hire_date, exit_date, exit_type
FROM silver_employees;

DROP TABLE IF EXISTS gold_dim_line;

CREATE TABLE gold_dim_line AS
SELECT
    ROW_NUMBER() OVER (ORDER BY line_code)         AS line_key,
    line_code,
    CASE WHEN line_code LIKE 'T%' THEN 'Tramway' ELSE 'Busway' END AS mode
FROM (SELECT DISTINCT line_code FROM silver_fleet_availability);
