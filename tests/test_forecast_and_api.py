from __future__ import annotations

import numpy as np

from trackflow.dashboard import create_app
from trackflow.forecast import fit_predict


def test_model_recovers_trend_and_seasonality():
    months = np.arange(36)
    y = 0.02 + 0.0002 * months + 0.01 * (months % 12 == 0)  # January spike
    pred, sigma = fit_predict(y, start_month=1, horizon=12)
    expected = 0.02 + 0.0002 * np.arange(36, 48) + 0.01 * (np.arange(36, 48) % 12 == 0)
    assert np.allclose(pred, expected, atol=1e-6)
    assert sigma < 1e-6


def test_forecast_written_for_horizon_and_bounded(conn):
    rows = conn.execute("SELECT kpi, COUNT(*), MIN(yhat_lower), MAX(yhat_upper) FROM gold_kpi_forecast GROUP BY kpi").fetchall()
    assert {r[0] for r in rows} == {"absenteeism_rate", "turnover_rate", "fleet_availability"}
    for _, n, lo, hi in rows:
        assert n == 6 and 0 <= lo <= hi <= 1


def test_forecast_is_backtested_against_baseline(conn):
    for kpi, mae_model, mae_naive in conn.execute("SELECT kpi, mae_model, mae_seasonal_naive FROM gold_kpi_forecast_eval"):
        assert mae_model >= 0 and mae_naive >= 0, kpi


def test_dashboard_api(built):
    pipeline, _ = built
    client = create_app(pipeline).test_client()
    assert client.get("/").status_code == 200
    runs = client.get("/api/runs").get_json()
    assert runs and runs[0]["status"] == "success"
    detail = client.get(f"/api/runs/{runs[0]['run_id']}").get_json()
    assert len(detail["tasks"]) == len(pipeline.tasks)
    assert all(q["passed"] or q["severity"] == "warn" for q in detail["quality"])
    kpis = client.get("/api/kpis").get_json()
    assert kpis["actuals"] and kpis["forecast"]
