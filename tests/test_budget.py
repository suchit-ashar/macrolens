import io
from datetime import date
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from ingest import budget

FIX = Path(__file__).parent / "fixtures" / "budget"
CURRENT_XLSX = (FIX / "budget_at_a_glance_2026-27.xlsx").read_bytes()   # real file, Budget 2026-27
XLS_2021 = (FIX / "bag1_budget2021-22.xls").read_bytes()               # real .xls, Budget 2021-22
CGA_SEP = (FIX / "cga_2026-09.html").read_text(encoding="utf-8")        # trimmed real page
CGA_MAR = (FIX / "cga_2024-03.html").read_text(encoding="utf-8")        # trimmed, March provisional
CGA_NONE = (FIX / "cga_unpublished.html").read_text(encoding="utf-8")
LAST_MOD = "Wed, 25 Feb 2026 05:53:23 GMT"
ARCHIVE_URL = "https://www.indiabudget.gov.in/budget2021-22/doc/Budget_at_Glance/bag1.xls"


class Resp:
    def __init__(self, content=b"", status=200, headers=None):
        self.status_code, self.headers = status, headers or {}
        self.content = content if isinstance(content, bytes) else content.encode("utf-8")
        self.text = content if isinstance(content, str) else content.decode("latin-1")


class FakeSession:
    def __init__(self, routes, head_headers=None):
        self.routes, self.head_headers, self.urls = routes, head_headers, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.urls.append(url)
        return self.routes.get(url) or Resp("not found", status=404)

    def head(self, url, headers=None, timeout=None, allow_redirects=True):
        if self.head_headers is None:
            raise AttributeError("no HEAD")
        return Resp(b"", headers=self.head_headers)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "RAW_DIR", tmp_path / "budget")
    monkeypatch.setattr(budget, "_today", lambda: date(2026, 11, 21))
    budget._MEMO.clear()
    yield
    budget._MEMO.clear()


def workbook(rows) -> bytes:
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def budget_routes(archive=True):
    routes = {budget.BAAG_URL: Resp(CURRENT_XLSX, headers={"Last-Modified": LAST_MOD})}
    if archive:
        routes[ARCHIVE_URL] = Resp(XLS_2021)
    return routes


# ------------------------------ Budget at a Glance parsing ------------------------------

def test_parse_current_workbook():
    p = budget.parse_glance(CURRENT_XLSX)
    assert p["fiscal_deficit"]["2024|actual"] == [1574431, 4.8]
    assert p["fiscal_deficit"]["2025|BE"] == [1568936, 4.4]
    assert p["fiscal_deficit"]["2025|RE"] == [1558492, 4.4]
    assert p["fiscal_deficit"]["2026|BE"] == [1695768, 4.3]
    assert p["revenue_deficit"]["2024|actual"] == [564296, 1.7]
    assert p["primary_deficit"]["2026|BE"] == [291796, 0.7]
    assert p["capital_expenditure"]["2024|actual"][0] == 1051953
    assert p["interest_payments"]["2025|RE"][0] == 1274338
    assert p["gross_tax_revenue"]["2026|BE"][0] == 4404086   # from the "Receipts" sheet


def test_read_real_xls_file():
    p = budget.parse_glance(XLS_2021)          # Excel 97-2003 file, read without xlrd
    assert p["fiscal_deficit"]["2019|actual"] == [933651, 4.6]
    assert p["fiscal_deficit"]["2020|RE"] == [1848655, 9.5]
    assert p["primary_deficit"]["2021|BE"] == [697111, 3.1]
    assert p["capital_expenditure"]["2019|actual"][0] == 335726


def test_value_and_gdp_share_in_one_cell():
    content = workbook([
        [None, "Budget at a Glance"],
        [None, "", "", "2023-2024\n Actuals", "2024-2025\nBudget \nEstimates", "2024-2025\nRevised \nEstimates",
         "2025-2026\nBudget \nEstimates"],
        [None, "x", " 17. Fiscal Deficit \n [9-(1+5+6)]", "1654644\n(5.6)", "1613312\n(4.9)", "1569527\n(4.8)",
         "1568936\n(4.4)"],
        [None, "x", " 16. Effective Revenue Deficit", "461301\n(1.6)", "1\n(0.6)", "1\n(1.0)", "1\n(0.3)"],
        [None, "x", " 15. Revenue Deficit (10-1)", "765216\n(2.6)", "580201\n(1.8)", "610098\n(1.9)", "523846\n(1.5)"],
    ])
    p = budget.parse_glance(content)
    assert p["fiscal_deficit"]["2023|actual"] == [1654644, 5.6]
    assert p["revenue_deficit"]["2025|BE"] == [523846, 1.5]      # not the effective revenue deficit


def test_gdp_row_stored_as_negative_numbers_and_header_typo():
    # Budget 2018-19 stores "(3.5)" as -3.5 with a bracket number format; Budget 2017-18 labels
    # its Actuals column "2016-2016" (meaning 2015-16).
    content = workbook([
        [None, None, "2016-2016", "2016-2017", "2016-2017", "2017-2018"],
        [None, None, "Actuals", "Budget", "Revised", "Budget"],
        [None, None, None, "Estimates", "Estimates", "Estimates"],
        ["9. Scheme Expenditure", None, 1, 1, 1, 1],
        [None, "11. On Capital Account", 179495, 200066, 238336, 271021],
        [None, "15. On Capital Account", 73527, 46957, 41511, 38780],
        [None, "19. On Capital Account", 253022, 247023, 279847, 309801],
        ["22. Fiscal Deficit [16-(1+5+6)]", None, 532791, 533904, 534274, 546532],
        [None, None, -3.9, -3.5, -3.2, -3.2],
        ["23. Primary Deficit (22-14)", None, -100, 41234, 51205, 23454],
        [None, None, -0.1, -0.3, -0.3, -0.1],
    ])
    p = budget.parse_glance(content)
    assert p["fiscal_deficit"]["2015|actual"] == [532791, 3.9]
    assert p["fiscal_deficit"]["2016|RE"] == [534274, 3.2]
    assert p["primary_deficit"]["2015|actual"] == [-100, -0.1]   # a surplus keeps its sign
    assert p["capital_expenditure"]["2015|actual"][0] == 253022  # the total row, not a part


def test_combine_actual_from_newest_and_estimate_re_else_be():
    older = {"fiscal_deficit": {"2019|actual": [10, 1.0], "2020|BE": [20, 2.0], "2020|RE": [21, 2.1],
                                "2021|BE": [30, 3.0]}}
    newer = {"fiscal_deficit": {"2020|actual": [22, 2.2], "2021|BE": [30, 3.0], "2021|RE": [31, 3.1],
                                "2022|BE": [40, 4.0]}}
    assert budget.combine_glance([older, newer], "fiscal_deficit", "actual", False) == {2019: 10, 2020: 22}
    assert budget.combine_glance([older, newer], "fiscal_deficit", "estimate", False) == \
        {2020: 21, 2021: 31, 2022: 40}
    assert budget.combine_glance([older, newer], "fiscal_deficit", "estimate", True)[2022] == 4.0


def test_fetch_budget_series(monkeypatch):
    monkeypatch.setattr(budget, "ARCHIVE", {"2021-22": ARCHIVE_URL})
    s = FakeSession(budget_routes())
    df, meta = budget.fetch("baag:fiscal_deficit:actual", session=s, save_raw=False)
    assert list(df["date"]) == [pd.Timestamp("2019-04-01"), pd.Timestamp("2024-04-01")]
    assert list(df["value"]) == [933651.0, 1574431.0] and df["value"].dtype == float
    assert meta["last_updated"] == "2026-02-25" and meta["fetched_at"]

    est, _ = budget.fetch("baag:fiscal_deficit_gdp:estimate", session=s, save_raw=False)
    assert dict(zip(est["date"].dt.year, est["value"])) == {2020: 9.5, 2021: 6.8, 2025: 4.4, 2026: 4.3}
    assert len(s.urls) == 2          # second series reused the downloads of the first


def test_budget_cache_skips_unchanged_files(monkeypatch):
    monkeypatch.setattr(budget, "ARCHIVE", {"2021-22": ARCHIVE_URL})
    budget.fetch("baag:revenue_deficit:actual", session=FakeSession(budget_routes()))
    files = {p.name for p in (budget.RAW_DIR / "baag").rglob("*")}
    assert {"budget_at_a_glance_20260225.xlsx", "budget2021-22_bag1.xls", "budget2021-22_bag1.json"} <= files

    budget._MEMO.clear()
    s = FakeSession(budget_routes(), head_headers={"Last-Modified": LAST_MOD, "Content-Length": str(len(CURRENT_XLSX))})
    df, meta = budget.fetch("baag:revenue_deficit:actual", session=s)
    assert s.urls == [] and df["value"].iloc[-1] == 564296 and meta["last_updated"] == "2026-02-25"

    budget._MEMO.clear()   # a new Last-Modified means a new budget file: download it again
    s = FakeSession(budget_routes(), head_headers={"Last-Modified": "Sun, 01 Feb 2027 06:00:00 GMT",
                                                    "Content-Length": "1"})
    budget.fetch("baag:revenue_deficit:actual", session=s)
    assert s.urls == [budget.BAAG_URL]


def test_archive_outage_is_reported_not_fatal(monkeypatch):
    monkeypatch.setattr(budget, "ARCHIVE", {"2021-22": ARCHIVE_URL})
    df, meta = budget.fetch("baag:primary_deficit:estimate", session=FakeSession(budget_routes(archive=False)),
                            save_raw=False)
    assert df["value"].iloc[-1] == 291796 and "2021-22" in meta["missing_archives"][0]


# ------------------------------ CGA monthly accounts ------------------------------

def test_parse_cga_month():
    rec = budget.parse_cga(CGA_SEP)
    assert rec["basis"] == "BE" and rec["fy"] == "2026-2027" and rec["month"] == (2026, 9)
    rows = rec["rows"]
    assert rows["fiscal_deficit"] == {"estimate": 1695768, "actual": 714413, "pct": 42.1, "pct_coppy": 36.5}
    assert rows["revenue_receipts"]["actual"] == 1756820          # printed as "1 756820"
    assert rows["primary_deficit"]["pct_coppy"] == -1.7
    assert rows["total_receipts"]["actual"] == 1835422 and rows["total_expenditure"]["actual"] == 2549835
    assert rows["capital_expenditure"]["actual"] == 654547 and rows["interest_payments"]["actual"] == 646010


def test_parse_cga_march_provisional_against_revised_estimates():
    rec = budget.parse_cga(CGA_MAR)
    assert rec["basis"] == "RE" and rec["month"] == (2024, 3)
    assert rec["rows"]["fiscal_deficit"]["actual"] == 1653670 and rec["rows"]["fiscal_deficit"]["pct"] == 95.3


def test_parse_cga_unpublished_month():
    assert budget.parse_cga(CGA_NONE) is None


def cga_routes():
    aug = CGA_SEP.replace("September 2026", "August 2026").replace("714413", "710249")
    url = budget.CGA_URL.format
    return {url(month=8, fy="2026-2027"): Resp(aug), url(month=9, fy="2026-2027"): Resp(CGA_SEP),
            url(month=10, fy="2026-2027"): Resp(CGA_NONE), url(month=11, fy="2026-2027"): Resp(CGA_NONE)}


def test_fetch_cga_stops_at_first_unreleased_month(monkeypatch):
    monkeypatch.setattr(budget, "CGA_START", (2026, 8))
    s = FakeSession(cga_routes())
    df, meta = budget.fetch("cga:fiscal_deficit", session=s, save_raw=False)
    assert list(df["date"]) == [pd.Timestamp("2026-08-01"), pd.Timestamp("2026-09-01")]
    assert list(df["value"]) == [710249.0, 714413.0]
    assert [u.split("Published/")[1] for u in s.urls] == ["8/2026-2027.aspx", "9/2026-2027.aspx", "10/2026-2027.aspx"]
    assert meta["latest_period"].endswith("September 2026")
    pct, _ = budget.fetch("cga:fiscal_deficit_pct_be", session=s, save_raw=False)
    assert pct["value"].iloc[-1] == 42.1 and len(s.urls) == 3


def test_cga_pct_be_skips_months_compared_with_revised_estimates(monkeypatch):
    monkeypatch.setattr(budget, "CGA_START", (2024, 3))
    monkeypatch.setattr(budget, "_today", lambda: date(2024, 5, 10))
    url = budget.CGA_URL.format
    s = FakeSession({url(month=3, fy="2023-2024"): Resp(CGA_MAR), url(month=4, fy="2024-2025"): Resp(CGA_NONE)})
    target, _ = budget.fetch("cga:fiscal_deficit_pct_target", session=s, save_raw=False)
    assert list(target["value"]) == [95.3] and target["date"].iloc[0] == pd.Timestamp("2024-03-01")
    with pytest.raises(budget.BudgetError, match="No CGA values"):   # March compares with RE, not BE
        budget.fetch("cga:fiscal_deficit_pct_be", session=s, save_raw=False)


def test_cga_cache_downloads_only_latest_and_new_months(monkeypatch):
    monkeypatch.setattr(budget, "CGA_START", (2026, 8))
    budget.fetch("cga:revenue_deficit", session=FakeSession(cga_routes()))
    assert {p.name for p in (budget.RAW_DIR / "cga").glob("*.json")} == {"2026-08.json", "2026-09.json"}

    budget._MEMO.clear()
    s = FakeSession(cga_routes())
    df, _ = budget.fetch("cga:revenue_deficit", session=s)
    assert [u.split("Published/")[1] for u in s.urls] == ["9/2026-2027.aspx", "10/2026-2027.aspx"]
    assert list(df["value"]) == [138468.0, 138468.0]


def test_cga_since_limits_months(monkeypatch):
    monkeypatch.setattr(budget, "CGA_START", (2026, 8))
    s = FakeSession(cga_routes())
    df, _ = budget.fetch("cga:fiscal_deficit", since=date(2026, 9, 1), session=s, save_raw=False)
    assert list(df["date"]) == [pd.Timestamp("2026-09-01")]
    assert "8/2026-2027.aspx" not in " ".join(s.urls)


def test_cga_page_for_another_month_raises(monkeypatch):
    monkeypatch.setattr(budget, "CGA_START", (2026, 8))
    url = budget.CGA_URL.format
    s = FakeSession({url(month=8, fy="2026-2027"): Resp(CGA_SEP)})
    with pytest.raises(budget.BudgetError, match="expected"):
        budget.fetch("cga:fiscal_deficit", session=s, save_raw=False)


@pytest.mark.parametrize("series", ["baag:fiscal_deficit", "baag:nope:actual", "baag:capital_expenditure_gdp:actual",
                                    "cga:nope", "fred:x", "baag:fiscal_deficit:be"])
def test_bad_source_series(series):
    with pytest.raises(budget.BudgetError):
        budget.fetch(series, session=FakeSession({}), save_raw=False)
