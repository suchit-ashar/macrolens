"""Daily gold and silver rates from IBJA (India Bullion and Jewellers Association).

IBJA publishes AM (opening) and PM (closing) rates every working day; RBI uses IBJA closing
rates to price Sovereign Gold Bonds. The home page has a table of the last few days for each
session, and its chart carries about four months of PM rates for gold 999 and 916 (a hidden
JSON field). Both are read; on dates in both, the table wins. A missed day is filled on the
next run. No rates are published on weekends and central-government holidays.

Units: gold in rupees per 10 grams, silver in rupees per kilogram.
source_series: "<session>:<column>", e.g. "pm:Gold 999" or "pm:Silver 999".
"""
import json
import re
from datetime import datetime, timezone
from html import unescape

import pandas as pd

from ingest.http import FetchError, get

URL = "https://ibjarates.com/"
SANE = {"Gold": (10_000, 2_000_000), "Silver": (10_000, 2_000_000)}  # rupees per 10 g / per kg
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_DATE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


class IbjaError(FetchError):
    pass


def _session_block(html: str, session: str) -> str:
    start = html.find(f'id="tab-{session}"')
    if start < 0:
        raise IbjaError(f"IBJA '{session.upper()}' rate table not found (page layout may have changed)")
    nxt = html.find('id="tab-', start + 10)
    return html[start: nxt if nxt > 0 else len(html)]


CHART = {"Gold 999": ("HdnGold", "purity999"), "Gold 916": ("HdnGold", "purity916")}  # PM rates only


def _day(m: re.Match) -> pd.Timestamp:
    return pd.Timestamp(int(m.group(3)), int(m.group(2)), int(m.group(1)))


def _chart_rows(html: str, column: str) -> list[tuple]:
    """(date, value) pairs from the chart's hidden JSON field, or [] if absent."""
    field, key = CHART.get(column, (None, None))
    if not field:
        return []
    m = (re.search(r'id="' + field + r'"[^>]*value="([^"]*)"', html)
         or re.search(r'value="([^"]*)"[^>]*id="' + field + '"', html))
    if not m:
        return []
    try:
        data = json.loads(unescape(m.group(1)))
        pairs = zip(data["labels"], data[key])
    except (ValueError, KeyError, TypeError):
        return []
    return [(_day(d), float(v)) for lab, v in pairs if v is not None and (d := _DATE.fullmatch(str(lab).strip()))]


def parse_rates(html: str, session: str, column: str) -> pd.DataFrame:
    """AM or PM rates as DataFrame[date, value] for one column (e.g. 'Gold 999'): the history table,
    plus the chart's longer PM history where IBJA provides it."""
    cell = re.compile(r'data-label="' + re.escape(column) + r'"[^>]*>\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*<', re.I)
    rows = []
    for row in _ROW.findall(_session_block(html, session.lower())):
        d, v = _DATE.search(row), cell.search(row)
        if d and v:
            rows.append((_day(d), float(v.group(1).replace(",", ""))))
    if not rows:
        raise IbjaError(f"no '{column}' rates in the IBJA {session.upper()} table")
    chart = _chart_rows(html, column) if session.lower() == "pm" else []
    # table rows last so they win on duplicate dates
    df = (pd.DataFrame(chart + rows, columns=["date", "value"]).drop_duplicates("date", keep="last")
          .sort_values("date").reset_index(drop=True))
    lo, hi = SANE.get(column.split()[0], (0, float("inf")))
    bad = df[(df["value"] < lo) | (df["value"] > hi)]
    if not bad.empty:
        raise IbjaError(f"IBJA {column} value {bad['value'].iloc[0]:,.0f} on {bad['date'].iloc[0].date()} looks wrong")
    return df


def fetch(source_series: str, since=None, session=None):
    sess, column = source_series.split(":", 1)
    fetched_at = datetime.now(timezone.utc)
    df = parse_rates(get(URL, session=session).text, sess, column)
    return df, {"last_updated": str(df["date"].iloc[-1].date()), "fetched_at": fetched_at.isoformat(timespec="seconds")}
