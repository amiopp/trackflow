from __future__ import annotations

import sqlite3
import textwrap

import pytest

from trackflow.engine import Pipeline, PipelineError, Runner


def _pipeline(tmp_path, tasks_yaml: str, retry: str = "{ max_attempts: 3, base_delay_s: 1 }") -> Pipeline:
    header = f"settings:\n  database: wh.db\n  raw_dir: raw\n  retry: {retry}\ntasks:\n"
    body = textwrap.indent(textwrap.dedent(tasks_yaml).strip("\n"), "  ")
    (tmp_path / "pipelines.yaml").write_text(header + body + "\n")
    return Pipeline.from_yaml(tmp_path / "pipelines.yaml")


def test_topological_order_respects_dependencies(built):
    pipeline, _ = built
    order = pipeline.topological_order()
    for name, task in pipeline.tasks.items():
        for dep in task.depends_on:
            assert order.index(dep) < order.index(name)


def test_cycle_is_rejected(tmp_path):
    with pytest.raises(PipelineError, match="cycle"):
        _pipeline(tmp_path, """
            - { name: a, layer: bronze, type: sql, file: a.sql, depends_on: [b] }
            - { name: b, layer: bronze, type: sql, file: b.sql, depends_on: [a] }
        """)


def test_unknown_dependency_is_rejected(tmp_path):
    with pytest.raises(PipelineError, match="unknown task 'ghost'"):
        _pipeline(tmp_path, "- { name: a, layer: bronze, type: sql, file: a.sql, depends_on: [ghost] }")


def test_select_from_layer_and_only(built):
    pipeline, _ = built
    gold = pipeline.select(from_layer="gold")
    assert gold and all(pipeline.tasks[n].layer == "gold" for n in gold)
    partial = pipeline.select(only=["silver_absences"])
    assert partial[0] == "silver_absences"
    assert "forecast_kpis" in partial and "silver_employees" not in partial


def test_retry_with_exponential_backoff_then_skip_downstream(tmp_path, monkeypatch):
    import trackflow

    calls, sleeps = {"n": 0}, []

    def flaky(conn):
        calls["n"] += 1
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(trackflow, "tests_flaky", flaky, raising=False)

    p = _pipeline(tmp_path, """
        - { name: extract, layer: bronze, type: python, callable: "trackflow:tests_flaky" }
        - { name: model,   layer: silver, type: python, callable: "trackflow:tests_flaky", depends_on: [extract] }
    """)
    run_id, status = Runner(p, sleep=sleeps.append).run()

    assert status == "failed"
    assert calls["n"] == 3                 # model never ran
    assert sleeps == [1.0, 2.0]            # 1s -> 2s backoff between 3 attempts
    rows = sqlite3.connect(tmp_path / "wh.db").execute(
        "SELECT task, attempt, status FROM ops_task_runs WHERE run_id=? ORDER BY task, attempt", (run_id,)).fetchall()
    assert rows == [("extract", 1, "failed"), ("extract", 2, "failed"), ("extract", 3, "failed"), ("model", 0, "skipped")]


def test_quality_failure_is_not_retried(tmp_path):
    sleeps: list[float] = []
    p = _pipeline(tmp_path, """
        - { name: seed, layer: bronze, type: sql, file: seed.sql }
        - name: dq
          layer: silver
          type: quality
          depends_on: [seed]
          checks: [ { table: t, check: not_null, column: x } ]
    """)
    (tmp_path / "seed.sql").write_text("DROP TABLE IF EXISTS t; CREATE TABLE t (x INT); INSERT INTO t VALUES (1), (NULL);")
    _, status = Runner(p, sleep=sleeps.append).run()
    assert status == "failed" and sleeps == []
