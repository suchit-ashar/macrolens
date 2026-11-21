import pytest
from ingest import fred


class FakeResponse:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.text = payload, status, str(payload)

    def json(self):
        return self._p


class FakeSession:
    def __init__(self, status=200):
        self.status = status

    def get(self, url, params=None, timeout=None):
        if self.status != 200:
            return FakeResponse({"error_message": "Bad Request"}, self.status)
        if url.endswith("/series"):
            return FakeResponse({"seriess": [{"title": "10Y", "units": "Percent",
                                              "last_updated": "2026-11-20 15:16:02-06"}]})
        return FakeResponse({"observations": [
            {"date": "2026-11-18", "value": "4.10"},
            {"date": "2026-11-19", "value": "."},      # FRED missing value
            {"date": "2026-11-20", "value": "4.15"},
        ]})


def test_parses_values_and_drops_missing():
    df, meta = fred.fetch_series("DGS10", api_key="x", session=FakeSession(), save_raw=False)
    assert list(df["value"]) == [4.10, 4.15]
    assert meta["last_updated"].startswith("2026-11-20")


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(fred.FredError, match="FRED_API_KEY"):
        fred.fetch_series("DGS10", session=FakeSession(), save_raw=False)


def test_bad_request_raises_without_long_retry():
    with pytest.raises(fred.FredError, match="HTTP 400"):
        fred.fetch_series("NOPE", api_key="x", session=FakeSession(status=400), save_raw=False)
