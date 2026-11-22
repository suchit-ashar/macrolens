"""Fetch every indicator that has a working fetcher, merge into Parquet, print a summary.

Usage:  python -m ingest.run_all [indicator_id ...]
Exit code 1 if any fetch fails (so GitHub Actions flags it).

Parquet files keep every vintage (see docs/ARCHITECTURE.md rule 3); read them through
transform.normalize.latest_vintage.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from ingest import budget, fbil, fred, ibja, imf, mospi, rbi, rbi_releases, trade, worldbank
from ingest.registry import load_registry
from transform.checks import run_checks, to_records
from transform.normalize import latest_vintage, merge_vintages, to_long

CLEAN_DIR = Path(__file__).resolve().parent.parent / "data" / "clean"
LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "logs"

# Every fetcher is called as fetch(source_series, since) -> (DataFrame[date, value], meta).
# `since` is the last stored date, used by fetchers that download incrementally.
FETCHERS = {
    "FRED": lambda series, since: fred.fetch_series(series),
    "FBIL": fbil.fetch,
    "MoSPI": mospi.fetch,
    "RBI": rbi.fetch,
    "WorldBank": worldbank.fetch,
    "IMF": imf.fetch,
    "Commerce": trade.fetch,
    "Union Budget": budget.fetch,
    "CGA": budget.fetch,
    "RBIRelease": rbi_releases.fetch,
    "IBJA": ibja.fetch,
}


def fetcher_key(entry: dict) -> str:
    """Registry `fetcher` overrides `source` (e.g. RBI press-release series show source RBI)."""
    return entry.get("fetcher") or entry["source"]


def update_indicator(entry: dict, clean_dir: Path = CLEAN_DIR, fetchers: dict = FETCHERS) -> pd.DataFrame:
    path = clean_dir / f"{entry['id']}.parquet"
    existing = pd.read_parquet(path) if path.exists() else None
    since = existing["date"].max().date() if existing is not None and not existing.empty else None

    raw, meta = fetchers[fetcher_key(entry)](entry["source_series"], since)
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
    failures, done, skipped, lines = [], [], [], []

    def log(line: str):
        print(line)
        lines.append(line)

    started = datetime.now(timezone.utc)
    for entry in registry.values():
        if only and entry["id"] not in only:
            continue
        if fetcher_key(entry) not in FETCHERS or entry["source_series"] == "TBD":
            skipped.append(entry["id"])
            continue
        t0 = datetime.now(timezone.utc)
        try:
            merged = update_indicator(entry)
            last = latest_vintage(merged).iloc[-1]
            done.append(entry["id"])
            log(f"OK    {entry['id']:<26} {last['date'].date()}  {last['value']:>14.2f} {entry['unit']}"
                f"  ({(datetime.now(timezone.utc) - t0).total_seconds():.0f}s)")
        except Exception as e:  # keep going; report at the end
            failures.append(entry["id"])
            log(f"FAIL  {entry['id']:<26} [{fetcher_key(entry)}] {type(e).__name__}: {str(e)[:300]}")

    log(f"\n{len(done)} fetched, {len(failures)} failed, {len(skipped)} not built yet"
        + (f": {', '.join(skipped)}" if skipped else ""))

    issues = quality_report(registry, only)
    errors = [i for i in issues if i.severity == "error"]
    lines += [f"QUALITY {i.severity.upper():<5} {i.indicator_id:<26} {i.check:<9} {i.message}" for i in issues]
    # Committed by the workflow so failures can be read without opening the Actions log.
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    header = (f"Run started {started:%Y-%m-%d %H:%M} UTC, took {(datetime.now(timezone.utc) - started).total_seconds():.0f}s. "
              f"{len(done)} ok, {len(failures)} failed, {len(errors)} quality error(s).\n")
    (LOG_DIR / "last_run.txt").write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failures or errors else 0


def quality_report(registry: dict, only: list[str] | None = None) -> list:
    """Run transform/checks.py on every stored series; print and save the result."""
    issues = []
    for entry in registry.values():
        path = CLEAN_DIR / f"{entry['id']}.parquet"
        if (only and entry["id"] not in only) or not path.exists():
            continue
        issues += run_checks(pd.read_parquet(path), entry)
    print(f"\nQuality: {sum(i.severity == 'error' for i in issues)} error(s), "
          f"{sum(i.severity == 'warn' for i in issues)} warning(s)")
    for i in issues:
        print(f"  {i.severity.upper():<5} {i.indicator_id:<22} {i.check:<9} {i.message}")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "quality.json").write_text(json.dumps(
        {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "issues": to_records(issues)},
        indent=2), encoding="utf-8")
    return issues


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
