from analytics.briefing import icon_for, split_briefing

SAMPLE = """# Daily Market Briefing — 22 November 2026 (IST)

**Data cut-off:** Sunday, 12:56 IST.

## Executive Summary

**FACT:** Markets fell.

## Global Equities

| Market | Close |
|---|---:|
| S&P 500 | 6,910.39 |

### Sub heading

text

## What to Watch Today

1. GIFT Nifty

## 1 Key Question for Tomorrow

**Will tech stabilise?**

---

**Source notes:** Reuters.
"""


def test_split_sections_and_cutoff():
    b = split_briefing(SAMPLE)
    assert b.cutoff == "**Data cut-off:** Sunday, 12:56 IST."
    assert [h for h, _ in b.sections] == ["Executive Summary", "Global Equities", "What to Watch Today",
                                          "1 Key Question for Tomorrow"]
    assert "### Sub heading" in b.sections[1][1] and "|---|---:|" in b.sections[1][1]


def test_notes_split_from_last_section():
    b = split_briefing(SAMPLE)
    assert b.sections[-1][1] == "**Will tech stabilise?**"
    assert b.notes == "**Source notes:** Reuters."


def test_take_is_case_insensitive_and_removes():
    b = split_briefing(SAMPLE)
    assert b.take("executive summary")[0] == "Executive Summary"
    assert b.take("what to watch", "key events")[0] == "What to Watch Today"
    assert b.take("executive summary") is None
    assert len(b.sections) == 2


def test_no_headings_and_curly_apostrophe():
    assert split_briefing("just text").sections == []
    b = split_briefing("## Today’s Market Narrative\nx")
    assert b.take("today's market narrative") is not None


from analytics.briefing import bullets, labelled, lead_bullets, lead_table, md_inline  # noqa: E402


def test_focus_bullets():
    assert bullets("- AI valuation\n- US yields\n\ntext") == ["AI valuation", "US yields"]


def test_lead_bullets_then_detail():
    lead, rest = lead_bullets("- One.\n- Two.\n- Three.\n\n**FACT:** detail\n\n- later bullet")
    assert lead == ["One.", "Two.", "Three."] and rest.startswith("**FACT:** detail") and "later bullet" in rest
    assert lead_bullets("**FACT:** no bullets")[0] == []


def test_numbered_takeaways_and_drivers():
    body = "1. **Global Macro** — Yields fell.\n2. **Commodities** — Brent up.\n3. **India** — Banks led."
    assert labelled(body, numbered=True) == [("Global Macro", "Yields fell."), ("Commodities", "Brent up."),
                                             ("India", "Banks led.")]
    drivers = "- **Rates:** 10Y fell 12 bp.\n- **Geopolitics:** Data unavailable."
    assert labelled(drivers) == [("Rates", "10Y fell 12 bp."), ("Geopolitics", "Data unavailable.")]


def test_lead_table_note_and_rest():
    body = ("| Index | Close | Change |\n|---|---:|---:|\n| S&P 500 | 6,910.39 | -3.70% |\n| Nikkei 225 | N/A | N/A |\n\n"
            "Close date: Friday, 20 November 2026.\n\n**FACT:** analysis")
    rows, note, rest = lead_table(body)
    assert rows == [["S&P 500", "6,910.39", "-3.70%"], ["Nikkei 225", "N/A", "N/A"]]
    assert note.startswith("Close date") and rest == "**FACT:** analysis"
    assert lead_table("**FACT:** no table") == ([], "", "**FACT:** no table")


def test_md_inline_escapes_html():
    out = md_inline('**Rates:** <script>x</script> [AP](https://apnews.com/a) [bad](javascript:alert(1))')
    assert "<script>" not in out and "<b>Rates:</b>" in out
    assert '<a href="https://apnews.com/a"' in out
    assert 'href="javascript' not in out  # only http(s) links become anchors


from analytics.briefing import dashboard_price  # noqa: E402

DASH = """| Indicator | Latest | Change | Direction | Why it matters |
|---|---:|---:|---|---|
| Brent | $92.29/bbl (23 Nov) | -0.30% | Down | Import-cost relief |
| Gold | N/A | N/A | N/A | x |"""


def test_dashboard_price_with_date():
    assert dashboard_price(DASH, "Brent", 20, 250) == {"value": 92.29, "change": -0.3, "day": 23, "month": 11}


def test_dashboard_price_without_date_and_text_change():
    p = dashboard_price("| Brent | $92.59/bbl | +0.66% vs 19 Nov | Up | x |", "Brent", 20, 250)
    assert p["value"] == 92.59 and p["change"] == 0.66 and p["day"] is None


def test_dashboard_price_missing_or_implausible():
    assert dashboard_price(DASH, "Gold", 1, 10000) is None
    assert dashboard_price(DASH, "WTI", 20, 250) is None
    assert dashboard_price("| Brent | $9229/bbl | | | |", "Brent", 20, 250) is None


from analytics.briefing import take_market_rows  # noqa: E402

SCORE = """Intro text.

| Sector | Market | Performance (1D/1W) | In the news? | Why (driver with source/date) |
|---|---|---:|---|---|
| Bank | India | Data unavailable | Yes | Financial shares led; Reuters, 23 Nov |
| IT | India | Data unavailable | No verified catalyst | Data unavailable |
| Technology | US | -7.27% / Data unavailable | Yes | AI losses; 20 Nov |

Closing note."""


def test_take_india_rows_keeps_us():
    news, rest = take_market_rows(SCORE, "India")
    assert news == {"bank": ("Yes", "Financial shares led; Reuters, 23 Nov"),
                    "it": ("No verified catalyst", "Data unavailable")}
    assert "| Technology | US |" in rest and "| Bank |" not in rest
    assert rest.startswith("Intro text.") and rest.endswith("Closing note.")


def test_table_left_empty_is_removed():
    only_india = "\n".join(SCORE.splitlines()[:6]) + "\n"
    news, rest = take_market_rows(only_india, "India")
    assert set(news) == {"bank", "it"} and "|" not in rest


def test_no_market_column_unchanged():
    body = "| Sector | 1D |\n|---|---|\n| Bank | +2.49% |"
    assert take_market_rows(body, "India") == ({}, body)


def test_icons():
    assert icon_for("India ↔ Global Linkages") == "link"
    assert icon_for("Indian Markets") == "bank"
    assert icon_for("Global Macro") == "globe"
    assert icon_for("Something new") == "doc"
