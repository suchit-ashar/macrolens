"""MacroLens dashboard (Streamlit).

Run:  streamlit run app/app.py
Reads data/clean/*.parquet through storage/db.py (DuckDB). Educational only.
"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.registry import load_registry  # noqa: E402
from storage import db  # noqa: E402
from transform.checks import run_checks  # noqa: E402
from transform.normalize import yoy_pct  # noqa: E402

DISCLAIMER = ("For education only. Not investment advice or a research recommendation. "
              "Data comes from the official sources linked on each chart and may be revised.")
COUNTRY_NAMES = {"IN": "India", "US": "United States", "GLOBAL": "Global"}
RANGES = {"1Y": 365, "3Y": 3 * 365, "5Y": 5 * 365, "10Y": 10 * 365, "Max": None}
# Index series that get a derived year-on-year % view, and the period count for YoY.
YOY = {"us_cpi": 12, "in_cpi_2024base": 12, "in_cpi_2024base_back": 12}
COLORS = {"IN": "#E07B39", "US": "#3B6FB6", "GLOBAL": "#5B8C5A"}
SHORT = {"in_10y": "10Y G-sec yield", "in_cpi_2024base": "CPI inflation", "in_repo_rate": "Repo rate",
         "inr_usd": "INR per USD", "us_10y": "10Y Treasury", "us_cpi": "CPI inflation",
         "us_dollar_broad": "Dollar index (broad)", "us_policy_rate": "Fed funds (upper)",
         "brent": "Brent crude"}

st.set_page_config(page_title="MacroLens", page_icon="📈", layout="wide")


# ---------- data ----------
def _db_stamp() -> float:
    return max((p.stat().st_mtime for p in db.CLEAN_DIR.glob("*.parquet")), default=0)


@st.cache_data(show_spinner=False)
def load_all(stamp: float):
    con = db.connect()
    summary = con.execute("SELECT * FROM summary").df()
    obs = con.execute("SELECT indicator_id, date, value FROM latest ORDER BY indicator_id, date").df()
    allv = con.execute("SELECT * FROM observations").df()
    con.close()
    obs["date"] = pd.to_datetime(obs["date"])
    allv["date"] = pd.to_datetime(allv["date"])
    return summary, obs, allv


@st.cache_data(show_spinner=False)
def quality(stamp: float):
    registry = load_registry()
    _, _, allv = load_all(stamp)
    issues = []
    for iid, entry in registry.items():
        issues += run_checks(allv[allv["indicator_id"] == iid], entry)
    return pd.DataFrame([vars(i) for i in issues], columns=["indicator_id", "check", "severity", "message"])


# ---------- formatting ----------
def fmt_value(v, unit):
    if pd.isna(v):
        return "–"
    return {"percent": f"{v:.2f}%", "inr_per_usd": f"₹{v:,.2f}",
            "usd_per_barrel": f"${v:,.2f}/bbl"}.get(unit, f"{v:,.2f}")


def fmt_change(row):
    if pd.isna(row["prev_value"]) or pd.isna(row["value"]):
        return None
    d = row["value"] - row["prev_value"]
    if row["unit"] == "percent":
        return f"{d * 100:+.0f} bp"
    return f"{d / row['prev_value'] * 100:+.2f}%"


def source_line(row) -> str:
    parts = [f"Source: [{row['source']}]({row['source_url']})",
             f"latest {pd.Timestamp(row['date']).date()}" if pd.notna(row["date"]) else "no data"]
    if isinstance(row.get("release_date"), str) and row["release_date"] not in ("", "None"):
        parts.append(f"source updated {row['release_date'][:10]}")
    if isinstance(row.get("fetched_at"), str):
        parts.append(f"fetched {row['fetched_at'][:10]}")
    return " · ".join(parts)


def clip(df: pd.DataFrame, days: int | None) -> pd.DataFrame:
    if days is None or df.empty:
        return df
    return df[df["date"] >= pd.Timestamp(date.today()) - pd.Timedelta(days=days)]


def line_chart(traces: list[dict], unit_label: str, height: int = 300):
    fig = go.Figure()
    for t in traces:
        fig.add_trace(go.Scatter(x=t["df"]["date"], y=t["df"]["value"], name=t["name"], mode="lines",
                                 line=dict(color=t.get("color"), width=2, shape=t.get("shape", "linear"),
                                           dash=t.get("dash"))))
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=40 if len(traces) > 1 else 10, b=10),
                      yaxis_title=unit_label, showlegend=len(traces) > 1,
                      legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0), hovermode="x unified")
    values = pd.concat([t["df"]["value"] for t in traces if not t["df"].empty])
    if not values.empty and values.max() - values.min() < 1e-9:  # flat line: avoid a zero-height axis
        fig.update_yaxes(range=[values.min() - 1, values.max() + 1])
    return fig


def event_to_steps(df: pd.DataFrame) -> pd.DataFrame:
    """Extend an event series to today so the step line shows the rate still in force."""
    if df.empty:
        return df
    tail = pd.DataFrame({"date": [pd.Timestamp(date.today())], "value": [df["value"].iloc[-1]]})
    return pd.concat([df, tail], ignore_index=True)


UNIT_LABEL = {"percent": "%", "index": "index", "inr_per_usd": "INR per USD", "usd_per_barrel": "USD per barrel"}


# ---------- page ----------
stamp = _db_stamp()
if stamp == 0:
    st.error("No data yet. Run `python -m ingest.run_all` first.")
    st.stop()
summary, obs, allv = load_all(stamp)
series = {iid: g[["date", "value"]].reset_index(drop=True) for iid, g in obs.groupby("indicator_id")}
rows = summary.set_index("indicator_id")

st.title("MacroLens")
st.caption("Official macro data for India, the US and global markets, updated daily. " + DISCLAIMER)

with st.sidebar:
    st.header("View")
    countries = st.multiselect("Countries", ["IN", "US", "GLOBAL"], default=["IN", "US", "GLOBAL"],
                               format_func=lambda c: COUNTRY_NAMES[c])
    window = st.radio("Chart range", list(RANGES), index=2, horizontal=True)
    cpi_view = st.radio("CPI shown as", ["YoY % (derived)", "Index level"], index=0)
    st.divider()
    st.caption(f"Data last updated: {pd.to_datetime(summary['fetched_at'].dropna()).max():%d %b %Y}"
               if summary["fetched_at"].notna().any() else "")

days = RANGES[window]
shown = summary[summary["country"].isin(countries)]

tab_overview, tab_charts, tab_compare, tab_quality, tab_data = st.tabs(
    ["Overview", "Charts", "India vs US", "Data quality", "Data & sources"])

# ---- Overview: one card per indicator ----
with tab_overview:
    for country in [c for c in ["IN", "US", "GLOBAL"] if c in countries]:
        group = shown[(shown["country"] == country) & (shown["indicator_id"] != "in_cpi_2024base_back")]
        if group.empty:
            continue
        st.subheader(COUNTRY_NAMES[country])
        cols = st.columns(min(len(group), 4))
        for i, (_, row) in enumerate(group.iterrows()):
            with cols[i % len(cols)]:
                label = SHORT.get(row["indicator_id"], row["name"])
                y = (yoy_pct(series.get(row["indicator_id"], pd.DataFrame(columns=["date", "value"])),
                             YOY[row["indicator_id"]])
                     if row["indicator_id"] in YOY and cpi_view.startswith("YoY") else pd.DataFrame())
                if not y.empty:
                    delta = (y["value"].iloc[-1] - y["value"].iloc[-2]) * 100 if len(y) > 1 else None
                    st.metric("CPI YoY (derived)",f"{y['value'].iloc[-1]:.2f}%",
                              f"{delta:+.0f} bp" if delta is not None else None, delta_color="off",
                              help=row["name"])
                else:
                    st.metric(label if row["indicator_id"] not in YOY else f"{label} (index)",
                              fmt_value(row["value"], row["unit"]), fmt_change(row), delta_color="off",
                              help=row["name"])
                st.caption(source_line(row))
    st.caption("Change is versus the previous observation. bp = basis points (0.01 percentage point).")

# ---- Charts: one per indicator ----
with tab_charts:
    ids = [i for i in shown["indicator_id"] if i != "in_cpi_2024base_back"]
    for pair in [ids[i:i + 2] for i in range(0, len(ids), 2)]:
        cols = st.columns(2)
        for col, iid in zip(cols, pair):
            row = rows.loc[iid]
            df = series.get(iid, pd.DataFrame(columns=["date", "value"]))
            with col:
                st.markdown(f"**{row['name']}**")
                traces, unit_label = [], UNIT_LABEL.get(row["unit"], row["unit"])
                if iid in YOY and cpi_view.startswith("YoY"):
                    unit_label = "% YoY (derived)"
                    traces.append({"df": clip(yoy_pct(df, YOY[iid]), days), "name": "YoY % (derived)",
                                   "color": COLORS[row["country"]]})
                    if iid == "in_cpi_2024base" and "in_cpi_2024base_back" in series:
                        traces.append({"df": clip(yoy_pct(series["in_cpi_2024base_back"], 12), days),
                                       "name": "Back series YoY (derived)", "color": "#999999", "dash": "dot"})
                elif row["frequency"] == "event":
                    traces.append({"df": clip(event_to_steps(df), days), "name": row["name"],
                                   "color": COLORS[row["country"]], "shape": "hv"})
                else:
                    traces.append({"df": clip(df, days), "name": row["name"], "color": COLORS[row["country"]]})
                    if iid == "in_cpi_2024base" and "in_cpi_2024base_back" in series:
                        traces.append({"df": clip(series["in_cpi_2024base_back"], days),
                                       "name": "Official back series", "color": "#999999", "dash": "dot"})
                if all(t["df"].empty for t in traces):
                    st.info("No observations in this range.")
                else:
                    st.plotly_chart(line_chart(traces, unit_label), use_container_width=True)
                st.caption(source_line(row))
    st.caption("India CPI: the live 2024-base series and MoSPI's official back series are drawn as separate "
               "lines and never joined. YoY % is computed by MacroLens from the index (derived).")

# ---- India vs US ----
with tab_compare:
    st.markdown("Side-by-side views of the same concept in both countries. Levels are not directly "
                "comparable across currencies and inflation regimes; use these for direction and spread.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Policy rates**")
        tr = []
        if "in_repo_rate" in series:
            tr.append({"df": clip(event_to_steps(series["in_repo_rate"]), days), "name": "RBI repo rate",
                       "color": COLORS["IN"], "shape": "hv"})
        if "us_policy_rate" in series:
            tr.append({"df": clip(series["us_policy_rate"], days), "name": "Fed funds (upper)",
                       "color": COLORS["US"], "shape": "hv"})
        if tr:
            st.plotly_chart(line_chart(tr, "%"), use_container_width=True)
        st.caption("Sources: RBI, FRED")
    with c2:
        st.markdown("**10-year government bond yields**")
        tr = [{"df": clip(series[k], days), "name": n, "color": COLORS[c]}
              for k, n, c in [("in_10y", "India 10Y par yield (FBIL)", "IN"), ("us_10y", "US 10Y Treasury", "US")]
              if k in series]
        if tr:
            st.plotly_chart(line_chart(tr, "%"), use_container_width=True)
        if {"in_10y", "us_10y"} <= series.keys():
            spread = series["in_10y"].merge(series["us_10y"], on="date", suffixes=("_in", "_us"))
            spread = spread.assign(value=(spread["value_in"] - spread["value_us"]))[["date", "value"]]
            if not spread.empty:
                st.caption(f"India–US 10Y spread (derived): {spread['value'].iloc[-1] * 100:.0f} bp on "
                           f"{spread['date'].iloc[-1].date()}")
        st.caption("Sources: FBIL, FRED")
    c3, c4 = st.columns(2)
    with c3:
        st.markdown("**Inflation, YoY % (derived from CPI index)**")
        tr = [{"df": clip(yoy_pct(series[k], 12), days), "name": n, "color": COLORS[c], "dash": d}
              for k, n, c, d in [("in_cpi_2024base", "India CPI (2024 base, live)", "IN", None),
                                 ("in_cpi_2024base_back", "India CPI (back series)", "IN", "dot"),
                                 ("us_cpi", "US CPI-U", "US", None)] if k in series]
        if tr:
            st.plotly_chart(line_chart(tr, "% YoY"), use_container_width=True)
        st.caption("Sources: MoSPI, FRED (BLS)")
    with c4:
        st.markdown("**Rupee and dollar**")
        tr = [{"df": clip(series[k], days), "name": n, "color": COLORS[c]}
              for k, n, c in [("inr_usd", "INR per USD (FBIL)", "IN")] if k in series]
        if tr:
            st.plotly_chart(line_chart(tr, "INR per USD"), use_container_width=True)
        st.caption("Source: FBIL. A higher number means a weaker rupee.")

# ---- Data quality ----
with tab_quality:
    q = quality(stamp)
    if q.empty:
        st.success("All checks passed: no gaps, unusual jumps, stale or malformed series.")
    else:
        n_err, n_warn = (q["severity"] == "error").sum(), (q["severity"] == "warn").sum()
        (st.error if n_err else st.warning)(f"{n_err} error(s), {n_warn} warning(s)")
        st.dataframe(q, use_container_width=True, hide_index=True)
    st.caption("Checks: missing or future values, gaps longer than normal for the frequency (last 2 years), "
               "unusually large moves in the last 30 observations, and series that have stopped updating. "
               "Details: transform/checks.py.")

# ---- Data & sources ----
with tab_data:
    table = summary[["indicator_id", "name", "country", "value", "unit", "date", "first_date",
                     "frequency", "source", "source_url", "release_date", "fetched_at"]].copy()
    st.dataframe(table, use_container_width=True, hide_index=True,
                 column_config={"source_url": st.column_config.LinkColumn("source link")})
    pick = st.selectbox("Download one series", summary["indicator_id"],
                        format_func=lambda i: f"{i} — {rows.loc[i, 'name']}")
    out = series.get(pick, pd.DataFrame(columns=["date", "value"])).copy()
    show_vintages = st.checkbox("Include every vintage (revisions)")
    if show_vintages:
        out = allv[allv["indicator_id"] == pick][["date", "value", "fetched_at"]].sort_values(["date", "fetched_at"])
    st.download_button("Download CSV", out.to_csv(index=False).encode("utf-8"),
                       file_name=f"{pick}{'_vintages' if show_vintages else ''}.csv", mime="text/csv")
    st.caption("Raw source files are kept unmodified in data/raw for audit. Derived series (YoY %, spreads) "
               "are computed in the app and labelled as derived.")

st.divider()
st.caption(DISCLAIMER)
