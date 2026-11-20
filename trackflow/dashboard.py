"""Operations dashboard: pipeline runs, task health, data quality and KPIs (actuals + forecast)."""

from __future__ import annotations

import sqlite3
import threading

from flask import Flask, jsonify, render_template, request

from .engine import Pipeline, Runner, connect


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    cur = conn.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def create_app(pipeline: Pipeline) -> Flask:
    app = Flask(__name__)
    db_path = pipeline.root / pipeline.settings["database"]
    lock = threading.Lock()

    def db() -> sqlite3.Connection:
        return connect(db_path)

    @app.get("/")
    def index():
        return render_template("dashboard.html")

    @app.get("/api/runs")
    def runs():
        with db() as conn:
            return jsonify(_rows(conn, "SELECT * FROM ops_runs ORDER BY started_at DESC LIMIT 20"))

    @app.get("/api/runs/<run_id>")
    def run_detail(run_id: str):
        with db() as conn:
            return jsonify({
                "tasks": _rows(conn, "SELECT * FROM ops_task_runs WHERE run_id=? ORDER BY started_at, attempt", (run_id,)),
                "quality": _rows(conn, "SELECT * FROM ops_dq_results WHERE run_id=?", (run_id,)),
            })

    @app.get("/api/stats")
    def stats():
        with db() as conn:
            s = _rows(conn, """
                SELECT COUNT(*) AS runs,
                       ROUND(100.0 * SUM(status = 'success') / NULLIF(COUNT(*), 0), 1) AS success_rate,
                       ROUND(AVG((JULIANDAY(finished_at) - JULIANDAY(started_at)) * 86400), 1) AS avg_duration_s
                FROM ops_runs WHERE finished_at IS NOT NULL""")[0]
            return jsonify(s)

    @app.get("/api/kpis")
    def kpis():
        with db() as conn:
            if not _table_exists(conn, "gold_kpi_monthly"):
                return jsonify({"actuals": [], "forecast": []})
            actuals = _rows(conn, "SELECT kpi, year_month, value FROM gold_kpi_monthly WHERE scope='All' ORDER BY year_month")
            forecast = (_rows(conn, "SELECT kpi, year_month, yhat, yhat_lower, yhat_upper FROM gold_kpi_forecast ORDER BY year_month")
                        if _table_exists(conn, "gold_kpi_forecast") else [])
            return jsonify({"actuals": actuals, "forecast": forecast})

    @app.get("/api/pipeline")
    def plan():
        return jsonify([{"name": n, "layer": pipeline.tasks[n].layer, "type": pipeline.tasks[n].type,
                         "depends_on": pipeline.tasks[n].depends_on} for n in pipeline.topological_order()])

    @app.post("/api/run")
    def trigger():
        body = request.get_json(silent=True) or {}
        if not lock.acquire(blocking=False):
            return jsonify({"error": "a run is already in progress"}), 409

        def work():
            try:
                Runner(pipeline).run(only=body.get("only"), from_layer=body.get("from_layer"), trigger="dashboard")
            finally:
                lock.release()

        threading.Thread(target=work, daemon=True).start()
        return jsonify({"status": "started"}), 202

    return app
