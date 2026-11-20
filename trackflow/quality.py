"""Declarative data quality checks, configured per task in pipelines.yaml.

Each check compiles to a query returning the number of failing rows.
``severity: error`` (default) fails the task; ``warn`` is logged only.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class CheckResult:
    table: str
    check: str
    detail: str
    failures: int
    severity: str

    @property
    def passed(self) -> bool:
        return self.failures == 0


def _sql_list(values: list[str]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


def compile_check(spec: dict) -> tuple[str, str]:
    t, kind, col = spec["table"], spec["check"], spec.get("column")
    if kind == "not_null":
        return f"SELECT COUNT(*) FROM {t} WHERE {col} IS NULL", col
    if kind == "unique":
        return (f"SELECT COALESCE(SUM(n - 1), 0) FROM (SELECT COUNT(*) n FROM {t} GROUP BY {col} HAVING n > 1)", col)
    if kind == "accepted_values":
        return f"SELECT COUNT(*) FROM {t} WHERE {col} NOT IN ({_sql_list(spec['values'])})", col
    if kind == "expression":
        return f"SELECT COUNT(*) FROM {t} WHERE NOT ({spec['expr']})", spec["expr"]
    if kind == "relationship":
        to, to_col = spec["to"], spec["to_column"]
        return (f"SELECT COUNT(*) FROM {t} s LEFT JOIN {to} p ON p.{to_col} = s.{col} "
                f"WHERE s.{col} IS NOT NULL AND p.{to_col} IS NULL", f"{col} -> {to}.{to_col}")
    if kind == "min_rows":
        return f"SELECT CASE WHEN COUNT(*) >= {int(spec['value'])} THEN 0 ELSE 1 END FROM {t}", f">= {spec['value']} rows"
    raise ValueError(f"unknown check type: {kind}")


def run_checks(conn: sqlite3.Connection, specs: list[dict]) -> list[CheckResult]:
    results = []
    for spec in specs:
        sql, detail = compile_check(spec)
        failures = conn.execute(sql).fetchone()[0] or 0
        results.append(CheckResult(spec["table"], spec["check"], detail, int(failures), spec.get("severity", "error")))
    return results
