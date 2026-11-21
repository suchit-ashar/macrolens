"""Fetch series from FRED (Federal Reserve Bank of St. Louis).

Docs: https://fred.stlouisfed.org/docs/api/fred/
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

BASE = "https://api.stlouisfed.org/fred"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "fred"


class FredError(RuntimeError):
    pass


def _get(endpoint: str, params: dict, session=None, retries: int = 3) -> dict:
    session = session or requests.Session()
    last_err = None
    for attempt in range(retries):
        try:
            r = session.get(f"{BASE}/{endpoint}", params={**params, "file_type": "json"}, timeout=30)
            if r.status_code == 200:
                return r.json()
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code in (400, 401, 403, 404):
                break  # bad key or bad series id: retrying won't help
        except requests.RequestException as e:
            last_err = str(e)
        time.sleep(2 ** attempt)
    raise FredError(f"FRED {endpoint} failed for {params.get('series_id')}: {last_err}")


def fetch_series(series_id: str, api_key: str | None = None, session=None, save_raw: bool = True):
    """Return (DataFrame[date, value], metadata dict) for one FRED series."""
    api_key = api_key or os.getenv("FRED_API_KEY")
    if not api_key:
        raise FredError("FRED_API_KEY is not set (add it to .env or GitHub Secrets)")
    params = {"series_id": series_id, "api_key": api_key}

    meta_json = _get("series", params, session)
    obs_json = _get("series/observations", params, session)

    fetched_at = datetime.now(timezone.utc)
    if save_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        stamp = fetched_at.strftime("%Y%m%d")
        (RAW_DIR / f"{series_id}_{stamp}.json").write_text(
            json.dumps({"series": meta_json, "observations": obs_json}), encoding="utf-8")

    rows = obs_json.get("observations", [])
    df = pd.DataFrame(rows, columns=["date", "value"]) if rows else pd.DataFrame(columns=["date", "value"])
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"].replace(".", None), errors="coerce")  # FRED uses "." for missing
    df = df.dropna(subset=["value"]).reset_index(drop=True)

    info = (meta_json.get("seriess") or [{}])[0]
    meta = {
        "title": info.get("title"),
        "units": info.get("units"),
        "last_updated": info.get("last_updated"),  # when FRED last updated the series
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
    }
    return df, meta
