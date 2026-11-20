from __future__ import annotations

import sqlite3

import pytest

from trackflow.quality import compile_check, run_checks
from trackflow.sql import parse_date


@pytest.mark.parametrize("raw, expected", [
    ("2024-03-07", "2024-03-07"),
    ("07/03/2024", "2024-03-07"),
    ("20240307", "2024-03-07"),
    ("  2024-03-07 ", "2024-03-07"),
    ("", None),
    ("31/02/2024", None),   # impossible date is rejected, not silently shifted
    ("garbage", None),
])
def test_parse_date_handles_every_source_format(raw, expected):
    conn = sqlite3.connect(":memory:")
    sql = f"WITH src(x) AS (SELECT ?) SELECT {parse_date('x')} FROM src"
    assert conn.execute(sql, (raw,)).fetchone()[0] == expected


def test_silver_removes_duplicates(conn):
    bronze = conn.execute("SELECT COUNT(*), COUNT(DISTINCT employee_id) FROM bronze_hr_employees").fetchone()
    silver = conn.execute("SELECT COUNT(*) FROM silver_employees").fetchone()[0]
    assert bronze[0] > bronze[1] == silver


def test_silver_drops_orphans_and_bad_dates(conn):
    assert conn.execute("SELECT COUNT(*) FROM silver_absences WHERE employee_id = 'E99999'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM silver_absences WHERE start_date IS NULL").fetchone()[0] == 0


def test_departments_are_conformed(conn):
    depts = {r[0] for r in conn.execute("SELECT DISTINCT department FROM silver_employees")}
    assert depts == {"Operations", "Maintenance", "Customer Service", "Security", "Support Functions"}


def test_absence_fact_grain_is_employee_day(conn):
    dupes = conn.execute("""SELECT COUNT(*) FROM (SELECT employee_key, date_key, COUNT(*) n
                            FROM gold_fact_absence_day GROUP BY 1, 2 HAVING n > 1)""").fetchone()[0]
    # overlapping absences in the source would double count: the model must not hide it silently
    total = conn.execute("SELECT COUNT(*) FROM gold_fact_absence_day").fetchone()[0]
    assert dupes / total < 0.05


def test_kpis_reconcile_with_numerator_and_denominator(conn):
    bad = conn.execute("""SELECT COUNT(*) FROM gold_kpi_monthly
                          WHERE denominator > 0 AND ABS(value - numerator / denominator) > 1e-9""").fetchone()[0]
    assert bad == 0


def test_network_availability_is_weighted_by_required_fleet(conn):
    network, lines = conn.execute("""
        SELECT (SELECT value FROM gold_kpi_monthly WHERE kpi='fleet_availability' AND scope='All' AND year_month='2024-06'),
               (SELECT SUM(numerator) / SUM(denominator) FROM gold_kpi_monthly
                WHERE kpi='fleet_availability' AND scope <> 'All' AND year_month='2024-06')""").fetchone()
    assert network == pytest.approx(lines)


def test_every_month_has_every_kpi(conn):
    months = conn.execute("SELECT COUNT(DISTINCT year_month) FROM gold_dim_date").fetchone()[0]
    for kpi, n in conn.execute("SELECT kpi, COUNT(*) FROM gold_kpi_monthly WHERE scope='All' GROUP BY kpi"):
        assert n == months, kpi


def test_quality_checks_catch_problems():
    conn = sqlite3.connect(":memory:")
    conn.executescript("CREATE TABLE t (id INT, v REAL); INSERT INTO t VALUES (1, .5), (1, 2.0), (NULL, .1);")
    results = run_checks(conn, [
        {"table": "t", "check": "unique", "column": "id"},
        {"table": "t", "check": "not_null", "column": "id"},
        {"table": "t", "check": "expression", "expr": "v BETWEEN 0 AND 1"},
        {"table": "t", "check": "min_rows", "value": 10, "severity": "warn"},
    ])
    assert [r.failures for r in results] == [1, 1, 1, 1]
    assert results[-1].severity == "warn"


def test_unknown_check_type_fails_loudly():
    with pytest.raises(ValueError):
        compile_check({"table": "t", "check": "vibes"})
