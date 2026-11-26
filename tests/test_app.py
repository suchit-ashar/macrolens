"""Smoke test: every page and every country renders without an exception (uses real stored data)."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "app" / "app.py")
DATA = Path(__file__).resolve().parent.parent / "data" / "clean"
PAGES = [":material/home: Overview", ":material/public: Countries", ":material/bar_chart: Indicators",
         ":material/compare_arrows: Compare", ":material/database: Data sources", ":material/newspaper: Daily briefing"]
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


@pytest.mark.parametrize("page", [PAGES[1], PAGES[3], PAGES[4], PAGES[5]])
def test_other_pages(page):
    at = run(page, "India")
    assert not at.exception, at.exception
