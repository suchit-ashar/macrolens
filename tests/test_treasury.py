from datetime import date

import pandas as pd
import pytest

from ingest import treasury

NOMINAL = ('Date,"1 Mo","2 Yr","10 Yr","30 Yr"\n'
           "11/20/2026,4.19,4.63,4.92,5.31\n11/19/2026,4.20,4.76,5.04,5.40\n")
REAL = 'Date,"5 YR","10 YR"\n11/20/2026,2.53,2.77\n'


def test_parse_sorted_by_date():
    df = treasury.parse_csv(NOMINAL, "10 Yr")
    assert list(df["date"]) == [pd.Timestamp("2026-11-19"), pd.Timestamp("2026-11-20")]
    assert df["value"].tolist() == [5.04, 4.92]


def test_column_names_case_insensitive():
    assert treasury.parse_csv(REAL, "10 yr")["value"].tolist() == [2.77]


def test_missing_column_raises():
    with pytest.raises(treasury.TreasuryError):
        treasury.parse_csv(NOMINAL, "7 Yr")


def test_implausible_value_raises():
    with pytest.raises(treasury.TreasuryError):
        treasury.parse_csv('Date,"10 Yr"\n11/20/2026,49.2\n', "10 Yr")


def test_fetch_only_years_since_last_date(monkeypatch):
    calls = []

    class Resp:
        def __init__(self, text):
            self.text = text

    def fake_get(url, session=None):
        calls.append(url)
        return Resp(NOMINAL if "2026" in url else "")

    monkeypatch.setattr(treasury, "get", fake_get)
    df, meta = treasury.fetch("nominal:2 Yr", since=date(2026, 11, 19), today=date(2026, 11, 23))
    assert len(calls) == 1 and "type=daily_treasury_yield_curve" in calls[0]
    assert df["value"].tolist() == [4.76, 4.63] and meta["last_updated"] == "2026-11-20"


def test_real_curve_url(monkeypatch):
    seen = []
    monkeypatch.setattr(treasury, "get", lambda url, session=None: (seen.append(url), type("R", (), {"text": REAL}))[1])
    treasury.fetch("real:10 YR", since=date(2026, 1, 2), today=date(2026, 11, 23))
    assert "daily_treasury_real_yield_curve" in seen[0]
