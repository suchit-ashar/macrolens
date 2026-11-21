"""Fetch IMF World Economic Outlook data from the IMF SDMX 3.0 API (https://api.imf.org), no key.

The WEO mixes history and IMF projections in one series. We never mix them in storage:
  "WEO:<COUNTRY>.<INDICATOR>.A"        years before the current calendar year (actuals and
                                       the IMF's latest estimates)
  "WEO:<COUNTRY>.<INDICATOR>.A:proj"   the current year onwards (IMF projections)
Dates: 1 January of the year. For India the IMF reports fiscal years (2025 = FY 2025-26).

Indicators used: GGXWDG_NGDP general government gross debt, % of GDP;
GGXCNL_NGDP net lending/borrowing (fiscal balance), % of GDP; GGXONLB_NGDP primary balance.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ingest.http import FetchError, get

BASE = "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "imf"
ACCEPT = "application/vnd.sdmx.data+json;version=2.0.0"


class ImfError(FetchError):
    pass


def parse_sdmx(body: dict) -> pd.DataFrame:
    """Single-series SDMX-JSON 2.0 data message -> DataFrame[date, value]."""
    try:
        data = body["data"]
        series = data["dataSets"][0]["series"]
        periods = data["structures"][0]["dimensions"]["observation"][0]["values"]
    except (KeyError, IndexError) as e:
        raise ImfError(f"Unexpected IMF response layout: {e}") from e
    if len(series) != 1:
        raise ImfError(f"Expected one series, got {len(series)}")
    obs = next(iter(series.values()))["observations"]
    rows = [(periods[int(i)]["value"], v[0]) for i, v in obs.items()]
    df = pd.DataFrame(rows, columns=["year", "value"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["date"] = pd.to_datetime(df["year"].astype(str).str[:4] + "-01-01")
    return df.dropna(subset=["value"]).sort_values("date")[["date", "value"]].reset_index(drop=True)


def fetch(source_series: str, since=None, session=None, save_raw: bool = True, today=None):
    dataflow, _, rest = source_series.partition(":")
    key, _, part = rest.partition(":")
    if not dataflow or not key:
        raise ImfError(f"source_series must be 'WEO:<COUNTRY>.<INDICATOR>.A[:proj]', got '{source_series}'")
    url = f"{BASE}/{dataflow}/+/{key}"
    body = get(url, session=session, headers={"Accept": ACCEPT}).json()
    fetched_at = datetime.now(timezone.utc)
    if save_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / f"{dataflow}_{key}_{fetched_at:%Y%m%d}.json").write_text(json.dumps(body), encoding="utf-8")
    df = parse_sdmx(body)
    cutoff = pd.Timestamp((today or fetched_at.date()).year, 1, 1)
    df = df[df["date"] >= cutoff] if part == "proj" else df[df["date"] < cutoff]
    return df.reset_index(drop=True), {"last_updated": None, "fetched_at": fetched_at.isoformat(timespec="seconds")}
