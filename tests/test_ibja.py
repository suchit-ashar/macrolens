import pandas as pd
import pytest

from ingest import ibja


def table(session: str, rows: list[tuple]) -> str:
    body = "".join(
        f'<tr><td data-label="{session.upper()}"><strong>{d}</strong></td>'
        f'<td data-label="Gold 999">{g}</td><td data-label="Gold 995">{g - 500}</td>'
        f'<td data-label="Silver 999">{s} </td></tr>' for d, g, s in rows)
    return (f'<div id="tab-{session}" class="tab-pane"><table><thead><tr><th></th><th>999</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


HTML = ("<html>" + table("am", [("20/11/2026", 123000, 150000)])
        + table("pm", [("20/11/2026", 123584, 150650), ("19/11/2026", 129985, 161575), ("17/11/2026", 134418, 170000)])
        + "</html>")


def test_pm_gold_sorted_by_date():
    df = ibja.parse_rates(HTML, "pm", "Gold 999")
    assert list(df["date"]) == [pd.Timestamp("2026-11-17"), pd.Timestamp("2026-11-19"), pd.Timestamp("2026-11-20")]
    assert df["value"].iloc[-1] == 123584


def test_am_table_is_separate():
    assert ibja.parse_rates(HTML, "am", "Gold 999")["value"].tolist() == [123000]


def test_silver_column_with_trailing_space():
    assert ibja.parse_rates(HTML, "pm", "Silver 999")["value"].iloc[-1] == 150650


def test_missing_table_raises():
    with pytest.raises(ibja.IbjaError):
        ibja.parse_rates("<html></html>", "pm", "Gold 999")


def test_implausible_value_raises():
    with pytest.raises(ibja.IbjaError):
        ibja.parse_rates(table("pm", [("20/11/2026", 12, 150650)]), "pm", "Gold 999")


CHART = ('<input type="hidden" id="HdnGold" value="{&quot;labels&quot;:[&quot;14/11/2026&quot;,&quot;17/11/2026&quot;,'
         '&quot;20/11/2026&quot;],&quot;purity999&quot;:[135000,134000,999999],&quot;purity916&quot;:[1,2,3]}" />')


def test_chart_history_merged_and_table_wins():
    df = ibja.parse_rates(HTML + CHART, "pm", "Gold 999")
    assert df["date"].iloc[0] == pd.Timestamp("2026-11-14") and df["value"].iloc[0] == 135000
    assert df.set_index("date").loc["2026-11-17", "value"] == 134418  # table value, not chart's 134000
    assert df["value"].iloc[-1] == 123584


def test_chart_ignored_for_am_and_silver():
    assert len(ibja.parse_rates(HTML + CHART, "am", "Gold 999")) == 1
    assert len(ibja.parse_rates(HTML + CHART, "pm", "Silver 999")) == 3


def test_fetch_meta(monkeypatch):
    class Resp:
        text = HTML
    monkeypatch.setattr(ibja, "get", lambda url, session=None: Resp())
    df, meta = ibja.fetch("pm:Gold 999")
    assert meta["last_updated"] == "2026-11-20" and len(df) == 3
