import pytest

from ingest import worldbank


class Resp:
    status_code = 200

    def __init__(self, payload):
        self._p, self.text = payload, str(payload)

    def json(self):
        return self._p


class FakeSession:
    def __init__(self, payload):
        self.payload, self.urls = payload, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.urls.append(url)
        return Resp(self.payload)


def test_parses_years_and_drops_missing():
    payload = [{"lastupdated": "2026-11-11"},
               [{"date": "2025", "value": 4.22}, {"date": "2024", "value": 4.2}, {"date": "1990", "value": None}]]
    s = FakeSession(payload)
    df, meta = worldbank.fetch("SL.UEM.TOTL.ZS:IND", session=s, save_raw=False)
    assert [d.year for d in df["date"]] == [2024, 2025] and df["value"].iloc[-1] == 4.22
    assert meta["last_updated"] == "2026-11-11"
    assert "/country/IND/indicator/SL.UEM.TOTL.ZS" in s.urls[0]


def test_api_error_message_raises():
    s = FakeSession([{"message": [{"id": "120", "value": "Invalid value"}]}])
    with pytest.raises(worldbank.WorldBankError):
        worldbank.fetch("NOPE:IND", session=s, save_raw=False)


def test_bad_source_series():
    with pytest.raises(worldbank.WorldBankError, match="ISO3"):
        worldbank.fetch("SL.UEM.TOTL.ZS")
