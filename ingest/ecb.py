"""Rupees per euro, as published by the European Central Bank (euro foreign exchange reference rates).

The ECB publishes, every working day (rates set at 2:15 pm CET), the value of one euro in about 30
currencies, including the Indian rupee. MacroLens shows only rates a source publishes directly, so
this fetcher returns the ECB's own INR per EUR rate and nothing derived from it.

Reuse: ECB statistics may be used free of charge provided the ECB is cited as the source and the data
is not modified (https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/usage_policy.en.html).
Download: the ECB Data Portal API (https://data.ecb.europa.eu/help/api/overview).
source_series: the currency quoted per euro, e.g. "INR" (rupees per 1 euro).
"""
import io
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from ingest.http import FetchError, get

URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{code}.EUR.SP00.A"
HISTORY_START = date(2010, 1, 1)


class EcbError(FetchError):
    pass


def parse_csv(text: str) -> pd.DataFrame:
    """ECB csvdata for one series -> DataFrame[date, value]."""
    raw = pd.read_csv(io.StringIO(text))
    if not {"TIME_PERIOD", "OBS_VALUE"} <= set(raw.columns):
        raise EcbError(f"ECB response has unexpected columns: {list(raw.columns)[:6]}")
    df = pd.DataFrame({"date": pd.to_datetime(raw["TIME_PERIOD"], errors="coerce"),
                       "value": pd.to_numeric(raw["OBS_VALUE"], errors="coerce")})
    return df.dropna().drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def fetch(source_series: str, since=None, session=None):
    code = source_series.strip().upper()
    start = (since + timedelta(days=1)) if since else HISTORY_START
    r = get(URL.format(code=code), {"format": "csvdata", "startPeriod": start.isoformat()}, session=session)
    df = parse_csv(r.text) if r.text.strip() else pd.DataFrame(columns=["date", "value"])
    if not df.empty and ((df["value"] <= 0) | (df["value"] > 100000)).any():
        raise EcbError(f"ECB {code} per EUR value looks wrong")
    meta = {"last_updated": str(df["date"].iloc[-1].date()) if not df.empty else None,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return df, meta
