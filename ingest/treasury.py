"""US Treasury daily par yield curve rates, straight from the US Treasury (home.treasury.gov).

FRED republishes the same numbers (DGS2, DGS10, ...) about one business day later, so reading the
Treasury's own CSV gives the previous US session's close by the next Indian morning.

One CSV per calendar year; a run downloads only the years from the last stored date onward.
source_series: "<curve>:<column>", e.g. "nominal:10 Yr" or "real:10 YR" (column names as in the CSV header).
"""
import io
from datetime import date, datetime, timezone

import pandas as pd

from ingest.http import FetchError, get

URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
       "{year}/all?type={kind}&field_tdr_date_value={year}&page&_format=csv")
CURVES = {"nominal": "daily_treasury_yield_curve", "real": "daily_treasury_real_yield_curve"}
FIRST_YEAR = 2000  # used only when nothing is stored yet


class TreasuryError(FetchError):
    pass


def parse_csv(text: str, column: str) -> pd.DataFrame:
    raw = pd.read_csv(io.StringIO(text))
    cols = {c.strip().lower(): c for c in raw.columns}
    if "date" not in cols or column.strip().lower() not in cols:
        raise TreasuryError(f"column '{column}' not in Treasury CSV (columns: {list(raw.columns)[:8]}...)")
    df = pd.DataFrame({"date": pd.to_datetime(raw[cols["date"]], format="%m/%d/%Y", errors="coerce"),
                       "value": pd.to_numeric(raw[cols[column.strip().lower()]], errors="coerce")})
    df = df.dropna().sort_values("date").reset_index(drop=True)
    bad = df[(df["value"] < -5) | (df["value"] > 25)]
    if not bad.empty:
        raise TreasuryError(f"Treasury {column} value {bad['value'].iloc[0]} on {bad['date'].iloc[0].date()} looks wrong")
    return df


def fetch(source_series: str, since=None, session=None, today: date | None = None):
    curve, column = source_series.split(":", 1)
    if curve not in CURVES:
        raise TreasuryError(f"unknown Treasury curve '{curve}'")
    today = today or datetime.now(timezone.utc).date()
    start = since.year if since else FIRST_YEAR
    frames = []
    for year in range(start, today.year + 1):
        text = get(URL.format(year=year, kind=CURVES[curve]), session=session).text
        if text.strip():
            frames.append(parse_csv(text, column))
    if not frames:
        raise TreasuryError("Treasury returned no data")
    df = pd.concat(frames).drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    if since is not None:
        df = df[df["date"] >= pd.Timestamp(since)]
    meta = {"last_updated": str(df["date"].iloc[-1].date()) if not df.empty else None,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return df.reset_index(drop=True), meta
