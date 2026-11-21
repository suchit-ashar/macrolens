import pandas as pd

from analytics import signals as sg


def df(dates, values):
    return pd.DataFrame({"date": pd.to_datetime(dates), "value": values})


def test_policy_stance_reports_last_change():
    s = sg.policy_stance(df(["2025-12-05", "2026-10-07"], [5.25, 5.5]))
    assert s.text == "RBI tightening: +25 bp on 07 Oct 2026"
    s = sg.policy_stance(df(["2025-06-06", "2025-12-05"], [5.5, 5.25]))
    assert "easing: -25 bp" in s.text


def test_inflation_band_rbi():
    assert sg.inflation_band(6.09, 2, 6, 4).level == "bad"
    assert sg.inflation_band(4.3, 2, 6, 4).level == "good"
    assert sg.inflation_band(5.6, 2, 6, 4).level == "watch"
    assert sg.inflation_band(1.5, 2, 6, 4).text == "below the 2–6% band"


def test_inflation_point_target():
    assert sg.inflation_target(2.3).level == "good"
    assert sg.inflation_target(3.2).level == "watch"
    assert sg.inflation_target(4.5).level == "bad"


def test_rupee_direction_uses_higher_is_weaker():
    firmer = df(["2026-11-13", "2026-11-20"], [94.20, 92.97])
    assert sg.local_currency(firmer).text.startswith("rupee firmer this week")
    weaker = df(["2026-11-13", "2026-11-20"], [92.0, 94.2])
    assert sg.local_currency(weaker).level == "bad"


def test_liquidity_sign_negative_means_surplus():
    s = sg.liquidity(-87705.74)
    assert s.level == "good" and "surplus" in s.text and "87,706" in s.text
    assert "deficit" in sg.liquidity(120000).text


def test_reserves_and_trends():
    r = df(["2026-10-16", "2026-11-13"], [720000, 705342])
    assert sg.reserves(r).level == "watch"
    u = df(["2026-04-01", "2026-10-01"], [5.2, 4.9])
    assert sg.trend_lower_is_better(u, 180, "unemployment").text == "unemployment falling"


def test_value_ago_needs_history():
    assert sg.value_ago(df(["2026-11-20"], [1.0]), 7) is None
    assert sg.local_currency(df(["2026-11-20"], [92.97])).text == ""


def test_at_most_and_balance():
    assert sg.at_most(4.3, 4.5, "the 4.5% path").level == "good"
    assert sg.at_most(84.3, 60, "the 60% anchor").level == "bad"
    assert sg.balance(-0.5, 1.5, 2.5).level == "good"
    assert sg.balance(-2.0, 1.5, 2.5).level == "watch"
