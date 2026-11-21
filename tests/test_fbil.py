import io
from datetime import date, datetime

import openpyxl
import pytest

from ingest import fbil


class Resp:
    def __init__(self, payload=None, content=b"", status=200):
        self._p, self.content, self.status_code, self.text = payload, content, status, str(payload)

    def json(self):
        return self._p


def make_workbook(as_of: datetime, tenors=((9.75, 7.32), (10, 7.34), (10.25, 7.35))) -> bytes:
    wb = openpyxl.Workbook()
    wb.active.title = "G-Sec"
    ws = wb.create_sheet("Par Yield")
    ws.append(["Financial Benchmarks India Private Ltd "])
    ws.append([])
    ws.append(["FBIL GSec Base/Par Yield", as_of.strftime("%d-%b-%Y")])
    ws.append([])
    ws.append(["Tenor (Year)", "YTM% p.a.(Semi-Annual)", "YTM % p.a.(Annualized)"])
    for t, y in tenors:
        ws.append([t, y, y + 0.13])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class FakeSession:
    def __init__(self, published=("2026-11-12", "2026-11-13")):
        self.published, self.downloads = list(published), []

    def get(self, url, params=None, headers=None, timeout=None):
        if url.endswith("/refrates/fetchfiltered"):
            return Resp([
                {"processRunDate": "2026-11-13 00:00:00", "subProdName": "INR / 1 USD",
                 "displayTime": "2026-11-13 13:00:00", "rate": 94.1997},
                {"processRunDate": "2026-11-13 00:00:00", "subProdName": "INR / 1 EUR",
                 "displayTime": "2026-11-13 13:00:00", "rate": 104.18},
                {"processRunDate": "2026-11-12 00:00:00", "subProdName": "INR / 1 USD",
                 "displayTime": "2026-11-12 13:00:00", "rate": 94.05},
            ] if params["fromDate"].startswith("2026") else [])
        if url.endswith("/gsec/fetchfiltered"):
            lo, hi = params["fromDate"], params["toDate"]
            return Resp([{"processRunDate": d} for d in self.published if lo <= d <= hi])
        if url.endswith("/gsec/downloadPublished"):
            self.downloads.append(params["date"])
            return Resp(content=make_workbook(datetime.fromisoformat(params["date"])))
        raise AssertionError(url)


def test_refrates_picks_one_pair_sorted():
    df, meta = fbil.fetch_refrates("INR / 1 USD", start=date(2025, 6, 1), end=date(2026, 11, 20),
                                   session=FakeSession(), save_raw=False)
    assert list(df["value"]) == [94.05, 94.1997]
    assert meta["last_updated"] == "2026-11-13 13:00:00"


def test_refrates_unknown_pair_raises():
    with pytest.raises(fbil.FbilError, match="No FBIL"):
        fbil.fetch_refrates("INR / 1 XYZ", start=date(2026, 1, 1), end=date(2026, 11, 20),
                            session=FakeSession(), save_raw=False)


def test_parse_par_yield_exact_tenor():
    as_of, value = fbil.parse_par_yield(make_workbook(datetime(2026, 11, 13)), 10)
    assert as_of == date(2026, 11, 13) and value == 7.34


def test_parse_par_yield_missing_tenor():
    with pytest.raises(fbil.FbilError, match="Tenor 30"):
        fbil.parse_par_yield(make_workbook(datetime(2026, 11, 13)), 30)


def test_gsec_downloads_only_dates_after_since(monkeypatch, tmp_path):
    monkeypatch.setattr(fbil, "RAW_DIR", tmp_path)
    monkeypatch.setattr(fbil, "PAUSE", 0)
    s = FakeSession()
    df, meta = fbil.fetch_gsec_par(10, since=date(2026, 11, 12), end=date(2026, 11, 20), session=s)
    assert s.downloads == ["2026-11-13"]
    assert list(df["value"]) == [7.34] and meta["last_updated"] == "2026-11-13"
    assert (tmp_path / "gsec" / "gsec_20261113.xlsx").exists()


def test_dispatch_rejects_unknown_kind():
    with pytest.raises(fbil.FbilError, match="Unknown"):
        fbil.fetch("nope:1")
