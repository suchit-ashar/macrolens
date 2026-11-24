from datetime import date

import pandas as pd
import pytest

from ingest import ecb

CSV = ("KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
       "EXR.D.INR.EUR.SP00.A,D,INR,EUR,SP00,A,2026-11-19,101.20\n"
       "EXR.D.INR.EUR.SP00.A,D,INR,EUR,SP00,A,2026-11-20,101.85\n")


def test_rupees_per_euro_as_published(monkeypatch):
    seen = []

    class Resp:
        text = CSV
    monkeypatch.setattr(ecb, "get", lambda url, params=None, session=None: (seen.append((url, params)), Resp())[1])
    df, meta = ecb.fetch("INR", since=date(2026, 11, 18))
    assert df["value"].tolist() == [101.20, 101.85]
    assert df["date"].iloc[-1] == pd.Timestamp("2026-11-20") and meta["last_updated"] == "2026-11-20"
    assert "EXR/D.INR.EUR.SP00.A" in seen[0][0] and seen[0][1]["startPeriod"] == "2026-11-19"


def test_unexpected_columns_raise():
    with pytest.raises(ecb.EcbError):
        ecb.parse_csv("A,B\n1,2\n")
