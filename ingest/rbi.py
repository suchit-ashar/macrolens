"""Fetch RBI policy rates automatically.

1. The "Policy Rates" box on the RBI home page gives the rate in force today.
2. For the repo rate, the MPC press release gives the effective date: we scan RBI's recent
   press-release list for MPC statements, read the announced rate and the release date,
   and use that date when the announced rate equals today's rate. Daily runs always see
   the release, since the list covers the last few weeks.
3. If no matching release is found, the row is dated on the day we observed the rate, and
   meta["date_basis"] says so.

run_all keeps a row only when the rate changes, so unchanged days add nothing. History
before the daily job started was loaded once from RBI's Handbook (ingest/rbi_history.py).

source_series: "homepage:<label>", e.g. "homepage:Policy Repo Rate".
"""
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path

import pandas as pd

from ingest.http import FetchError, get

HOME = "https://www.rbi.org.in/"
RELEASES = "https://rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "rbi"
IST = timezone(timedelta(hours=5, minutes=30))
MPC_TITLE = re.compile(r"Monetary Policy Statement|Resolution of the Monetary Policy Committee|"
                       r"Governor.{0,3}s Statement", re.I)
RATE_IN_RELEASE = re.compile(r"policy repo rate[^.]{0,200}?\b(?:to|at)\s+(\d+(?:\.\d+)?)\s*per\s*cent", re.I)
RELEASE_DATE = re.compile(r"Date\s*:\s*([A-Z][a-z]{2,8}\.? \d{1,2}, \d{4})")


class RbiError(FetchError):
    pass


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).replace("\xa0", " ")


def parse_rate(html: str, label: str) -> float:
    m = re.search(re.escape(label) + r"\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*%", _text(html))
    if not m:
        raise RbiError(f"'{label}' not found on RBI home page (layout may have changed)")
    value = float(m.group(1))
    if not 0 < value < 20:
        raise RbiError(f"'{label}' parsed as {value}%, which looks wrong")
    return value


def list_mpc_releases(html: str) -> list[str]:
    """Absolute URLs of MPC-related releases in the press-release list, newest first."""
    out = []
    for href, title in re.findall(r'<a[^>]+href="?([^" >]*prid=\d+)"?[^>]*>(.*?)</a>', html, re.S | re.I):
        if MPC_TITLE.search(_text(title)):
            url = href if href.startswith("http") else "https://rbi.org.in/Scripts/" + href.split("/")[-1]
            if url not in out:
                out.append(url)
    return out


def parse_mpc_release(html: str) -> tuple[pd.Timestamp, float] | None:
    """(release date, announced repo rate) from an MPC statement, or None."""
    text = _text(html)
    rate, when = RATE_IN_RELEASE.search(text), RELEASE_DATE.search(text)
    if not rate or not when:
        return None
    day = pd.to_datetime(when.group(1).replace(".", ""), format="mixed")
    return pd.Timestamp(day.date()), float(rate.group(1))


def effective_date(rate: float, session=None) -> pd.Timestamp | None:
    """Date of the most recent MPC release announcing `rate`, if one is in the recent list."""
    listing = get(RELEASES, session=session).text
    for url in list_mpc_releases(listing):
        found = parse_mpc_release(get(url, session=session).text)
        if found and abs(found[1] - rate) < 1e-9:
            return found[0]
    return None


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

    when, basis = None, "observed"
    if label == "Policy Repo Rate":
        try:
            when = effective_date(value, session=session)
        except FetchError:
            when = None  # the home-page value is still good; fall back to today's date
        if when is not None and when <= today:
            basis = "mpc_release"
    df = pd.DataFrame({"date": [when if basis == "mpc_release" else today], "value": [value]})
    return df, {"last_updated": str(df["date"].iloc[0].date()) if basis == "mpc_release" else None,
                "fetched_at": fetched_at.isoformat(timespec="seconds"), "date_basis": basis}
