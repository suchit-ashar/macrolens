"""Fetch annual indicators from the World Bank API (https://api.worldbank.org/v2), no key needed.

Used for long cross-country history the slides compare (India vs China, BRICS): ILO-modelled
unemployment and participation, GNI per capita (Atlas), investment share of GDP.

source_series: "<indicator code>:<ISO3 country>", e.g. "SL.UEM.TOTL.ZS:IND".
Dates: 1 January of the year the value refers to.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ingest.http import FetchError, get

BASE = "https://api.worldbank.org/v2"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "worldbank"


class WorldBankError(FetchError):
    pass


def fetch(source_series: str, since=None, session=None, save_raw: bool = True):
    code, _, country = source_series.partition(":")
    if not code or not country:
        raise WorldBankError(f"source_series must be '<indicator>:<ISO3>', got '{source_series}'")
    body = get(f"{BASE}/country/{country}/indicator/{code}",
               {"format": "json", "per_page": "20000"}, session=session).json()
    if not isinstance(body, list) or len(body) < 2 or body[1] is None:
        message = body[0].get("message") if isinstance(body, list) and body else body
        raise WorldBankError(f"World Bank {code} {country}: {message}")
    meta_wb, rows = body[0], body[1]
    fetched_at = datetime.now(timezone.utc)
    if save_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / f"{code}_{country}_{fetched_at:%Y%m%d}.json").write_text(json.dumps(rows), encoding="utf-8")
    df = pd.DataFrame({"date": [pd.Timestamp(int(r["date"]), 1, 1) for r in rows],
                       "value": pd.to_numeric([r["value"] for r in rows], errors="coerce")})
    df = df.dropna().sort_values("date").reset_index(drop=True)
    return df, {"last_updated": meta_wb.get("lastupdated"), "fetched_at": fetched_at.isoformat(timespec="seconds")}
