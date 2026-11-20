"""Command line entry point.

    python -m trackflow.cli generate              # synthetic source extracts
    python -m trackflow.cli run                   # full pipeline
    python -m trackflow.cli run --from-layer gold # rebuild Gold only
    python -m trackflow.cli run --only silver_absences   # task + everything downstream
    python -m trackflow.cli plan                  # print the execution order
    python -m trackflow.cli kpis                  # latest KPI snapshot
    python -m trackflow.cli serve                 # dashboard on :5000
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys

from .engine import Pipeline, Runner
from .generate import generate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trackflow")
    ap.add_argument("--config", default="pipelines.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--seed", type=int, default=42)
    r = sub.add_parser("run")
    r.add_argument("--only", nargs="+")
    r.add_argument("--from-layer", choices=["bronze", "silver", "gold"])
    sub.add_parser("plan")
    sub.add_parser("kpis")
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=5000)
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    pipeline = Pipeline.from_yaml(args.config)

    if args.cmd == "generate":
        for name, n in generate(pipeline.root / pipeline.settings["raw_dir"], seed=args.seed).items():
            print(f"{name:<22} {n:>7,} rows")
    elif args.cmd == "plan":
        for i, name in enumerate(pipeline.topological_order(), 1):
            t = pipeline.tasks[name]
            print(f"{i:>2}. [{t.layer:<6}] {name:<28} <- {', '.join(t.depends_on) or '-'}")
    elif args.cmd == "run":
        _, status = Runner(pipeline).run(only=args.only, from_layer=args.from_layer)
        return 0 if status == "success" else 1
    elif args.cmd == "kpis":
        conn = sqlite3.connect(pipeline.root / pipeline.settings["database"])
        rows = conn.execute("""
            SELECT kpi, year_month, value FROM gold_kpi_monthly k
            WHERE scope = 'All' AND year_month = (SELECT MAX(year_month) FROM gold_kpi_monthly)
            ORDER BY kpi""").fetchall()
        for kpi, ym, v in rows:
            print(f"{kpi:<30} {ym}  {v:7.2%}")
    elif args.cmd == "serve":
        from .dashboard import create_app
        create_app(pipeline).run(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
