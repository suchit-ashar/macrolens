"""Fetch every indicator that has a working fetcher, merge into Parquet, print a summary.

Usage:  python -m ingest.run_all [indicator_id ...]
Exit code 1 if any fetch fails (so GitHub Actions flags it).

Parquet files keep every vintage (see docs/ARCHITECTURE.md rule 3); read them through
transform.normalize.latest_vintage.
"""
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from ingest import fbil, fred, mospi, rbi
from ingest.registry import load_registry
from transform.normalize import latest_vintage, merge_vintages, to_long

CLEAN_DIR = Path(__file__).resolve().parent.parent / "data" / "clean"

# Every fetcher is called as fetch(source_series, since) -> (DataFrame[date, value], meta).
# `since` is the last stored date, used by fetchers that download incrementally.
FETCHERS = {
    "FRED": lambda series, since: fred.fetch_series(series),
    "FBIL": fbil.fetch,
    "MoSPI": mospi.fetch,
    "RBI": rbi.fetch,
}


def update_indicator(entry: dict, clean_dir: Path = CLEAN_DIR, fetchers: dict = FETCHERS) -> pd.DataFrame:
    path = clean_dir / f"{entry['id']}.parquet"
    existing = pd.read_parquet(path) if path.exists() else None
    since = existing["date"].max().date() if existing is not None and not existing.empty else None

    raw, meta = fetchers[entry["source"]](entry["source_series"], since)
    if raw.empty and existing is None:
        raise ValueError("no observations returned")
    new = to_long(raw, entry, release_date=meta.get("last_updated"), fetched_at=meta.get("fetched_at"))
    merged = merge_vintages(existing, new, event=entry["frequency"] == "event")
    merged.to_parquet(path, index=False)
    return merged


def main(only: list[str] | None = None) -> int:
    load_dotenv()
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    registry = load_registry()
    failures, done, skipped = [], [], []

    for entry in registry.values():
        if only and entry["id"] not in only:
            continue
        if entry["source"] not in FETCHERS or entry["source_series"] == "TBD":
            skipped.append(entry["id"])
            continue
        try:
            merged = update_indicator(entry)
            last = latest_vintage(merged).iloc[-1]
            done.append(entry["id"])
            print(f"OK    {entry['id']:<22} {last['date'].date()}  {last['value']:>10.2f} {entry['unit']}")
        except Exception as e:  # keep going; report at the end
            failures.append(entry["id"])
            print(f"FAIL  {entry['id']:<22} {type(e).__name__}: {e}")

    print(f"\n{len(done)} fetched, {len(failures)} failed, {len(skipped)} not built yet"
          + (f": {', '.join(skipped)}" if skipped else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
