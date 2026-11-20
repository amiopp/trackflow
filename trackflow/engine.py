"""TrackFlow orchestration engine.

* builds a DAG from pipelines.yaml and validates it (unknown deps, cycles)
* runs tasks in topological order with retries and exponential backoff
* skips everything downstream of a failure instead of running on bad data
* supports partial reruns: a single task, or everything from a given layer
* records every run, task attempt and data-quality result in ops_* tables
"""

from __future__ import annotations

import importlib
import logging
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import ingest, quality
from .sql import render

log = logging.getLogger("trackflow")
LAYERS = ["bronze", "silver", "gold"]

OPS_DDL = """
CREATE TABLE IF NOT EXISTS ops_runs (
    run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, status TEXT,
    trigger TEXT, selection TEXT
);
CREATE TABLE IF NOT EXISTS ops_task_runs (
    run_id TEXT, task TEXT, layer TEXT, attempt INTEGER, status TEXT,
    started_at TEXT, finished_at TEXT, duration_s REAL, rows INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS ops_dq_results (
    run_id TEXT, task TEXT, tbl TEXT, check_type TEXT, detail TEXT,
    failures INTEGER, severity TEXT, passed INTEGER
);
"""


class PipelineError(Exception):
    pass


@dataclass
class Task:
    name: str
    layer: str
    type: str
    depends_on: list[str] = field(default_factory=list)
    source: str | None = None
    file: str | None = None
    checks: list[dict] = field(default_factory=list)
    callable: str | None = None
    params: dict = field(default_factory=dict)


@dataclass
class Pipeline:
    tasks: dict[str, Task]
    settings: dict
    root: Path

    # ---------------------------------------------------------------- loading
    @classmethod
    def from_yaml(cls, path: str | Path, overrides: dict | None = None) -> Pipeline:
        path = Path(path)
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        settings = {**cfg.get("settings", {}), **(overrides or {})}
        tasks = {t["name"]: Task(**t) for t in cfg["tasks"]}
        p = cls(tasks, settings, path.parent)
        p.validate()
        return p

    def validate(self) -> None:
        for t in self.tasks.values():
            if t.layer not in LAYERS:
                raise PipelineError(f"{t.name}: unknown layer '{t.layer}'")
            for dep in t.depends_on:
                if dep not in self.tasks:
                    raise PipelineError(f"{t.name}: depends on unknown task '{dep}'")
        self.topological_order()  # raises on cycles

    # ------------------------------------------------------------- planning
    def topological_order(self) -> list[str]:
        indegree = {n: len(t.depends_on) for n, t in self.tasks.items()}
        children: dict[str, list[str]] = {n: [] for n in self.tasks}
        for n, t in self.tasks.items():
            for dep in t.depends_on:
                children[dep].append(n)
        ready = sorted(n for n, d in indegree.items() if d == 0)
        order: list[str] = []
        while ready:
            n = ready.pop(0)
            order.append(n)
            for c in sorted(children[n]):
                indegree[c] -= 1
                if indegree[c] == 0:
                    ready.append(c)
        if len(order) != len(self.tasks):
            cyclic = sorted(set(self.tasks) - set(order))
            raise PipelineError(f"dependency cycle between: {', '.join(cyclic)}")
        return order

    def downstream(self, names: set[str]) -> set[str]:
        out, changed = set(names), True
        while changed:
            changed = False
            for n, t in self.tasks.items():
                if n not in out and any(d in out for d in t.depends_on):
                    out.add(n)
                    changed = True
        return out

    def select(self, only: list[str] | None = None, from_layer: str | None = None) -> list[str]:
        order = self.topological_order()
        if only:
            unknown = set(only) - set(self.tasks)
            if unknown:
                raise PipelineError(f"unknown task(s): {', '.join(sorted(unknown))}")
            chosen = self.downstream(set(only))
        elif from_layer:
            if from_layer not in LAYERS:
                raise PipelineError(f"unknown layer '{from_layer}'")
            floor = LAYERS.index(from_layer)
            chosen = {n for n, t in self.tasks.items() if LAYERS.index(t.layer) >= floor}
        else:
            chosen = set(order)
        return [n for n in order if n in chosen]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: str | Path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(OPS_DDL)
    return conn


class Runner:
    def __init__(self, pipeline: Pipeline, sleep: Callable[[float], None] = time.sleep):
        self.p = pipeline
        self.sleep = sleep
        self.db_path = self.p.root / self.p.settings["database"]
        self.raw_dir = self.p.root / self.p.settings["raw_dir"]

    # ----------------------------------------------------------- task types
    def _execute(self, conn: sqlite3.Connection, task: Task, run_id: str) -> int | None:
        if task.type == "ingest":
            table = "bronze_" + Path(task.source).stem
            return ingest.load_csv(conn, self.raw_dir / task.source, table, run_id)
        if task.type == "sql":
            conn.executescript(render(self.p.root / task.file, **self.p.settings.get("calendar", {})))
            return None
        if task.type == "quality":
            results = quality.run_checks(conn, task.checks)
            conn.executemany(
                "INSERT INTO ops_dq_results VALUES (?,?,?,?,?,?,?,?)",
                [(run_id, task.name, r.table, r.check, r.detail, r.failures, r.severity, int(r.passed))
                 for r in results])
            errors = [r for r in results if not r.passed and r.severity == "error"]
            for r in results:
                if not r.passed:
                    log.warning("DQ %s %s.%s [%s]: %d failing rows", r.severity.upper(), r.table, r.check,
                                r.detail, r.failures)
            if errors:
                conn.commit()
                raise PipelineError(f"{len(errors)} data quality check(s) failed")
            return len(results)
        if task.type == "python":
            module, func = task.callable.split(":")
            return getattr(importlib.import_module(module), func)(conn, **task.params)
        raise PipelineError(f"{task.name}: unknown task type '{task.type}'")

    # ----------------------------------------------------------------- run
    def run(self, only: list[str] | None = None, from_layer: str | None = None,
            trigger: str = "manual") -> tuple[str, str]:
        plan = self.p.select(only, from_layer)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        retry = self.p.settings.get("retry", {})
        max_attempts, base_delay = int(retry.get("max_attempts", 1)), float(retry.get("base_delay_s", 0))
        selection = ",".join(only) if only else (f"from:{from_layer}" if from_layer else "all")

        conn = connect(self.db_path)
        conn.execute("INSERT INTO ops_runs VALUES (?,?,?,?,?,?)", (run_id, _now(), None, "running", trigger, selection))
        conn.commit()
        log.info("run %s started: %d task(s) [%s]", run_id, len(plan), selection)

        failed: set[str] = set()
        for name in plan:
            task = self.p.tasks[name]
            if any(d in failed for d in task.depends_on):
                failed.add(name)
                conn.execute("INSERT INTO ops_task_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (run_id, name, task.layer, 0, "skipped", _now(), _now(), 0, None, "upstream failed"))
                conn.commit()
                log.warning("  %-28s skipped (upstream failed)", name)
                continue
            for attempt in range(1, max_attempts + 1):
                started, t0 = _now(), time.perf_counter()
                try:
                    rows = self._execute(conn, task, run_id)
                    conn.commit()
                    status, error = "success", None
                except Exception as exc:  # noqa: BLE001 - every failure is recorded
                    conn.rollback()
                    status, rows, error = "failed", None, f"{type(exc).__name__}: {exc}"
                dur = round(time.perf_counter() - t0, 3)
                conn.execute("INSERT INTO ops_task_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (run_id, name, task.layer, attempt, status, started, _now(), dur, rows, error))
                conn.commit()
                if status == "success":
                    unit = {"quality": "checks passed", "python": "rows written"}.get(task.type, "rows")
                    log.info("  %-28s ok    %6.2fs %s", name, dur, f"{rows:,} {unit}" if rows is not None else "")
                    break
                # data-quality failures are deterministic: retrying would not help
                retryable = task.type != "quality" and attempt < max_attempts
                log.error("  %-28s FAIL  attempt %d/%d: %s", name, attempt, max_attempts, error)
                if not retryable:
                    failed.add(name)
                    break
                self.sleep(base_delay * 2 ** (attempt - 1))

        status = "failed" if failed else "success"
        conn.execute("UPDATE ops_runs SET finished_at=?, status=? WHERE run_id=?", (_now(), status, run_id))
        conn.commit()
        conn.close()
        log.info("run %s finished: %s", run_id, status.upper())
        return run_id, status
