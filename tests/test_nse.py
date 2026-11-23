from datetime import date

import pandas as pd
import pytest

from ingest import nse

FILE = ("Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,"
        "Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield\n"
        "Nifty 50,20-11-2026,25368,25808.8,25345.2,25800.6,286.3,1.12,428344270,42565.93,21.02,3.17,1.32\n"
        "India VIX,20-11-2026,16.11,17.5625,15.03,17.32,1.21,7.51,-,-,-,-,-\n")


class Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(nse, "RAW_DIR", tmp_path)
    monkeypatch.setattr(nse, "PAUSE", 0)
    nse._memo.clear()
    yield
    nse._memo.clear()


def test_parse_file():
    df = nse.parse_file(FILE)
    assert df.set_index("index").loc["Nifty 50", "close"] == 25800.6
    assert df["date"].iloc[0] == pd.Timestamp("2026-11-20")


def test_fetch_skips_weekends_and_holidays(tmp_path):
    asked = []

    class Session:
        def get(self, url, headers=None, timeout=None):
            asked.append(url)
            return Resp(200, FILE) if "20112026" in url else Resp(404)

    df, meta = nse.fetch("Nifty 50", since=date(2026, 11, 19), session=Session(), today=date(2026, 11, 23))
    assert len(asked) == 2  # Fri 20 (file) and Mon 23 (not yet published); Sat/Sun never asked
    assert df["value"].tolist() == [25800.6] and meta["last_updated"] == "2026-11-20"
    assert (tmp_path / "ind_close_all_20261120.csv").exists()


def test_cached_file_not_downloaded_again(tmp_path):
    (tmp_path / "ind_close_all_20261120.csv").write_text(FILE, encoding="utf-8")

    class NoNet:
        def get(self, *a, **k):
            return Resp(404)

    df, _ = nse.fetch("india vix", since=date(2026, 11, 19), session=NoNet(), today=date(2026, 11, 20))
    assert df["value"].tolist() == [17.32]


def test_unknown_index_raises():
    class Session:
        def get(self, url, headers=None, timeout=None):
            return Resp(200, FILE)

    with pytest.raises(nse.NseError):
        nse.fetch("Nifty Unicorns", since=date(2026, 11, 19), session=Session(), today=date(2026, 11, 20))


def test_blocked_response_raises():
    class Session:
        def get(self, url, headers=None, timeout=None):
            return Resp(403, "Access denied")

    with pytest.raises(nse.NseError):
        nse.fetch("Nifty 50", since=date(2026, 11, 19), session=Session(), today=date(2026, 11, 20))
