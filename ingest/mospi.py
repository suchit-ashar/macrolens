"""Fetch official statistics from the MoSPI API platform (https://api.mospi.gov.in/api).

Products used (all readable without a login token, 10-20 records per page, so every query
is filtered down to a single series and paged through):
  cpi/getCPIData    CPI, 2024 base (Current = 2025 onwards, Back = official back series)
  nas/getNasData    National accounts, 2022-23 base (quarterly from FY 2022-23)
  plfs/getData      Periodic Labour Force Survey (monthly bulletin from April 2025)

source_series is "<product>/<endpoint>?<filters>[&_value=<field>]", e.g.
  cpi/getCPIData?base_year=2024&series=Current&state_code=1&sector_code=3&division_code=0&_value=inflation
A bare "getCPIData?..." means "cpi/getCPIData?...". Options starting with "_" are not sent:
  _value=<field>      field holding the number (default: index for CPI, constant_price for
                      NAS, value for PLFS)
  _top=<field>        query month by month and keep the aggregate row, where <field> is
                      empty (CPI divisions also return all their sub-groups)
  _from_year=<year>   first year for _top queries (default 2025)

Dates: monthly rows -> first day of the month; NAS quarters -> first day of the quarter of
India's fiscal year (Q1 = April); NAS annual rows -> 1 April of the fiscal year.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl

import pandas as pd

from ingest.http import FetchError, get

BASE = "https://api.mospi.gov.in/api"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "mospi"
MAX_PAGES = 200
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                      "August", "September", "October", "November", "December"], 1)}
DEFAULT_FIELD = {"cpi": "index", "nas": "constant_price", "plfs": "value"}


class MospiError(FetchError):
    pass


def parse_source(source_series: str) -> tuple[str, str, dict, str]:
    """-> (product, endpoint, query params, value field)."""
    path, _, query = source_series.partition("?")
    product, _, endpoint = path.rpartition("/")
    product = product or "cpi"
    params = dict(parse_qsl(query))
    field = params.pop("_value", DEFAULT_FIELD.get(product, "value"))
    return product, endpoint, params, field


def row_date(r: dict) -> pd.Timestamp:
    year, month, quarter = str(r.get("year") or ""), r.get("month"), r.get("quarter")
    fy = re.fullmatch(r"(\d{4})-\d{2}", year)
    if fy and quarter and re.fullmatch(r"Q[1-4]", str(quarter)):
        start = pd.Timestamp(int(fy.group(1)), 4, 1)
        return start + pd.DateOffset(months=3 * (int(str(quarter)[1]) - 1))
    if month in MONTHS and re.fullmatch(r"\d{4}", year):
        return pd.Timestamp(int(year), MONTHS[month], 1)
    if fy:
        return pd.Timestamp(int(fy.group(1)), 4, 1)
    raise MospiError(f"Cannot work out the period of row {r}")


def _all_pages(url: str, params: dict, session=None) -> list[dict]:
    rows, page, pages = [], 1, 1
    while page <= pages:
        body = get(url, {**params, "page": page}, session=session).json()
        if not body.get("statusCode") or not body.get("data"):
            raise MospiError(f"MoSPI {url.split('/api/')[-1]}: {body.get('msg', 'no data')}")
        rows.extend(body["data"])
        pages = min(int((body.get("meta_data") or {}).get("totalPages", 1)), MAX_PAGES)
        page += 1
    return rows


def _top_level_by_month(url: str, params: dict, top_field: str, first_year: int, session=None) -> list[dict]:
    """One request per month; keep the aggregate row (where `top_field`, e.g. group, is empty).

    Used for CPI divisions, whose sub-group rows would otherwise mean hundreds of pages.
    The aggregate row comes first on page 1; later pages are read only if it does not.
    """
    today = datetime.now(timezone.utc).date()
    out = []
    for year in range(first_year, today.year + 1):
        for month in range(1, 13):
            if year == today.year and month > today.month:
                break
            page, pages = 1, 1
            while page <= min(pages, MAX_PAGES):
                body = get(url, {**params, "year": year, "month_code": month, "page": page}, session=session).json()
                if not body.get("statusCode") or not body.get("data"):
                    break  # month not published
                top = [r for r in body["data"] if not r.get(top_field)]
                if top:
                    out.append(top[0])
                    break
                pages = int((body.get("meta_data") or {}).get("totalPages", 1))
                page += 1
    if not out:
        raise MospiError(f"MoSPI {url.split('/api/')[-1]}: no aggregate rows found")
    return out


def fetch(source_series: str, since=None, session=None, save_raw: bool = True):
    product, endpoint, params, field = parse_source(source_series)
    top_field, first_year = params.pop("_top", None), params.pop("_from_year", None)
    params = {**params, "Format": "JSON"}
    url = f"{BASE}/{product}/{endpoint}"
    if top_field:
        rows = _top_level_by_month(url, params, top_field, int(first_year or 2025), session)
    else:
        rows = _all_pages(url, params, session)

    fetched_at = datetime.now(timezone.utc)
    if save_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        tag = "_".join(f"{k}{v}" for k, v in params.items() if k != "Format")
        (RAW_DIR / f"{product}_{endpoint}_{tag}_{fetched_at:%Y%m%d}.json".replace(" ", "")).write_text(
            json.dumps(rows), encoding="utf-8")

    if rows and field not in rows[0]:
        raise MospiError(f"Field '{field}' not in MoSPI rows (fields: {sorted(rows[0])})")
    df = pd.DataFrame({"date": [row_date(r) for r in rows],
                       "value": pd.to_numeric([r.get(field) for r in rows], errors="coerce")})
    df = df.dropna(subset=["value"])
    # A row should be unique per period once filtered; refuse to guess if the filter was too loose.
    if df["date"].duplicated().any():
        raise MospiError(f"Filter '{source_series}' matched more than one series per period; narrow it")
    df = df.sort_values("date").reset_index(drop=True)
    meta = {"last_updated": None,  # the API does not expose release dates
            "fetched_at": fetched_at.isoformat(timespec="seconds")}
    return df, meta
