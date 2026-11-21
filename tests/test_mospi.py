import pytest

from ingest import mospi

QUERY = "getCPIData?base_year=2024&series=Current&state_code=1&sector_code=3&division_code=0"


class Resp:
    status_code = 200

    def __init__(self, payload):
        self._p, self.text = payload, str(payload)

    def json(self):
        return self._p


def row(year, month, index):
    return {"base_year": "2024", "series": "Current", "year": str(year), "month": month,
            "state": "All India", "sector": "Combined", "division": "CPI (General)", "index": index}


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(params)
        data = self.pages[params["page"] - 1]
        return Resp({"data": data, "msg": "Data fetched successfully", "statusCode": True,
                     "meta_data": {"page": params["page"], "totalPages": len(self.pages)}})


def test_pages_through_and_sorts():
    s = FakeSession([[row(2026, "October", "110.05"), row(2026, "September", "109.49")],
                     [row(2025, "December", "104.10")]])
    df, _ = mospi.fetch(QUERY, session=s, save_raw=False)
    assert [d.strftime("%Y-%m") for d in df["date"]] == ["2025-12", "2026-09", "2026-10"]
    assert df["value"].iloc[-1] == 110.05
    assert s.calls[0]["base_year"] == "2024" and s.calls[0]["Format"] == "JSON"
    assert [c["page"] for c in s.calls] == [1, 2]


def test_loose_filter_is_rejected():
    s = FakeSession([[row(2026, "October", "110.05"), row(2026, "October", "111.00")]])
    with pytest.raises(mospi.MospiError, match="more than one"):
        mospi.fetch(QUERY, session=s, save_raw=False)


def test_no_data_raises():
    class Empty:
        def get(self, url, params=None, headers=None, timeout=None):
            return Resp({"data": [], "msg": "No Data Found", "statusCode": True})
    with pytest.raises(mospi.MospiError, match="No Data Found"):
        mospi.fetch(QUERY, session=Empty(), save_raw=False)
