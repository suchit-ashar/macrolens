import json
from datetime import date
from pathlib import Path

import pytest

from ingest import trade

FIX = Path(__file__).parent / "fixtures" / "trade"
OCT_2026 = (FIX / "release_2335914.html").read_text(encoding="utf-8")   # 13 Nov 2026, trimmed
JAN_2024 = (FIX / "release_2006282.html").read_text(encoding="utf-8")   # 15 Feb 2024, trimmed
LISTING = (FIX / "allrel_2026-11.html").read_text(encoding="utf-8")     # Commerce, Nov 2026, trimmed


class Resp:
    status_code = 200

    def __init__(self, text):
        self.text, self.content = text, text.encode("utf-8")


class FakeSession:
    """Serves the PIB listing (GET + POST) and release pages from fixtures."""

    def __init__(self, listings=None, releases=None):
        self.listings = listings or {}   # (year, month) -> listing html
        self.releases = releases or {}   # prid -> release html
        self.gets, self.posts = [], []

    def get(self, url, params=None, headers=None, timeout=None):
        self.gets.append(url)
        if "allRel.aspx" in url:
            return Resp(LISTING)
        prid = url.rsplit("PRID=", 1)[1]
        return Resp(self.releases.get(prid, "<html><body><p>No tables here</p></body></html>"))

    def post(self, url, data=None, headers=None, timeout=None):
        key = (int(data["ctl00$ContentPlaceHolder1$ddlYear"]), int(data["ctl00$ContentPlaceHolder1$ddlMonth"]))
        self.posts.append((key, data))
        return Resp(self.listings.get(key, LISTING.split("<ul>")[0] + "<ul></ul></form></body></html>"))


class NoNetwork:
    def get(self, *a, **k):
        raise AssertionError("unexpected GET")

    def post(self, *a, **k):
        raise AssertionError("unexpected POST")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(trade, "RAW_DIR", tmp_path / "trade")
    monkeypatch.setattr(trade, "PAUSE", 0)
    monkeypatch.setattr(trade, "_today", lambda: date(2026, 11, 21))
    monkeypatch.setattr(trade, "_listing_memo", {})
    monkeypatch.setattr(trade, "_release_memo", {})


def test_parse_october_2026_release():
    rel = trade.parse_release(OCT_2026)
    assert rel["month"] == "2026-10" and rel["release_date"] == "2026-11-13"
    assert rel["values"]["2026-10"] == {"merch_exports": 49.47, "merch_imports": 89.35,
                                        "services_exports": 40.51, "services_imports": 20.72,
                                        "total_exports": 89.99, "total_imports": 110.07}
    assert rel["values"]["2025-10"]["merch_exports"] == 34.11  # same month a year earlier
    assert set(rel["values"]) == {"2026-10", "2025-10"}       # cumulative April-October table ignored


def test_parse_2024_layout_usd_billion_overall_trade():
    rel = trade.parse_release(JAN_2024)
    assert rel["month"] == "2024-01" and rel["release_date"] == "2024-02-15"
    assert rel["values"]["2024-01"]["total_exports"] == 69.72
    assert rel["values"]["2023-01"]["services_imports"] == 14.83


def test_page_without_trade_table():
    assert trade.parse_release("<table><tr><td>Exports</td><td>1.0</td></tr></table>") is None


def test_listing_titles():
    rows = dict(trade.parse_listing(LISTING))
    assert rows["2335914"].startswith("The cumulative exports (merchandise & services)")
    assert [p for p, t in rows.items() if trade.TITLE_RE.search(t)] == ["2335914"]


def test_fetch_downloads_caches_and_computes_balance(monkeypatch):
    monkeypatch.setattr(trade, "BACKFILL_START", date(2026, 10, 1))
    s = FakeSession(listings={(2026, 11): LISTING}, releases={"2335914": OCT_2026})
    df, meta = trade.fetch("pib:total_balance", session=s)
    assert [d.strftime("%Y-%m") for d in df["date"]] == ["2025-10", "2026-10"]
    # printed balance "20.09" lost its sign; computed from exports and imports
    assert df["value"].iloc[-1] == pytest.approx(89.99 - 110.07)
    assert meta["last_updated"] == "2026-11-13"
    assert [k for k, _ in s.posts] == [(2026, 11)]
    assert s.posts[0][1]["ctl00$ContentPlaceHolder1$ddlMinistry"] == "16"
    assert sum("PRID=" in u for u in s.gets) == 1   # only the title-matched candidate
    assert (trade.RAW_DIR / "2026-10_2335914.json").exists()
    assert (trade.RAW_DIR / "2026-10_2335914.html").exists()

    # a second run (new process) is served from the cache
    monkeypatch.setattr(trade, "_listing_memo", {})
    monkeypatch.setattr(trade, "_release_memo", {})
    df2, _ = trade.fetch("pib:merch_exports", session=NoNetwork())
    assert list(df2["value"]) == [34.11, 49.47]


def _write(month, prid, release_date, values):
    trade.RAW_DIR.mkdir(parents=True, exist_ok=True)
    (trade.RAW_DIR / f"{month}_{prid}.json").write_text(json.dumps(
        {"month": month, "prid": prid, "release_date": release_date, "values": values}))


def _vals(x):
    return {"merch_exports": x, "merch_imports": 2 * x, "services_exports": 1.0, "services_imports": 0.5,
            "total_exports": x + 1, "total_imports": 2 * x + 0.5}


def test_newest_release_wins_and_since_skips_network():
    _write("2025-10", "1", "2025-11-14", {"2025-10": _vals(34.38), "2024-10": _vals(30.0)})
    _write("2026-10", "2", "2026-11-13", {"2026-10": _vals(49.47), "2025-10": _vals(34.11)})
    df, _ = trade.fetch("pib:merch_exports", since=date(2026, 10, 1), session=NoNetwork())
    assert [d.strftime("%Y-%m") for d in df["date"]] == ["2024-10", "2025-10", "2026-10"]
    assert list(df["value"]) == [30.0, 34.11, 49.47]
    bal, _ = trade.fetch("pib:merch_balance", since=date(2026, 10, 1), session=NoNetwork())
    assert list(bal["value"]) == [-30.0, -34.11, -49.47]


def test_missing_month_not_yet_released_is_not_an_error(monkeypatch):
    monkeypatch.setattr(trade, "_today", lambda: date(2026, 12, 5))  # Nov release due mid-December
    _write("2026-10", "2", "2026-11-13", {"2026-10": _vals(49.47)})
    s = FakeSession()
    df, _ = trade.fetch("pib:merch_exports", since=date(2026, 10, 1), session=s)
    assert list(df["value"]) == [49.47]
    assert [k for k, _ in s.posts] == [(2026, 12)]


def test_unknown_series():
    with pytest.raises(trade.TradeError, match="Unknown trade series"):
        trade.fetch("pib:gold_imports", session=NoNetwork())


def test_listing_filter_not_applied_raises(monkeypatch):
    monkeypatch.setattr(trade, "BACKFILL_START", date(2026, 10, 1))
    s = FakeSession(listings={(2026, 11): LISTING.replace('selected="selected" value="16"', 'value="16"')})
    with pytest.raises(trade.TradeError, match="ministry filter"):
        trade.fetch("pib:merch_exports", session=s)


def test_up_to_date_with_empty_cache_returns_no_rows():
    """GitHub Actions starts with an empty download cache; if the stored data is already current,
    there is nothing new to fetch and that must not be an error."""
    class NoNetwork:
        def get(self, *a, **k):
            raise AssertionError("no request expected")

        post = get

    df, meta = trade.fetch("pib:total_exports", since=date(2026, 10, 1), session=NoNetwork(), save_raw=False)
    assert df.empty and meta["last_updated"] is None
