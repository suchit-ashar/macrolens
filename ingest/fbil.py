"""Fetch benchmarks from FBIL (Financial Benchmarks India Ltd).

FBIL's website is an Angular app backed by a public JSON API at /wasdm. Public
(non-subscriber) access currently lags by about a week.

source_series formats (config/indicators.yaml):
  refrates:<subProdName>   e.g. "refrates:INR / 1 USD"  daily reference rate, history from July 2018
  gsec_par:<tenor years>   e.g. "gsec_par:10"           par yield from the daily G-sec valuation
                                                        workbook ("Par Yield" sheet, semi-annual YTM)
  <endpoint>[:<tenor>]     e.g. "tbill:91 Days", "ovnmibor", "mror", "cd:3 Months"
                           money-market benchmarks (T-bill, CD, MIBOR, market repo, SORR)
"""
import io
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import openpyxl
import pandas as pd

from ingest.http import FetchError, get

BASE = "https://www.fbil.org.in/wasdm"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "fbil"
REFRATES_START = date(2018, 7, 1)   # FBIL took over the USD/INR reference rate in July 2018
GSEC_BACKFILL_START = date(2025, 1, 1)  # first run downloads one workbook per business day from here
PAUSE = 0.3  # seconds between workbook downloads, to be polite


class FbilError(FetchError):
    pass


def _year_chunks(start: date, end: date):
    while start <= end:
        stop = min(date(start.year, 12, 31), end)
        yield start, stop
        start = stop + timedelta(days=1)


def _now():
    return datetime.now(timezone.utc)


def fetch_refrates(sub_prod: str, start: date = REFRATES_START, end: date | None = None,
                   session=None, save_raw: bool = True, with_rbi_latest: bool = False):
    """Daily FBIL reference rate for one currency pair, e.g. 'INR / 1 USD'."""
    end = end or date.today()
    rows = []
    for a, b in _year_chunks(start, end):
        r = get(f"{BASE}/refrates/fetchfiltered", {"fromDate": a.isoformat(), "toDate": b.isoformat(),
                                                   "authenticated": "false"}, session=session)
        rows.extend(r.json())
    fetched_at = _now()
    if save_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / f"refrates_{fetched_at:%Y%m%d}.json").write_text(json.dumps(rows), encoding="utf-8")

    picked = [x for x in rows if x.get("subProdName") == sub_prod]
    if not picked:
        raise FbilError(f"No FBIL reference rates found for '{sub_prod}'")
    df = pd.DataFrame({"date": pd.to_datetime([x["processRunDate"][:10] for x in picked]),
                       "value": pd.to_numeric([x["rate"] for x in picked], errors="coerce")})
    df = df.dropna().drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    meta = {"last_updated": max(x["displayTime"] for x in picked),
            "fetched_at": fetched_at.isoformat(timespec="seconds")}
    if with_rbi_latest:
        # FBIL's public feed lags about a week; the RBI home page shows the same FBIL rate the
        # next day. Add that day if it is newer than the feed.
        from ingest import rbi
        latest = rbi.homepage_fx(session=session)
        if latest and sub_prod in latest[1] and (df.empty or latest[0] > df["date"].max()):
            df = pd.concat([df, pd.DataFrame({"date": [latest[0]], "value": [latest[1][sub_prod]]})],
                           ignore_index=True)
            meta["last_updated"] = f"{latest[0].date()} (via RBI home page)"
    return df, meta


RATE_ENDPOINTS = {"tbill", "cd", "ovnmibor", "termmibor", "mror", "sorr"}


def fetch_rates(endpoint: str, tenor: str | None, start: date = REFRATES_START, end: date | None = None,
                session=None, save_raw: bool = True):
    """Daily FBIL money-market benchmark, e.g. ('tbill', '91 Days') or ('ovnmibor', None).

    tbill/cd/termmibor publish several tenors per day (field tenorName or tenor); pick one.
    ovnmibor/mror/sorr publish one overnight rate per day; over weekends and holidays its
    tenor reads 3D etc., so no tenor filter is applied.
    """
    end = end or date.today()
    rows = []
    for a, b in _year_chunks(start, end):
        r = get(f"{BASE}/{endpoint}/fetchfiltered", {"fromDate": a.isoformat(), "toDate": b.isoformat(),
                                                     "authenticated": "false"}, session=session)
        rows.extend(r.json())
    fetched_at = _now()
    if save_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / f"{endpoint}_{fetched_at:%Y%m%d}.json").write_text(json.dumps(rows), encoding="utf-8")
    if tenor:
        picked = [x for x in rows if str(x.get("tenorName") or x.get("tenor") or "").strip().lower() == tenor.lower()]
    else:
        picked = rows
    if not picked:
        names = sorted({str(x.get("tenorName") or x.get("tenor")) for x in rows})
        raise FbilError(f"No FBIL {endpoint} rates for tenor '{tenor}' (tenors seen: {names})")
    df = pd.DataFrame({"date": pd.to_datetime([x["processRunDate"][:10] for x in picked]),
                       "value": pd.to_numeric([x["rate"] for x in picked], errors="coerce")})
    df = df.dropna().drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    meta = {"last_updated": max(x.get("displayTime") or x["processRunDate"] for x in picked),
            "fetched_at": fetched_at.isoformat(timespec="seconds")}
    return df, meta


def parse_par_yield(xlsx_bytes: bytes, tenor: float) -> tuple[date, float]:
    """Return (valuation date, semi-annual par yield %) for one tenor from a G-sec workbook."""
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    if "Par Yield" not in wb.sheetnames:
        raise FbilError(f"'Par Yield' sheet missing (sheets: {wb.sheetnames})")
    as_of, header_seen = None, False
    for row in wb["Par Yield"].iter_rows(values_only=True):
        cells = [c for c in row if c is not None]
        if not cells:
            continue
        if as_of is None and len(cells) >= 2 and "Par Yield" in str(cells[0]):
            as_of = cells[1] if isinstance(cells[1], datetime) else datetime.strptime(str(cells[1]).strip(), "%d-%b-%Y")
        elif str(cells[0]).startswith("Tenor"):
            header_seen = True
        elif header_seen and isinstance(cells[0], (int, float)) and abs(cells[0] - tenor) < 1e-9:
            return as_of.date(), float(cells[1])
    raise FbilError(f"Tenor {tenor}y not found in Par Yield sheet")


def list_gsec_dates(start: date, end: date, session=None) -> list[date]:
    out = []
    for a, b in _year_chunks(start, end):
        r = get(f"{BASE}/gsec/fetchfiltered", {"fromDate": a.isoformat(), "toDate": b.isoformat(),
                                               "authenticated": "false"}, session=session)
        out.extend(date.fromisoformat(x["processRunDate"][:10]) for x in r.json())
    return sorted(set(out))


def fetch_gsec_par(tenor: float, since: date | None = None, end: date | None = None,
                   session=None, save_raw: bool = True):
    """Par yield for one tenor, one value per published valuation date after `since`."""
    end = end or date.today()
    start = (since + timedelta(days=1)) if since else GSEC_BACKFILL_START
    rows, fetched_at = [], _now()
    for d in list_gsec_dates(start, end, session):
        raw_path = RAW_DIR / "gsec" / f"gsec_{d:%Y%m%d}.xlsx"
        if raw_path.exists():
            content = raw_path.read_bytes()
        else:
            content = get(f"{BASE}/gsec/downloadPublished", {"date": d.isoformat()}, session=session).content
            if save_raw:
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(content)
            time.sleep(PAUSE)
        as_of, value = parse_par_yield(content, tenor)
        if as_of != d:
            raise FbilError(f"Workbook for {d} is dated {as_of}")
        rows.append((pd.Timestamp(d), value))
    df = pd.DataFrame(rows, columns=["date", "value"])
    meta = {"last_updated": str(df["date"].max().date()) if not df.empty else None,
            "fetched_at": fetched_at.isoformat(timespec="seconds")}
    return df, meta


def fetch(source_series: str, since: date | None = None, session=None):
    kind, _, arg = source_series.partition(":")
    if kind == "refrates":
        return fetch_refrates(arg, session=session, with_rbi_latest=True)
    if kind == "gsec_par":
        return fetch_gsec_par(float(arg), since=since, session=session)
    if kind in RATE_ENDPOINTS:
        return fetch_rates(kind, arg or None, session=session)
    raise FbilError(f"Unknown FBIL source_series '{source_series}'")
