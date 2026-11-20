-- Silver: conformed CMMS work orders

DROP TABLE IF EXISTS silver_work_orders;

CREATE TABLE silver_work_orders AS
WITH typed AS (
    SELECT
        TRIM(work_order_id)                         AS work_order_id,
        UPPER(TRIM(asset_id))                       AS asset_id,
        UPPER(SUBSTR(TRIM(asset_id), 1, INSTR(TRIM(asset_id), '-') - 1)) AS line_code,
        LOWER(TRIM(wo_type))                        AS wo_type,
        {{ parse_date('planned_date') }}            AS planned_date,
        {{ parse_date('completed_date') }}          AS completed_date,
        LOWER(TRIM(status))                         AS status
    FROM bronze_maint_work_orders
),
dedup AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY work_order_id ORDER BY work_order_id) AS rn
    FROM typed
)
SELECT work_order_id, asset_id, line_code, wo_type, planned_date, completed_date, status
FROM dedup
WHERE rn = 1 AND planned_date IS NOT NULL;
