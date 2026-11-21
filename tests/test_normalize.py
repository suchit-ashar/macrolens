import pandas as pd
from transform.normalize import to_long, yoy_pct, merge_vintages, latest_vintage, COLUMNS

ENTRY = {"id": "us_cpi", "country": "US", "unit": "index", "frequency": "monthly",
         "source": "FRED", "source_url": "https://fred.stlouisfed.org/series/CPIAUCSL"}


def test_to_long_has_standard_columns():
    df = pd.DataFrame({"date": ["2026-01-01"], "value": [100.0]})
    out = to_long(df, ENTRY, release_date="2026-02-12", fetched_at="2026-02-13T00:00:00")
    assert list(out.columns) == COLUMNS and out.loc[0, "country"] == "US"


def test_yoy_pct():
    df = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=13, freq="MS"),
                       "value": [100.0] * 12 + [103.0]})
    assert round(yoy_pct(df).iloc[-1]["value"], 2) == 3.00


def _long(dates, values, fetched_at, entry=ENTRY):
    return to_long(pd.DataFrame({"date": dates, "value": values}), entry, fetched_at=fetched_at)


def test_merge_appends_new_dates_and_revisions_only():
    old = _long(["2026-01-01", "2026-02-01"], [100.0, 101.0], "2026-03-01T00:00:00")
    new = _long(["2026-01-01", "2026-02-01", "2026-03-01"], [100.0, 101.5, 102.0], "2026-04-01T00:00:00")
    merged = merge_vintages(old, new)
    assert len(merged) == 4  # Jan unchanged, Feb revised (2 vintages), Mar new
    feb = merged[merged["date"] == "2026-02-01"]
    assert list(feb["value"]) == [101.0, 101.5]
    assert list(latest_vintage(merged)["value"]) == [100.0, 101.5, 102.0]


def test_merge_unchanged_is_noop():
    old = _long(["2026-01-01"], [100.0], "2026-03-01T00:00:00")
    new = _long(["2026-01-01"], [100.0], "2026-04-01T00:00:00")
    assert merge_vintages(old, new).equals(old)


def test_merge_event_keeps_changes_only():
    entry = {**ENTRY, "id": "in_repo_rate", "frequency": "event"}
    old = _long(["2026-11-20"], [5.50], "2026-11-20T01:00:00", entry)
    same = _long(["2026-11-21"], [5.50], "2026-11-21T01:00:00", entry)
    assert len(merge_vintages(old, same, event=True)) == 1
    cut = _long(["2026-12-06"], [5.25], "2026-12-06T01:00:00", entry)
    assert list(merge_vintages(old, cut, event=True)["value"]) == [5.50, 5.25]
