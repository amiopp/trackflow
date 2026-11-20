-- Gold: monthly KPI table consumed by BI and the forecasting step.
-- Long format (kpi, scope, year_month, value) so new KPIs need no schema change.

DROP TABLE IF EXISTS gold_kpi_monthly;

CREATE TABLE gold_kpi_monthly (
    kpi         TEXT NOT NULL,
    scope       TEXT NOT NULL,
    year_month  TEXT NOT NULL,
    value       REAL,
    numerator   REAL,
    denominator REAL,
    PRIMARY KEY (kpi, scope, year_month)
);

-- Absenteeism rate = absent working days / (headcount x working days)
INSERT INTO gold_kpi_monthly
WITH months AS (
    SELECT year_month, MIN(full_date) AS m_start, MAX(full_date) AS m_end,
           SUM(is_working_day) AS working_days
    FROM gold_dim_date GROUP BY year_month
),
headcount AS (
    SELECT m.year_month, e.department, COUNT(*) AS hc
    FROM months m
    JOIN gold_dim_employee e
      ON e.hire_date <= m.m_end AND (e.exit_date IS NULL OR e.exit_date >= m.m_end)
    GROUP BY m.year_month, e.department
),
absent AS (
    SELECT d.year_month, e.department, COUNT(*) AS absent_days
    FROM gold_fact_absence_day f
    JOIN gold_dim_date d     ON d.date_key = f.date_key
    JOIN gold_dim_employee e ON e.employee_key = f.employee_key
    WHERE f.is_working_day = 1
    GROUP BY d.year_month, e.department
),
by_dept AS (
    SELECT h.year_month, h.department AS scope,
           COALESCE(a.absent_days, 0) AS num, h.hc * m.working_days AS den
    FROM headcount h
    JOIN months m USING (year_month)
    LEFT JOIN absent a ON a.year_month = h.year_month AND a.department = h.department
)
SELECT 'absenteeism_rate', scope, year_month, num * 1.0 / den, num, den FROM by_dept
UNION ALL
SELECT 'absenteeism_rate', 'All', year_month, SUM(num) * 1.0 / SUM(den), SUM(num), SUM(den)
FROM by_dept GROUP BY year_month;

-- Turnover rate = exits in month / headcount at start of month
INSERT INTO gold_kpi_monthly
WITH months AS (
    SELECT year_month, MIN(full_date) AS m_start, MAX(full_date) AS m_end
    FROM gold_dim_date GROUP BY year_month
)
SELECT 'turnover_rate', 'All', m.year_month,
       SUM(CASE WHEN e.exit_date BETWEEN m.m_start AND m.m_end THEN 1 ELSE 0 END) * 1.0
         / NULLIF(SUM(CASE WHEN e.hire_date < m.m_start AND (e.exit_date IS NULL OR e.exit_date >= m.m_start) THEN 1 ELSE 0 END), 0),
       SUM(CASE WHEN e.exit_date BETWEEN m.m_start AND m.m_end THEN 1 ELSE 0 END),
       SUM(CASE WHEN e.hire_date < m.m_start AND (e.exit_date IS NULL OR e.exit_date >= m.m_start) THEN 1 ELSE 0 END)
FROM months m CROSS JOIN gold_dim_employee e
GROUP BY m.year_month;

-- Preventive maintenance compliance = preventive WOs closed within 3 days / planned
INSERT INTO gold_kpi_monthly
SELECT 'preventive_maintenance_rate', 'All', d.year_month,
       SUM(f.completed_on_time) * 1.0 / COUNT(*), SUM(f.completed_on_time), COUNT(*)
FROM gold_fact_work_order f
JOIN gold_dim_date d ON d.date_key = f.planned_date_key
WHERE f.wo_type = 'preventive'
GROUP BY d.year_month;

-- Fleet availability = vehicles available / vehicles required (per line and network)
INSERT INTO gold_kpi_monthly
SELECT 'fleet_availability', l.line_code, d.year_month,
       SUM(f.vehicles_available) * 1.0 / SUM(f.vehicles_required),
       SUM(f.vehicles_available), SUM(f.vehicles_required)
FROM gold_fact_fleet_availability f
JOIN gold_dim_date d ON d.date_key = f.date_key
JOIN gold_dim_line l ON l.line_key = f.line_key
GROUP BY l.line_code, d.year_month
UNION ALL
SELECT 'fleet_availability', 'All', d.year_month,
       SUM(f.vehicles_available) * 1.0 / SUM(f.vehicles_required),
       SUM(f.vehicles_available), SUM(f.vehicles_required)
FROM gold_fact_fleet_availability f
JOIN gold_dim_date d ON d.date_key = f.date_key
GROUP BY d.year_month;
