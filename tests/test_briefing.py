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


def test_icons():
    assert icon_for("India ↔ Global Linkages") == "link"
    assert icon_for("Indian Markets") == "bank"
    assert icon_for("Global Macro") == "globe"
    assert icon_for("Something new") == "doc"
