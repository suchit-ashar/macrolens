from datetime import date

import numpy as np
import pandas as pd

from transform.checks import run_checks
from transform.normalize import to_long

TODAY = date(2026, 11, 21)
DAILY = {"id": "x", "country": "IN", "unit": "percent", "frequency": "daily",
         "source": "T", "source_url": "https://example.org"}


def series(dates, values, entry=DAILY):
    return to_long(pd.DataFrame({"date": dates, "value": values}), entry, fetched_at="2026-11-21T00:00:00")


def business_days(end="2026-11-20", n=300, seed=0):
    d = pd.bdate_range(end=end, periods=n)
    rng = np.random.default_rng(seed)
    return d, 7 + np.cumsum(rng.normal(0, 0.02, n))


def checks(df, entry=DAILY):
    return {(i.check, i.severity) for i in run_checks(df, entry, TODAY)}


def test_clean_daily_series_passes():
    d, v = business_days()
    assert run_checks(series(d, v), DAILY, TODAY) == []


def test_recent_gap_warns_old_gap_ignored():
    d, v = business_days()
    keep = (d < "2026-10-01") | (d > "2026-10-20")
    assert ("gaps", "warn") in checks(series(d[keep], v[keep]))
    d, v = business_days(n=1000)
    keep = (d < "2023-03-01") | (d > "2023-03-25")  # more than 2 years ago
    assert ("gaps", "warn") not in checks(series(d[keep], v[keep]))


def test_known_gap_is_skipped():
    entry = {**DAILY, "frequency": "monthly", "unit": "index", "known_gaps": ["2025-11-01"]}
    d = [x for x in pd.date_range("2025-01-01", "2026-10-01", freq="MS") if x != pd.Timestamp("2025-10-01")]
    assert run_checks(series(d, np.linspace(100, 110, len(d)), entry), entry, TODAY) == []


def test_recent_jump_warns():
    d, v = business_days()
    v[-3] += 1.5  # a 150 bp one-day move in a calm series
    assert ("jumps", "warn") in checks(series(d, v))


def test_stale_warns_then_errors():
    d, v = business_days(end="2026-10-30")
    assert ("stale", "warn") in checks(series(d, v))
    d, v = business_days(end="2026-09-01")
    assert ("stale", "error") in checks(series(d, v))


def test_closed_series_not_stale():
    entry = {**DAILY, "expect_updates": False}
    d, v = business_days(end="2020-01-31")
    assert ("stale", "warn") not in checks(series(d, v, entry), entry)


def test_structure_errors():
    d, v = business_days()
    v[5] = np.nan
    assert ("structure", "error") in checks(series(d, v))
    assert ("structure", "error") in checks(series(["2027-01-04"], [7.0]))
    assert run_checks(series([], []), DAILY, TODAY)[0].message == "no observations stored"


def test_latest_vintage_is_checked():
    d, v = business_days()
    old = series(d, v)
    revised = old.tail(1).assign(value=np.nan, fetched_at="2026-11-22T00:00:00")
    assert ("structure", "error") in checks(pd.concat([old, revised]))
