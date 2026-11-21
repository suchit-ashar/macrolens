"""One-time import of the RBI policy repo rate history (already done; not part of the daily run).

Source: RBI Handbook of Statistics on Indian Economy, Table 40 "Major Monetary Policy Rates and
Reserve Requirements" (xlsx), 2008 onwards. rbidocs.rbi.org.in shows scripts a bot-check page,
so the file was downloaded once in a browser into data/raw/rbi/.
https://rbi.org.in/Scripts/AnnualPublications.aspx?head=Handbook+of+Statistics+on+Indian+Economy

Changes after the Handbook edition come from the daily job (ingest/rbi.py), which dates them
from the MPC press release automatically. Re-running this script merges the Handbook rows with
whatever the daily job has stored, so nothing is lost.

Usage:  python -m ingest.rbi_history data/raw/rbi/<Table 40 file>.xlsx
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
import pandas as pd

from ingest.registry import load_registry
from transform.normalize import to_long

ROOT = Path(__file__).resolve().parent.parent
CLEAN_PATH = ROOT / "data" / "clean" / "in_repo_rate.parquet"


class Table40Error(ValueError):
    pass


def parse_table40(path: Path) -> pd.DataFrame:
    """Return DataFrame[date, value] of repo-rate changes from Handbook Table 40.

    Layout: header row with 'Effective Date', a sub-header row with 'Repo' under the LAF
    column, then one row per date; '-' means no change. The table spans several sheets.
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = []
    for ws in wb.worksheets:
        data = [list(r) for r in ws.iter_rows(values_only=True)]
        date_col = repo_col = None
        for r in data:
            cells = [str(c).strip() if c is not None else "" for c in r]
            if "Effective Date" in cells:
                date_col = cells.index("Effective Date")
            if date_col is not None and "Repo" in cells:
                repo_col = cells.index("Repo")
                break
        if date_col is None or repo_col is None:
            continue
        for r in data:
            d, v = r[date_col], r[repo_col]
            if isinstance(d, datetime) and isinstance(v, (int, float)):
                rows.append((pd.Timestamp(d.date()), float(v)))
    if not rows:
        raise Table40Error(f"No repo-rate rows found in {path} (sheets: {wb.sheetnames})")
    df = pd.DataFrame(rows, columns=["date", "value"]).drop_duplicates().sort_values("date")
    if df["date"].duplicated().any():
        raise Table40Error("Conflicting repo rates for the same effective date")
    if not df["value"].between(0, 20).all():
        raise Table40Error("Repo rate outside 0-20% in Table 40")
    return df.reset_index(drop=True)


def change_points(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the first row of each run of equal values (the date the rate took effect)."""
    df = df.sort_values("date").drop_duplicates("date", keep="last")
    keep = df["value"].ne(df["value"].shift())
    return df[keep].reset_index(drop=True)


def build_history(table40: pd.DataFrame, stored: pd.DataFrame | None) -> pd.DataFrame:
    """Combine Handbook rows with what the daily job has stored (later changes)."""
    parts = [table40.assign(origin="handbook")]
    if stored is not None and not stored.empty:
        parts.append(stored[["date", "value"]].assign(origin="daily"))
    combined = pd.concat(parts, ignore_index=True)
    # On the same date the Handbook wins.
    combined["rank"] = combined["origin"].map({"handbook": 0, "daily": 1})
    combined = combined.sort_values(["date", "rank"]).drop_duplicates("date", keep="first")
    return change_points(combined[["date", "value"]])


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    entry = load_registry()["in_repo_rate"]
    table40 = parse_table40(Path(argv[0]))
    stored = pd.read_parquet(CLEAN_PATH) if CLEAN_PATH.exists() else None
    history = build_history(table40, stored)

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = to_long(history, entry, fetched_at=fetched_at)
    out["release_date"] = out["date"].dt.strftime("%Y-%m-%d")  # announced on the effective date
    CLEAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(CLEAN_PATH, index=False)

    print(f"Table 40: {len(table40)} repo changes, {table40['date'].min().date()} to {table40['date'].max().date()}")
    print(f"Saved {len(out)} change points to {CLEAN_PATH}")
    print(out[["date", "value"]].tail(8).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
