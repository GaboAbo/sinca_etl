"""Load step: upsert clean series into the local SQLite database.

Rows are keyed on ``(station, pollutant, timestamp)``. A stored row is only
overwritten when the incoming reading has a higher ``quality_rank``, so
loads are idempotent and never downgrade a reading.
"""

import sqlite3
import pandas as pd

from pathlib import Path
from datetime import date


DB_PATH = Path("data/sinca.db")

def to_sqlite(
        df: pd.DataFrame,
        station: str,
        pollutant: str,
        db_path: Path = DB_PATH,
        table: str = "measurements") -> dict:
    """Upsert a clean series into SQLite and report what changed.

    Creates the database file and table if needed. Each row is inserted,
    or, if a row with the same key exists, updated only when the incoming
    ``quality_rank`` is strictly higher.

    Args:
        df: Clean series as returned by :func:`src.transform.clean`,
            indexed by ``timestamp``.
        station: Station code stored on every row.
        pollutant: Parameter code stored on every row.
        db_path: SQLite database file.
        table: Table name. Inserted into the SQL as-is, so it must not come
            from user input.

    Returns:
        Row counts for this call: ``sent`` (rows passed in), ``inserted``
        (new rows), ``updated`` (stored rows upgraded to a better tier),
        ``unchanged`` (rows skipped because the stored reading was at least
        as good) and ``total`` (rows now stored for this station and
        pollutant).
    """
    df = df.reset_index()
    df["station"] = station
    df["pollutant"] = pollutant
    df["timestamp"] = df["timestamp"].astype(str)
    df["is_imputed"] = df["is_imputed"].astype(int)
    df["value"] = df["value"].astype("object").where(df["value"].notna(), None)
    

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
        station TEXT,
        pollutant TEXT,
        timestamp TEXT,
        value REAL,
        quality TEXT,
        quality_rank INTEGER,
        is_imputed INTEGER,
        updated_at DATETIME,
        PRIMARY KEY(station, pollutant, timestamp)
        )
        """
    )
    cols = ["station", "pollutant", "timestamp", "value", "quality", "quality_rank", "is_imputed"]
    placeholders = ",".join("?"*len(cols))

    changes_before = conn.total_changes
    before = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE station=? AND pollutant=?",
        (station, pollutant)
    ).fetchone()[0]

    conn.executemany(
        f"""
        INSERT INTO {table}
            ({','.join(cols)}, updated_at)
            VALUES ({placeholders}, datetime('now'))
        ON CONFLICT(station, pollutant, timestamp) DO UPDATE SET
            value = excluded.value,
            quality = excluded.quality,
            quality_rank = excluded.quality_rank,
            is_imputed = excluded.is_imputed,
            updated_at = excluded.updated_at
        WHERE excluded.quality_rank > {table}.quality_rank
        """,
        df[cols].itertuples(index=False, name=None)
    )
    conn.commit()
    changes = conn.total_changes - changes_before 

    after = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE station=? AND pollutant=?",
        (station, pollutant)
    ).fetchone()[0]

    """
    Still working on it: supposed to catch any inserted value out of range.
    But it needs to be scalable, so I have to set low and high thresholds for any variable

    negatives = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE value < 0"
    )"""

    length = len(df)
    inserted = after - before
    updated  = changes - inserted
    unchanged = length - inserted - updated
    conn.close()

    return {"sent": length, "inserted": inserted, "updated": updated, "unchanged": unchanged, "total": after}


def get_last_date(
        station: str,
        pollutant: str,
        db_path: Path = Path("data/sinca.db"),
        table: str = "measurements") -> date | None:
    """Return the date of the latest stored reading for a series.

    Args:
        station: Station code.
        pollutant: Parameter code.
        db_path: SQLite database file.
        table: Table name. Inserted into the SQL as-is, so it must not come
            from user input.

    Returns:
        The date of the most recent ``timestamp`` for this station and
        pollutant, or ``None`` if the database, the table or the series
        doesn't exist yet.
    """
    if not db_path.exists():
        return None

    conn = sqlite3.connect(db_path)
    try:
        exists = conn.execute(
            f"SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,)).fetchone()
        if not exists:
            return None
        row = conn.execute(
            f"SELECT MAX(timestamp) FROM {table} WHERE station=? AND pollutant=?",
            (station, pollutant)).fetchone()
    finally:
        conn.close()

    return pd.Timestamp(row[0]).date() if row and row[0] else None    
