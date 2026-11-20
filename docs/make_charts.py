"""Render the README chart from a built warehouse:  python docs/make_charts.py"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
conn = sqlite3.connect(ROOT / "data" / "warehouse.db")
actual = pd.read_sql("SELECT * FROM gold_kpi_monthly", conn)
fc = pd.read_sql("SELECT * FROM gold_kpi_forecast", conn)
for df in (actual, fc):
    df["month"] = pd.PeriodIndex(df.year_month, freq="M").to_timestamp()

plt.rcParams.update({"svg.fonttype": "none", "font.family": "sans-serif", "font.size": 10,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titleweight": "bold", "axes.titlesize": 11})
fig, axes = plt.subplots(2, 2, figsize=(13, 7.5))
BLUE, AMBER, GREY = "#2563eb", "#d97706", "#9ca3af"


def with_forecast(ax, kpi, title):
    a = actual[(actual.kpi == kpi) & (actual.scope == "All")]
    f = fc[fc.kpi == kpi]
    ax.plot(a.month, a.value, color=BLUE, lw=2, label="Actual")
    if len(f):
        ax.plot([a.month.iloc[-1], *f.month], [a.value.iloc[-1], *f.yhat], color=AMBER, lw=2, ls="--", label="Forecast")
        ax.fill_between(f.month, f.yhat_lower, f.yhat_upper, color=AMBER, alpha=.15, label="80% interval")
    ax.set_title(title, loc="left")
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=1))
    ax.legend(frameon=False, fontsize=9)


with_forecast(axes[0, 0], "absenteeism_rate", "Absenteeism rate · winter peaks, 6-month forecast")
with_forecast(axes[0, 1], "fleet_availability", "Fleet availability (network) · summer dips")

pm = actual[actual.kpi == "preventive_maintenance_rate"]
axes[1, 0].bar(pm.month, pm.value, width=20, color=BLUE, alpha=.85)
axes[1, 0].axhline(0.85, color=GREY, ls=":", lw=1.5)
axes[1, 0].text(pm.month.iloc[0], 0.86, "target 85%", color="#6b7280", fontsize=9)
axes[1, 0].set_ylim(0.5, 1)
axes[1, 0].set_title("Preventive maintenance done on time", loc="left")
axes[1, 0].yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
axes[1, 0].xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
axes[1, 0].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

lines = actual[(actual.kpi == "fleet_availability") & (actual.scope != "All")]
by_line = lines.groupby("scope").apply(lambda g: g.numerator.sum() / g.denominator.sum(), include_groups=False)
by_line = by_line.sort_values()
axes[1, 1].barh(by_line.index, by_line.values, color=[AMBER if v == by_line.min() else BLUE for v in by_line.values])
axes[1, 1].set_xlim(by_line.min() - 0.01, 1)
axes[1, 1].set_title("Availability by line, 2023–2025", loc="left")
axes[1, 1].xaxis.set_major_formatter(PercentFormatter(1, decimals=1))

fig.suptitle("Metrolink City · Gold layer KPIs (synthetic data)", x=0.01, ha="left", fontsize=13, fontweight="bold")
fig.tight_layout()
out = ROOT / "docs" / "kpis.svg"
fig.savefig(out, metadata={"Date": None})
# trim coordinate precision to 0.1 px: same picture, far fewer bytes
svg = re.sub(r"(\d+\.\d)\d{2,}", r"\1", out.read_text())
svg = re.sub(r"font-family: [^;\"]+", "font-family: sans-serif", svg)
svg = re.sub(r' transform="rotate\(-0 [^)]*\)"', "", svg)
svg = re.sub(r"<metadata>.*?</metadata>\n?", "", svg, flags=re.S)
svg = re.sub(r"\n\s*", "\n", svg)
out.write_text(svg)
print(f"wrote {out}")
