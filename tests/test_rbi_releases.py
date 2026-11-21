from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from ingest import rbi_releases as rr

FIX = Path(__file__).parent / "fixtures" / "rbi"
MMO = (FIX / "mmo_64005.html").read_text(encoding="utf-8")
WSS = (FIX / "wss_64013.html").read_text(encoding="utf-8")
BOP = (FIX / "bop_63974.html").read_text(encoding="utf-8")
LISTING = (FIX / "list.html").read_text(encoding="utf-8")

# Month archive (POST) page: an older MMO release, a corrected re-issue of Nov 19 and a BoP release.
ARCHIVE = LISTING.replace("</form>", """
<table><tr><td class="tableheader"><b>Nov 21, 2026<b></td></tr>
<tr><td><a class='link2' href=BS_PressReleaseDisplay.aspx?prid=64020>Money Market Operations as on November 19, 2026 (<span style="color: red">Revised</span>)</a></td></tr>
<tr><td class="tableheader"><b>Nov 13, 2026<b></td></tr>
<tr><td><a class='link2' href=BS_PressReleaseDisplay.aspx?prid=63974>Developments in India’s Balance of Payments for the Month of September 2026</a></td></tr>
<tr><td><a class='link2' href=BS_PressReleaseDisplay.aspx?prid=63970>Developments in India’s Balance of Payments during the Second Quarter (July-September) of 2026-27</a></td></tr>
</table></form>""")
REVISED = MMO.replace("5.59", "5.61").replace("November 19, 2026 |", "November 19, 2026 (Revised) |")
OLDER = MMO.replace("November 19, 2026", "November 18, 2026").replace("Nov 20, 2026", "Nov 19, 2026")


class Resp:
    status_code = 200

    def __init__(self, text):
        self.text = text


class FakeSession:
    def __init__(self, pages=None, archive=ARCHIVE):
        self.pages = pages or {"prid=64005": MMO, "prid=64020": REVISED, "prid=63998": OLDER,
                               "prid=64013": WSS, "prid=63974": BOP}
        self.archive, self.urls, self.posts = archive, [], []

    def get(self, url, params=None, headers=None, timeout=None):
        self.urls.append(url)
        for key, page in self.pages.items():
            if url.endswith(key):
                return Resp(page)
        return Resp(LISTING) if "prid=" not in url else Resp("<html>gone</html>")

    def post(self, url, data=None, headers=None, timeout=None):
        self.posts.append(data)
        return Resp(self.archive)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "RAW_DIR", tmp_path)
    monkeypatch.setattr(rr, "SLEEP", 0)
    rr._LIST_MEMO.clear()
    yield
    rr._LIST_MEMO.clear()


def test_parse_number_handles_indian_format_and_junk():
    assert rr.parse_number("3,37,68,416") == 33768416
    assert rr.parse_number("-87,705. 74") == -87705.74
    assert rr.parse_number("1,05, 796.00") == 105796.0
    assert rr.parse_number("–0.3") == -0.3
    for junk in ("-", "", "4.30-6.55", "Thu, 19/11/2026", "Item"):
        assert rr.parse_number(junk) is None


def test_parse_money_market_operations():
    p = rr.parse_release("mmo", MMO)
    assert p["release_date"] == "2026-11-20" and p["as_on"] == "2026-11-19"
    o = {k: v[0] for k, v in p["obs"].items()}
    assert o["wacr"] == ["2026-11-19", 5.59]
    assert o["treps_rate"] == ["2026-11-19", 5.55]
    assert o["market_repo_rate"] == ["2026-11-19", 5.58]
    assert o["sdf_amount"] == ["2026-11-19", 105796.0]
    assert o["msf_amount"] == ["2026-11-19", 18999.0]
    assert o["net_liquidity"] == ["2026-11-19", -87705.74]
    assert o["net_durable_liquidity"] == ["2026-10-31", 702107.0]  # its own as-on date


def test_parse_weekly_statistical_supplement():
    o = {k: v[0] for k, v in rr.parse_release("wss", WSS)["obs"].items()}
    assert o["fx_reserves_total"] == ["2026-11-13", 705342.0]
    assert o["fx_fca"] == ["2026-11-13", 583452.0]
    assert o["fx_gold"] == ["2026-11-13", 98613.0]
    assert o["bank_credit"] == ["2026-10-31", 23182499.0]
    assert o["deposits"] == ["2026-10-31", 28251076.0]
    assert o["m3"] == ["2026-10-31", 33768416.0]
    assert o["m3_yoy"] == ["2026-10-31", 16.5]
    assert o["bank_credit_yoy"][0] == "2026-10-31" and o["deposits_yoy"][0] == "2026-10-31"


def test_m3_date_rolls_back_a_year_when_after_release():
    # "Oct. 31" in a release dated Oct 20 can only mean last year's Oct 31.
    assert rr.parse_wss(WSS, date(2026, 10, 20))["obs"]["m3"][0][0] == "2025-10-31"


def test_m3_date_ignores_footnote_mark():
    # Real releases print "Dec. 31*"; the first date column (Mar. 31) must not be used instead.
    page = WSS.replace('class="head">Oct. 31</span>', 'class="head">Oct. 31*</span>')
    assert rr.parse_wss(page, date(2026, 11, 20))["obs"]["m3"][0] == ["2026-10-31", 33768416.0]


def test_stale_cache_is_reparsed_from_saved_page(tmp_path):
    import gzip
    import json
    folder = tmp_path / "wss"
    folder.mkdir()
    with gzip.open(folder / "2026-11-20_64013.html.gz", "wt", encoding="utf-8") as f:
        f.write(WSS)
    (folder / "2026-11-20_64013.json").write_text(json.dumps(
        {"prid": 64013, "kind": "wss", "release_date": "2026-11-20", "as_on": "2026-11-20",
         "obs": {"m3": [["2026-03-31", 1.0]]}}), encoding="utf-8")  # old parser, wrong date
    s = FakeSession()
    df, meta = rr.fetch("wss:m3", since=date(2026, 11, 2), session=s)
    assert meta["releases_downloaded"] == 0
    assert list(zip(df["date"], df["value"])) == [(pd.Timestamp("2026-10-31"), 33768416.0)]
    assert json.loads((folder / "2026-11-20_64013.json").read_text())["parser"] == rr.PARSER_VERSION


def test_parse_balance_of_payments_keeps_year_ago_column():
    p = rr.parse_release("bop", BOP)
    assert p["as_on"] == "2026-09-01"
    assert p["obs"]["current_account"] == [["2025-09-01", -5.2], ["2026-09-01", -7.4]]
    assert dict(p["obs"]["fdi_net"])["2026-09-01"] == -4.9
    assert dict(p["obs"]["fdi_india_net"])["2026-09-01"] == -0.5
    assert dict(p["obs"]["fpi_net"])["2026-09-01"] == -6.7


def test_unrecognised_page_raises():
    with pytest.raises(rr.RbiReleaseError):
        rr.parse_release("mmo", "<p>Date : Nov 20, 2026</p><p>maintenance</p>")


def test_listing_and_classification():
    entries = rr.parse_listing(LISTING)
    kinds = {e["prid"]: rr.classify(e["title"]) for e in entries}
    assert kinds[64005] == "mmo" and kinds[64013] == "wss" and kinds[64017] is None
    assert next(e for e in entries if e["prid"] == 64005)["date"] == "2026-11-20"
    assert rr.classify("Developments in India's Balance of Payments during the Second Quarter") is None


def test_fetch_backfills_caches_and_prefers_later_prid(tmp_path):
    s = FakeSession()
    df, meta = rr.fetch("mmo:wacr", since=date(2026, 11, 2), session=s)
    assert [p["hdnMonth"] for p in s.posts] == ["11"] and s.posts[0]["hdnYear"] == "2026"
    assert s.posts[0]["__VIEWSTATEGENERATOR"] == "380F4D6F"
    assert list(df["date"]) == [pd.Timestamp("2026-11-18"), pd.Timestamp("2026-11-19")]
    assert df["value"].iloc[-1] == 5.61  # the revised release (higher prid) wins
    assert meta["last_updated"] == "2026-11-20" and meta["fetched_at"].endswith("+00:00")
    assert (tmp_path / "mmo" / "2026-11-19_64020.json").exists()
    assert (tmp_path / "mmo" / "2026-11-19_64020.html.gz").exists()

    # Other series from the same releases come from the cache: no release page downloaded.
    s2 = FakeSession()
    df2, meta2 = rr.fetch("mmo:net_durable_liquidity", since=date(2026, 11, 2), session=s2)
    assert not [u for u in s2.urls if "prid=" in u] and meta2["releases_downloaded"] == 0
    assert list(df2["date"]) == [pd.Timestamp("2026-10-31")] and df2["value"].iloc[0] == 702107.0


def test_fetch_without_since_scans_from_backfill_start(monkeypatch):
    monkeypatch.setattr(rr, "BACKFILL_START", {**rr.BACKFILL_START, "bop": date(2026, 9, 1)})
    s = FakeSession()
    df, _ = rr.fetch("bop:current_account", session=s, save_raw=False)
    assert [p["hdnMonth"] for p in s.posts][:3] == ["9", "10", "11"]
    assert dict(zip(df["date"], df["value"])) == {pd.Timestamp("2025-09-01"): -5.2, pd.Timestamp("2026-09-01"): -7.4}


def test_fetch_errors():
    with pytest.raises(rr.RbiReleaseError, match="Unknown"):
        rr.fetch("mmo:nope", session=FakeSession())
    empty = FakeSession(archive=LISTING.replace("Weekly Statistical", "Weekly Something"))
    empty.pages = {}
    with pytest.raises(rr.RbiReleaseError, match="no observations"):
        rr.fetch("bop:fdi_net", since=date(2026, 11, 1), session=empty, save_raw=False)
