"""Bronze ingestion: land a raw extract untouched, plus lineage columns."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def load_csv(conn: sqlite3.Connection, path: Path, table: str, batch_id: str) -> int:
    """Replace ``table`` with the file contents. Every column is kept as text:
    typing and cleaning belong to Silver, so Bronze is always a faithful copy."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df["_batch_id"] = batch_id
    df["_source_file"] = path.name
    df["_ingested_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    df.to_sql(table, conn, if_exists="replace", index=False)
    return len(df)
