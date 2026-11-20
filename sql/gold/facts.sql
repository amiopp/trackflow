-- Gold: fact tables (grain documented on each)

-- Grain: one row per employee per absent calendar day
DROP TABLE IF EXISTS gold_fact_absence_day;

CREATE TABLE gold_fact_absence_day AS
SELECT
    e.employee_key,
    d.date_key,
    a.reason,
    d.is_working_day
FROM silver_absences a
JOIN gold_dim_employee e ON e.employee_id = a.employee_id
JOIN gold_dim_date     d ON d.full_date BETWEEN a.start_date AND a.end_date;

-- Grain: one row per work order
DROP TABLE IF EXISTS gold_fact_work_order;

CREATE TABLE gold_fact_work_order AS
SELECT
    w.work_order_id,
    w.asset_id,
    l.line_key,
    CAST(STRFTIME('%Y%m%d', w.planned_date) AS INTEGER)   AS planned_date_key,
    w.wo_type,
    w.status,
    CASE WHEN w.completed_date IS NOT NULL AND w.completed_date <= DATE(w.planned_date, '+3 days')
         THEN 1 ELSE 0 END                                AS completed_on_time,
    CAST(JULIANDAY(w.completed_date) - JULIANDAY(w.planned_date) AS INTEGER) AS days_to_complete
FROM silver_work_orders w
LEFT JOIN gold_dim_line l ON l.line_code = w.line_code;

-- Grain: one row per line per service day
DROP TABLE IF EXISTS gold_fact_fleet_availability;

CREATE TABLE gold_fact_fleet_availability AS
SELECT
    l.line_key,
    CAST(STRFTIME('%Y%m%d', f.service_date) AS INTEGER)  AS date_key,
    f.vehicles_required,
    f.vehicles_available
FROM silver_fleet_availability f
JOIN gold_dim_line l ON l.line_code = f.line_code;
