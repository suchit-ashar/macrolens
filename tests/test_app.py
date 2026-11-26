"""Smoke test: every page and every country renders without an exception (uses real stored data)."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "app" / "app.py")
DATA = Path(__file__).resolve().parent.parent / "data" / "clean"
PAGES = [":material/home: Overview", ":material/public: Countries", ":material/bar_chart: Indicators",
         ":material/compare_arrows: Compare", None, ":material/newspaper: Daily briefing"]  # [4]: Data sources, now linked from Compare
COUNTRIES = ["India", "United States", "Euro area", "China", "Japan", "United Kingdom", "France", "Germany"]

pytestmark = pytest.mark.skipif(not any(DATA.glob("*.parquet")), reason="no stored data")


def run(page: str, country: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["page"] = page
    at.session_state["country_pick"] = country
    return at.run()


@pytest.mark.parametrize("country", COUNTRIES)
def test_overview_each_country(country):
    at = run(PAGES[0], country)
    assert not at.exception, at.exception


@pytest.mark.parametrize("country", COUNTRIES)
def test_indicators_each_country(country):
    at = run(PAGES[2], country)
    assert not at.exception, at.exception


@pytest.mark.parametrize("page", [PAGES[1], PAGES[3], PAGES[5]])
def test_other_pages(page):
    at = run(page, "India")
    assert not at.exception, at.exception


def test_data_sources_not_in_menu_but_linked_from_compare():
    at = run(PAGES[3], "India")
    assert not any("Data sources" in o for o in at.radio[0].options)
    at.button(key="open_sources").click().run()
    assert not at.exception, at.exception
    assert any("Data sources" in m.value for m in at.markdown)
    assert at.radio[0].value is None  # no menu item is highlighted while on Data sources
    at.button(key="close_sources").click().run()
    assert not at.exception, at.exception
    assert any("<h1>Compare</h1>" in m.value for m in at.markdown)
    # From Data sources, every menu item navigates, including Compare itself.
    for target, heading in [(PAGES[3], "<h1>Compare</h1>"), (PAGES[1], "<h1>Countries</h1>")]:
        at.button(key="open_sources").click().run()  # we are on Compare before each round
        assert any("Data sources" in m.value for m in at.markdown)
        at.radio[0].set_value(target).run()
        assert not at.exception, at.exception
        assert any(heading in m.value for m in at.markdown), target
