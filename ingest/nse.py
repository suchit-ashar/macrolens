"""Daily closing values of NSE indices from NSE's official end-of-day file.

NSE publishes one CSV per trading day, "ind_close_all_DDMMYYYY.csv", with open/high/low/close and
% change for every NSE index (Nifty 50, Nifty Bank, sector indices, India VIX, ...). It appears in the
evening after the close; weekends and market holidays have no file (404), which is expected.

Each day's file is downloaded once and kept in data/raw/nse/ (cached between CI runs), so a run only
asks NSE for the days after the last stored date. All series share the same files.
source_series: the "Index Name" exactly as in the file, e.g. "Nifty 50" or "India VIX".
"""
import io
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from ingest.http import USER_AGENT, FetchError

URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "nse"
IST = timezone(timedelta(hours=5, minutes=30))
BACKFILL_DAYS = 120  # history to load when a series has nothing stored yet
PAUSE = 0.5  # seconds between downloads
_memo: dict[date, pd.DataFrame | None] = {}


class NseError(FetchError):
    pass


def parse_file(text: str) -> pd.DataFrame:
    """One day's file -> DataFrame[index, date, close]."""
    raw = pd.read_csv(io.StringIO(text))
    raw.columns = [c.strip() for c in raw.columns]
    need = {"Index Name", "Index Date", "Closing Index Value"}
    if not need <= set(raw.columns):
        raise NseError(f"NSE index file has unexpected columns: {list(raw.columns)[:6]}")
    out = pd.DataFrame({"index": raw["Index Name"].astype(str).str.strip(),
                        "date": pd.to_datetime(raw["Index Date"], format="%d-%m-%Y", errors="coerce"),
                        "close": pd.to_numeric(raw["Closing Index Value"], errors="coerce")})
    return out.dropna()


def _day(d: date, session=None) -> pd.DataFrame | None:
    """Parsed file for one day, from the local copy or NSE; None when NSE has no file (holiday/weekend)."""
    if d in _memo:
        return _memo[d]
    path = RAW_DIR / f"ind_close_all_{d:%Y%m%d}.csv"
    text = path.read_text(encoding="utf-8") if path.exists() else None
    if text is None:
        s = session or requests.Session()
        try:
            r = s.get(URL.format(d=d), headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"}, timeout=60)
        except requests.RequestException as e:
            raise NseError(f"NSE file for {d} could not be downloaded: {e}") from e
        if r.status_code == 404:
            _memo[d] = None
            return None
        if r.status_code != 200 or "Index Name" not in r.text[:200]:
            raise NseError(f"NSE file for {d}: HTTP {r.status_code}")
        text = r.text
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        time.sleep(PAUSE)  # be gentle with NSE when backfilling many days
    _memo[d] = parse_file(text)
    return _memo[d]


def fetch(source_series: str, since=None, session=None, today: date | None = None):
    today = today or datetime.now(IST).date()
    start = (since + timedelta(days=1)) if since else today - timedelta(days=BACKFILL_DAYS)
    rows, files = [], 0
    d = start
    while d <= today:
        if d.weekday() < 5:  # NSE does not trade at weekends
            day = _day(d, session)
            if day is not None:
                files += 1
                hit = day[day["index"].str.casefold() == source_series.casefold()]
                if hit.empty:
                    raise NseError(f"'{source_series}' not found in the NSE index file for {d}")
                rows.append((hit["date"].iloc[0], float(hit["close"].iloc[0])))
        d += timedelta(days=1)
    df = pd.DataFrame(rows, columns=["date", "value"]).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    meta = {"last_updated": str(df["date"].iloc[-1].date()) if not df.empty else None,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "files": files}
    return df, meta
