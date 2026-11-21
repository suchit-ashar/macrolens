"""Fetch CPI from the MoSPI API platform (https://api.mospi.gov.in).

The 2024-base CPI (launched 2026) is served by /api/cpi/getCPIData. Without a login
token the API returns 10 records per page, so we filter tightly and page through.

source_series is the endpoint plus its query string, e.g.
  getCPIData?base_year=2024&series=Current&state_code=1&sector_code=3&division_code=0
(state 1 = All India, sector 3 = Combined, division 0 = CPI (General)).
series=Current is the live series; series=Back is MoSPI's official back series on the
same base. They are stored under separate indicator_ids and never spliced.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl

import pandas as pd

from ingest.http import FetchError, get

BASE = "https://api.mospi.gov.in/api/cpi"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "mospi"
MAX_PAGES = 200
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                      "August", "September", "October", "November", "December"], 1)}


class MospiError(FetchError):
    pass


def fetch(source_series: str, since=None, session=None, save_raw: bool = True):
    endpoint, _, query = source_series.partition("?")
    params = {**dict(parse_qsl(query)), "Format": "JSON"}
    rows, page, pages = [], 1, 1
    while page <= pages:
        body = get(f"{BASE}/{endpoint}", {**params, "page": page}, session=session).json()
        if not body.get("statusCode") or not body.get("data"):
            raise MospiError(f"MoSPI {endpoint}: {body.get('msg', 'no data')}")
        rows.extend(body["data"])
        pages = min(int((body.get("meta_data") or {}).get("totalPages", 1)), MAX_PAGES)
        page += 1

    fetched_at = datetime.now(timezone.utc)
    if save_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        tag = "_".join(f"{k}{v}" for k, v in params.items() if k != "Format")
        (RAW_DIR / f"{endpoint}_{tag}_{fetched_at:%Y%m%d}.json").write_text(json.dumps(rows), encoding="utf-8")

    # A row should be unique per month once filtered; refuse to guess if the filter was too loose.
    df = pd.DataFrame({
        "date": [pd.Timestamp(int(r["year"]), MONTHS[r["month"]], 1) for r in rows],
        "value": pd.to_numeric([r["index"] for r in rows], errors="coerce"),
    }).dropna(subset=["value"])
    if df["date"].duplicated().any():
        raise MospiError(f"Filter '{query}' matched more than one series per month; narrow it")
    df = df.sort_values("date").reset_index(drop=True)
    meta = {"last_updated": None,  # the API does not expose release dates
            "fetched_at": fetched_at.isoformat(timespec="seconds")}
    return df, meta
