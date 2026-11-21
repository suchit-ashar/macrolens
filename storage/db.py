"""DuckDB access layer over the Parquet files in data/clean.

The Parquet files are the source of truth (committed by the daily job). The DuckDB file is
a disposable, rebuildable cache: `build()` recreates it from Parquet + the registry.

Tables / views:
  observations   every stored vintage (long format, docs/ARCHITECTURE.md)
  indicators     config/indicators.yaml
  latest         view: one row per (indicator_id, date), the most recent vintage
  summary        view: latest observation per indicator, with the previous one for change
"""
from pathlib import Path

import duckdb
import pandas as pd

from ingest.registry import load_registry

ROOT = Path(__file__).resolve().parent.parent
CLEAN_DIR = ROOT / "data" / "clean"
DB_PATH = ROOT / "data" / "macrolens.duckdb"

INDICATOR_COLUMNS = ["id", "country", "topic", "name", "source", "source_series", "unit", "frequency",
                     "source_url", "note"]


def _indicators_frame(registry: dict) -> pd.DataFrame:
    return pd.DataFrame([{k: e.get(k) for k in INDICATOR_COLUMNS} for e in registry.values()])


def build(db_path: Path | str = DB_PATH, clean_dir: Path = CLEAN_DIR, registry: dict | None = None):
    """(Re)create the database. Pass db_path=':memory:' for an in-memory database."""
    registry = registry or load_registry()
    files = sorted(Path(clean_dir).glob("*.parquet"))
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(db_path).unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    indicators = _indicators_frame(registry)
    con.execute("CREATE TABLE indicators AS SELECT * FROM indicators")
    if files:
        paths = [str(p).replace("\\", "/") for p in files]
        con.execute("""
            CREATE TABLE observations AS
            SELECT CAST(date AS DATE) AS date, indicator_id, country, CAST(value AS DOUBLE) AS value,
                   unit, frequency, source, source_url,
                   CAST(release_date AS VARCHAR) AS release_date, CAST(fetched_at AS VARCHAR) AS fetched_at
            FROM read_parquet(?, union_by_name = true)
        """, [paths])
    else:
        con.execute("""CREATE TABLE observations (date DATE, indicator_id VARCHAR, country VARCHAR,
                       value DOUBLE, unit VARCHAR, frequency VARCHAR, source VARCHAR, source_url VARCHAR,
                       release_date VARCHAR, fetched_at VARCHAR)""")
    con.execute("""
        CREATE VIEW latest AS
        SELECT * EXCLUDE (rn) FROM (
            SELECT *, row_number() OVER (PARTITION BY indicator_id, date
                                         ORDER BY fetched_at DESC NULLS LAST) AS rn
            FROM observations) WHERE rn = 1
    """)
    con.execute("""
        CREATE VIEW summary AS
        WITH ranked AS (
            SELECT *, row_number() OVER (PARTITION BY indicator_id ORDER BY date DESC) AS k FROM latest)
        SELECT i.id AS indicator_id, i.name, i.country, i.topic, i.note, i.unit, i.frequency, i.source, i.source_url,
               cur.date, cur.value, prev.date AS prev_date, prev.value AS prev_value,
               cur.release_date, cur.fetched_at, (SELECT min(date) FROM latest l WHERE l.indicator_id = i.id) AS first_date
        FROM indicators i
        LEFT JOIN ranked cur  ON cur.indicator_id = i.id AND cur.k = 1
        LEFT JOIN ranked prev ON prev.indicator_id = i.id AND prev.k = 2
        ORDER BY i.country, i.id
    """)
    return con


def connect(rebuild: bool = False):
    """Open the database, rebuilding it if missing, requested, or older than any Parquet file."""
    newest = max((p.stat().st_mtime for p in CLEAN_DIR.glob("*.parquet")), default=0)
    if rebuild or not DB_PATH.exists() or DB_PATH.stat().st_mtime < newest:
        build().close()
    return duckdb.connect(str(DB_PATH), read_only=True)


def series(con, indicator_id: str) -> pd.DataFrame:
    return con.execute("SELECT date, value FROM latest WHERE indicator_id = ? ORDER BY date",
                       [indicator_id]).df()


def vintages(con, indicator_id: str) -> pd.DataFrame:
    return con.execute("SELECT date, value, fetched_at FROM observations WHERE indicator_id = ? "
                       "ORDER BY date, fetched_at", [indicator_id]).df()


if __name__ == "__main__":
    con = build()
    print(con.execute("SELECT indicator_id, date, value, unit FROM summary").df().to_string(index=False))
    print(f"\nBuilt {DB_PATH}")
