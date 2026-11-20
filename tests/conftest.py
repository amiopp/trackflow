from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from trackflow.engine import Pipeline, Runner
from trackflow.generate import generate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def built(tmp_path_factory) -> tuple[Pipeline, sqlite3.Connection]:
    """Generate a small synthetic dataset and run the full pipeline once for the session."""
    work = tmp_path_factory.mktemp("platform")
    shutil.copy(ROOT / "pipelines.yaml", work / "pipelines.yaml")
    shutil.copytree(ROOT / "sql", work / "sql")
    generate(work / "data" / "raw", employees=300, seed=7)
    pipeline = Pipeline.from_yaml(work / "pipelines.yaml")
    _, status = Runner(pipeline, sleep=lambda s: None).run()
    assert status == "success"
    conn = sqlite3.connect(work / "data" / "warehouse.db")
    yield pipeline, conn
    conn.close()


@pytest.fixture
def conn(built) -> sqlite3.Connection:
    return built[1]
