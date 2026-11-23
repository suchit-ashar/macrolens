from datetime import date

import pandas as pd
import pytest

from ingest import ecb

CSV = ("KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
       "EXR.D.INR.EUR.SP00.A,D,INR,EUR,SP00,A,2026-11-20,101.85\n"
       "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-11-20,1.0990\n"
       "EXR.D.GBP.EUR.SP00.A,D,GBP,EUR,SP00,A,2026-11-20,0.83735\n"
       "EXR.D.JPY.EUR.SP00.A,D,JPY,EUR,SP00,A,2026-11-20,174.35\n"
       "EXR.D.CNY.EUR.SP00.A,D,CNY,EUR,SP00,A,2026-11-20,7.3388\n")


@pytest.fixture(autouse=True)
def fake_ecb(monkeypatch):
    ecb._memo.clear()

    class Resp:
        text = CSV
    monkeypatch.setattr(ecb, "get", lambda url, params=None, session=None: Resp())
    yield
    ecb._memo.clear()


@pytest.mark.parametrize("series, expected", [
    ("EUR:1", 101.85),
    ("USD:1", round(101.85 / 1.0990, 4)),
    ("GBP:1", round(101.85 / 0.83735, 4)),
    ("JPY:100", round(101.85 / 174.35 * 100, 4)),
    ("CNY:1", round(101.85 / 7.3388, 4)),
    ("AED:1", round(101.85 / 1.0990 / 3.6725, 4)),
])
def test_rupee_cross_rates(series, expected):
    df, meta = ecb.fetch(series, since=date(2026, 11, 19))
    assert df["value"].iloc[-1] == pytest.approx(expected, abs=1e-4)
    assert df["date"].iloc[-1] == pd.Timestamp("2026-11-20") and meta["last_updated"] == "2026-11-20"


def test_one_download_shared_by_all_series(monkeypatch):
    calls = []

    class Resp:
        text = CSV
    monkeypatch.setattr(ecb, "get", lambda url, params=None, session=None: (calls.append(url), Resp())[1])
    ecb.fetch("USD:1", since=date(2026, 11, 19))
    ecb.fetch("GBP:1", since=date(2026, 11, 19))
    assert len(calls) == 1


def test_missing_rupee_raises():
    with pytest.raises(ecb.EcbError):
        ecb.rupees_per(pd.DataFrame({"USD": [1.1]}), "USD")
