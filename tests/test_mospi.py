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


def test_nas_quarters_map_to_indian_fiscal_year():
    nas = [{"year": "2025-26", "quarter": "Q1", "constant_price": "7546230", "current_price": "8000192"},
           {"year": "2025-26", "quarter": "Q4", "constant_price": "8800000", "current_price": "9500000"},
           {"year": "2026-27", "quarter": "Q1", "constant_price": "8136153", "current_price": "8826871"}]
    df, _ = mospi.fetch("nas/getNasData?indicator_code=5&_value=current_price",
                        session=FakeSession([nas]), save_raw=False)
    assert [d.strftime("%Y-%m-%d") for d in df["date"]] == ["2025-04-01", "2026-01-01", "2026-04-01"]
    assert df["value"].iloc[-1] == 8826871


def test_option_params_are_not_sent_and_value_field_is_used():
    s = FakeSession([[{**row(2026, "October", "110.05"), "inflation": "6.09"}]])
    df, _ = mospi.fetch(QUERY + "&_value=inflation", session=s, save_raw=False)
    assert df["value"].iloc[0] == 6.09 and "_value" not in s.calls[0]


def test_plfs_monthly_rows():
    plfs = [{"year": "2026", "month": "October", "value": "4.9"}, {"year": "2025", "month": "April", "value": "5.1"}]
    df, _ = mospi.fetch("plfs/getData?indicator_code=3", session=FakeSession([plfs]), save_raw=False)
    assert [d.strftime("%Y-%m") for d in df["date"]] == ["2025-04", "2026-10"]


def test_top_level_row_picked_per_month(monkeypatch):
    class MonthSession:
        def __init__(self):
            self.calls = []

        def get(self, url, params=None, headers=None, timeout=None):
            self.calls.append(params)
            if (params["year"], params["month_code"]) != (2026, 1):
                return Resp({"data": [], "msg": "No Data Found", "statusCode": True})
            return Resp({"statusCode": True, "meta_data": {"totalPages": 22}, "data": [
                {"year": "2026", "month": "January", "group": None, "inflation": "2.11"},
                {"year": "2026", "month": "January", "group": "Food", "inflation": "2.50"}]})

    s = MonthSession()
    df, _ = mospi.fetch("cpi/getCPIData?division_code=1&_value=inflation&_top=group&_from_year=2026",
                        session=s, save_raw=False)
    assert list(df["value"]) == [2.11]
    assert all(c["page"] == 1 for c in s.calls)
