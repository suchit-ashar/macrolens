"""Fetch RBI policy rates from the "Policy Rates" box on the RBI home page.

The home page only shows the current value, so each run yields one observation dated
today (IST). run_all keeps a new row only when the value changes, building an event
history from the first run onwards. The date is when we observed the rate, not the
MPC effective date; earlier history still needs to be backfilled from RBI press releases.

source_series: "homepage:<label>", e.g. "homepage:Policy Repo Rate".
"""
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path

import pandas as pd

from ingest.http import FetchError, get

HOME = "https://www.rbi.org.in/"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "rbi"
IST = timezone(timedelta(hours=5, minutes=30))


class RbiError(FetchError):
    pass


def parse_rate(html: str, label: str) -> float:
    text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).replace("\xa0", " ")
    m = re.search(re.escape(label) + r"\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*%", text)
    if not m:
        raise RbiError(f"'{label}' not found on RBI home page (layout may have changed)")
    value = float(m.group(1))
    if not 0 < value < 20:
        raise RbiError(f"'{label}' parsed as {value}%, which looks wrong")
    return value


def fetch(source_series: str, since=None, session=None, save_raw: bool = True):
    kind, _, label = source_series.partition(":")
    if kind != "homepage" or not label:
        raise RbiError(f"Unknown RBI source_series '{source_series}'")
    html = get(HOME, session=session).text
    fetched_at = datetime.now(timezone.utc)
    if save_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / f"home_{fetched_at:%Y%m%d}.html").write_text(html, encoding="utf-8")
    value = parse_rate(html, label)
    today = pd.Timestamp(fetched_at.astimezone(IST).date())
    df = pd.DataFrame({"date": [today], "value": [value]})
    return df, {"last_updated": None, "fetched_at": fetched_at.isoformat(timespec="seconds")}
