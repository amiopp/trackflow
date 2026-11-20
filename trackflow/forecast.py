"""KPI forecasting, written back to Gold so BI shows actuals and predictions together.

Model: linear trend + month-of-year seasonality (ordinary least squares), with an
80% interval from the residual spread. Small, explainable, and dependency-light.
Before trusting it, each series is back-tested on the last ``horizon`` months
against a seasonal-naive baseline (same month last year); both errors are stored
in ``gold_kpi_forecast_eval`` so the model has to keep earning its place.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

Z80 = 1.2816


def _features(t: np.ndarray, months: np.ndarray) -> np.ndarray:
    season = np.zeros((len(t), 11))
    for i, m in enumerate(months):
        if m > 1:
            season[i, m - 2] = 1.0
    return np.column_stack([t, season])


def fit_predict(y: np.ndarray, start_month: int, horizon: int) -> tuple[np.ndarray, float]:
    """Fit on ``y`` (monthly, first month = ``start_month``); return forecasts and residual std."""
    n = len(y)
    t = np.arange(n + horizon, dtype=float)
    months = (np.arange(n + horizon) + start_month - 1) % 12 + 1
    X = _features(t, months)
    model = LinearRegression().fit(X[:n], y)
    resid = y - model.predict(X[:n])
    dof = max(n - X.shape[1] - 1, 1)
    return model.predict(X[n:]), float(np.sqrt((resid ** 2).sum() / dof))


def _mae(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a - b)))


def run(conn: sqlite3.Connection, horizon: int = 6, kpis: list[str] | None = None) -> int:
    df = pd.read_sql("SELECT kpi, year_month, value FROM gold_kpi_monthly WHERE scope = 'All' ORDER BY year_month", conn)
    if kpis:
        df = df[df.kpi.isin(kpis)]

    forecasts, evals = [], []
    for kpi, g in df.groupby("kpi"):
        g = g.sort_values("year_month")
        y = g.value.to_numpy(dtype=float)
        first = pd.Period(g.year_month.iloc[0], "M")
        if len(y) < 24:  # need two seasons to estimate monthly effects
            continue

        # back-test: hold out the last `horizon` months
        train, test = y[:-horizon], y[-horizon:]
        pred, _ = fit_predict(train, first.month, horizon)
        naive = y[-horizon - 12:-12]
        evals.append((kpi, horizon, _mae(test, pred), _mae(test, naive)))

        # final model on all history
        yhat, sigma = fit_predict(y, first.month, horizon)
        last = pd.Period(g.year_month.iloc[-1], "M")
        for i, v in enumerate(yhat, start=1):
            forecasts.append((
                kpi, "All", str(last + i), float(np.clip(v, 0, 1)),
                float(np.clip(v - Z80 * sigma, 0, 1)), float(np.clip(v + Z80 * sigma, 0, 1)),
                "ols_trend_seasonal", str(last),
            ))

    conn.executescript("""
        DROP TABLE IF EXISTS gold_kpi_forecast;
        CREATE TABLE gold_kpi_forecast (kpi TEXT, scope TEXT, year_month TEXT, yhat REAL,
            yhat_lower REAL, yhat_upper REAL, model TEXT, trained_through TEXT,
            PRIMARY KEY (kpi, scope, year_month));
        DROP TABLE IF EXISTS gold_kpi_forecast_eval;
        CREATE TABLE gold_kpi_forecast_eval (kpi TEXT PRIMARY KEY, holdout_months INTEGER,
            mae_model REAL, mae_seasonal_naive REAL);
    """)
    conn.executemany("INSERT INTO gold_kpi_forecast VALUES (?,?,?,?,?,?,?,?)", forecasts)
    conn.executemany("INSERT INTO gold_kpi_forecast_eval VALUES (?,?,?,?)", evals)
    return len(forecasts)
