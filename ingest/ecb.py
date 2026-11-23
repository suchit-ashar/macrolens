"""Rupee exchange rates from the European Central Bank's euro foreign exchange reference rates.

The ECB publishes, every working day (set at 2:15 pm CET), the value of one euro in about 30
currencies, including the Indian rupee. Rupee rates against other currencies are derived from
these: rupees per US dollar = (rupees per euro) / (US dollars per euro). The UAE dirham is not in
the ECB list; it is pegged at 3.6725 per US dollar, so rupees per dirham = rupees per US dollar / 3.6725.

Reuse: ECB statistics may be used free of charge provided the ECB is cited as the source
(https://www.ecb.europa.eu/home/disclaimer/html/index.en.html).
Download: the ECB Data Portal API (documented at https://data.ecb.europa.eu/help/api/overview).
source_series: "<currency>:<units>", meaning rupees per <units> <currency>, e.g. "USD:1", "JPY:100", "AED:1".
"""
import io
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from ingest.http import FetchError, get

URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{codes}.EUR.SP00.A"
CODES = ["INR", "USD", "GBP", "JPY", "CNY"]
AED_PER_USD = 3.6725  # Central Bank of the UAE peg
HISTORY_START = date(2010, 1, 1)
_memo: dict[date, pd.DataFrame] = {}


class EcbError(FetchError):
    pass


def parse_csv(text: str) -> pd.DataFrame:
    """ECB csvdata -> wide DataFrame indexed by date, one column per currency (units per euro)."""
    raw = pd.read_csv(io.StringIO(text))
    need = {"CURRENCY", "TIME_PERIOD", "OBS_VALUE"}
    if not need <= set(raw.columns):
        raise EcbError(f"ECB response has unexpected columns: {list(raw.columns)[:6]}")
    raw["TIME_PERIOD"] = pd.to_datetime(raw["TIME_PERIOD"], errors="coerce")
    raw["OBS_VALUE"] = pd.to_numeric(raw["OBS_VALUE"], errors="coerce")
    wide = raw.dropna(subset=["TIME_PERIOD", "OBS_VALUE"]).pivot_table(
        index="TIME_PERIOD", columns="CURRENCY", values="OBS_VALUE", aggfunc="last")
    return wide.sort_index()


def per_euro(start: date, session=None) -> pd.DataFrame:
    """All needed currencies per euro from `start`, downloaded once per run."""
    if start not in _memo:
        r = get(URL.format(codes="+".join(CODES)), {"format": "csvdata", "startPeriod": start.isoformat()},
                session=session)
        _memo[start] = parse_csv(r.text) if r.text.strip() else pd.DataFrame()
    return _memo[start]


def rupees_per(wide: pd.DataFrame, currency: str, units: float = 1) -> pd.Series:
    """Rupees per `units` of `currency`, derived from the per-euro rates."""
    if "INR" not in wide:
        raise EcbError("no rupee rate in the ECB data")
    inr = wide["INR"]
    if currency == "EUR":
        out = inr
    elif currency == "AED":
        out = inr / wide["USD"] / AED_PER_USD
    else:
        if currency not in wide:
            raise EcbError(f"no {currency} rate in the ECB data")
        out = inr / wide[currency]
    return (out * units).dropna()


def fetch(source_series: str, since=None, session=None):
    currency, _, units = source_series.partition(":")
    start = (since + timedelta(days=1)) if since else HISTORY_START
    wide = per_euro(start, session=session)
    if wide.empty:
        return pd.DataFrame(columns=["date", "value"]), {"last_updated": None,
                                                        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    s = rupees_per(wide, currency, float(units or 1))
    df = pd.DataFrame({"date": s.index, "value": s.round(4).values}).reset_index(drop=True)
    bad = df[(df["value"] <= 0) | (df["value"] > 100000)]
    if not bad.empty:
        raise EcbError(f"derived rupee rate {bad['value'].iloc[0]} for {currency} looks wrong")
    meta = {"last_updated": str(df["date"].iloc[-1].date()) if not df.empty else None,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return df, meta
