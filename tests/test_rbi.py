import pandas as pd
import pytest

from ingest import rbi

HTML = """<div class="policy"><h3>Policy&nbsp; Rates</h3>
<table><tr><td>Policy Repo Rate</td><td>: 5.50%</td></tr>
<tr><td>Standing Deposit Facility Rate</td><td>: 5.25%</td></tr>
<tr><td>Fixed Reverse Repo Rate</td><td>: 3.35%</td></tr></table></div>"""

LISTING = """<table>
<tr><td><a class='link2' href=BS_PressReleaseDisplay.aspx?prid=900>Money Market Operations as on October 6, 2026</a></td></tr>
<tr><td><a class='link2' href=BS_PressReleaseDisplay.aspx?prid=901>Governor’s Statement: October 7, 2026</a></td></tr>
<tr><td><a class='link2' href=BS_PressReleaseDisplay.aspx?prid=902>Monetary Policy Statement, 2026-27 Resolution of the Monetary Policy Committee (MPC) August 3 to 5, 2026</a></td></tr>
</table>"""

HIKE = """<td>Date : Oct 07, 2026</td><p>The MPC voted unanimously to increase the policy repo rate
under the liquidity adjustment facility (LAF) by 25 bps to 5.50 per cent. Consequently, the SDF rate
stands adjusted at 5.25 per cent.</p>"""

HOLD = """<td>Date : Aug 05, 2026</td><p>The MPC decided unanimously to keep the policy repo rate
under the liquidity adjustment facility (LAF) unchanged at 5.25 per cent.</p>"""


class Resp:
    status_code = 200

    def __init__(self, text):
        self.text = text


class FakeSession:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.urls.append(url)
        for key, page in self.pages.items():
            if key in url:
                return Resp(page)
        return Resp("<html></html>")


PAGES = {"prid=901": HIKE, "prid=902": HOLD, "BS_PressReleaseDisplay.aspx": LISTING, "rbi.org.in/": HTML}


def test_parses_repo_rate_not_reverse_repo():
    assert rbi.parse_rate(HTML, "Policy Repo Rate") == 5.50
    assert rbi.parse_rate(HTML, "Fixed Reverse Repo Rate") == 3.35


def test_missing_label_raises():
    with pytest.raises(rbi.RbiError, match="not found"):
        rbi.parse_rate("<p>maintenance</p>", "Policy Repo Rate")


def test_implausible_value_raises():
    with pytest.raises(rbi.RbiError, match="looks wrong"):
        rbi.parse_rate("Policy Repo Rate : 55.0%", "Policy Repo Rate")


def test_lists_only_mpc_releases():
    urls = rbi.list_mpc_releases(LISTING)
    assert [u.split("=")[-1] for u in urls] == ["901", "902"]


def test_parses_hike_and_hold_releases():
    assert rbi.parse_mpc_release(HIKE) == (pd.Timestamp("2026-10-07"), 5.5)
    assert rbi.parse_mpc_release(HOLD) == (pd.Timestamp("2026-08-05"), 5.25)
    assert rbi.parse_mpc_release("<p>Money market operations</p>") is None


def test_fetch_dates_change_from_mpc_release():
    df, meta = rbi.fetch("homepage:Policy Repo Rate", session=FakeSession(PAGES), save_raw=False)
    assert df["date"].iloc[0] == pd.Timestamp("2026-10-07") and df["value"].iloc[0] == 5.5
    assert meta["date_basis"] == "mpc_release"


def test_fetch_falls_back_to_today_without_matching_release():
    pages = {**PAGES, "prid=901": HOLD}  # no release announcing 5.50
    df, meta = rbi.fetch("homepage:Policy Repo Rate", session=FakeSession(pages), save_raw=False)
    assert meta["date_basis"] == "observed" and df["date"].iloc[0] > pd.Timestamp("2026-10-07")
