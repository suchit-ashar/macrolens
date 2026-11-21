"""MacroLens dashboard (Streamlit) — design B + C.

B: clean finance layout (white, navy, India saffron accent) with a one-line summary.
C: each topic has its own colour; every card carries a rule-based traffic light
   (analytics/signals.py) comparing the number with an official target or recent history.

Run:  streamlit run app/app.py
A country selector drives the page: India, United States, Euro area, China, Japan, Compare.
Charts and cards skip series that are missing, so a failed fetch never breaks the page.
"""
import sys
from datetime import date, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics import signals as sg  # noqa: E402
from ingest.registry import load_registry  # noqa: E402
from storage import db  # noqa: E402
from transform.checks import run_checks  # noqa: E402
from transform.normalize import yoy_pct  # noqa: E402

st.set_page_config(page_title="MacroLens", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")

NAVY, SAFFRON, INK, MUTED, LINE = "#0B2545", "#E07B39", "#0B2545", "#64748B", "#E5E7EB"
# Design C: one colour per topic -> (text/accent, light background)
TOPIC = {
    "rates": ("#4338CA", "#EEF2FF", "Policy rates"), "currency": ("#7C3AED", "#F5F3FF", "Currency"),
    "bonds": ("#1D4ED8", "#EFF6FF", "Bonds"), "liquidity": ("#0F766E", "#F0FDFA", "Liquidity"),
    "inflation": ("#B91C1C", "#FEF2F2", "Inflation"), "growth": ("#047857", "#ECFDF5", "Growth"),
    "external": ("#B45309", "#FFFBEB", "External"), "fiscal": ("#334155", "#F1F5F9", "Fiscal"),
    "jobs": ("#BE185D", "#FDF2F8", "Jobs"), "commodities": ("#92400E", "#FEF7EE", "Commodities"),
}
LIGHT = {"good": ("#16A34A", "#DCFCE7", "#166534"), "watch": ("#D97706", "#FEF3C7", "#92400E"),
         "bad": ("#DC2626", "#FDE2E1", "#991B1B"), "neutral": ("#64748B", "#EEF2F6", "#334155")}
COUNTRY_COLOR = {"IN": SAFFRON, "US": "#1D4ED8", "EA": "#047857", "CN": "#B91C1C", "JP": "#7C3AED", "GLOBAL": "#475569"}
SERIES_PALETTE = ["#0B2545", SAFFRON, "#1D4ED8", "#047857", "#B91C1C", "#7C3AED", "#0F766E", "#B45309"]
RANGES = {"1Y": 365, "3Y": 3 * 365, "5Y": 5 * 365, "10Y": 10 * 365, "Max": None}

st.markdown(f"""<style>
.block-container{{padding-top:1.6rem;max-width:1320px}}
[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"]{{display:none}}
.ml-head{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}}
.ml-brand{{font-size:1.9rem;font-weight:700;color:{NAVY};letter-spacing:-.01em}}
.ml-brand span{{color:{SAFFRON}}}
.ml-tag{{color:{MUTED};font-size:.92rem;margin:.1rem 0 .6rem}}
.ml-upd{{color:{MUTED};font-size:.85rem}}
.ml-sum{{background:#FFF4EC;border:1px solid #F8D9C2;border-radius:10px;padding:.65rem .9rem;color:#7A3A12;
  font-size:.95rem;margin:.4rem 0 1rem}}
.ml-sum b{{color:#5B2A0C}}
.ml-sec{{display:flex;align-items:center;gap:.5rem;margin:1.1rem 0 .5rem;font-weight:650;font-size:1.02rem}}
.ml-sec i{{width:10px;height:10px;border-radius:3px;display:inline-block}}
.ml-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(205px,1fr));gap:.7rem}}
.ml-card{{border-radius:12px;padding:.8rem .95rem;min-height:128px}}
.ml-card .l{{font-size:.8rem;font-weight:600;margin:0 0 .25rem}}
.ml-card .v{{font-size:1.55rem;font-weight:700;color:{INK};margin:0;line-height:1.2}}
.ml-card .d{{font-size:.76rem;margin:.35rem 0 0}}
.ml-card .d span{{border-radius:6px;padding:1px 7px;font-weight:600}}
.ml-card .s{{font-size:.78rem;margin:.4rem 0 0;display:flex;gap:.35rem;align-items:baseline}}
.ml-card .s i{{width:8px;height:8px;border-radius:50%;display:inline-block;flex:none;transform:translateY(-1px)}}
.ml-card .w{{font-size:.72rem;color:{MUTED};margin:.35rem 0 0}}
.ml-cap{{color:{MUTED};font-size:.8rem;margin:-.2rem 0 .8rem}}
.ml-cap a{{color:{MUTED}}}
.ml-legend{{color:{MUTED};font-size:.78rem;display:flex;gap:1rem;flex-wrap:wrap;margin:.2rem 0 .6rem}}
.ml-legend i{{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:.3rem}}
div[data-testid="stSegmentedControl"] button p{{font-size:.92rem}}
.stTabs [data-baseweb="tab-list"]{{gap:.3rem}}
.stTabs [data-baseweb="tab"]{{padding:.35rem .7rem}}
</style>""", unsafe_allow_html=True)


# ======================= data =======================
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


stamp = _db_stamp()
if stamp == 0:
    st.error("No data yet. Run `python -m ingest.run_all` first.")
    st.stop()
summary, obs, allv = load_all(stamp)
S = {iid: g[["date", "value"]].reset_index(drop=True) for iid, g in obs.groupby("indicator_id")}
ROWS = summary.set_index("indicator_id")
EMPTY = pd.DataFrame(columns=["date", "value"])


def has(iid: str) -> bool:
    return iid in ROWS.index and iid in S and not S[iid].empty


def get(iid: str) -> pd.DataFrame:
    return S.get(iid, EMPTY)


def last(iid: str):
    return float(get(iid)["value"].iloc[-1]) if has(iid) else None


def yoy(iid: str, periods: int = 12) -> pd.DataFrame:
    return yoy_pct(get(iid), periods) if has(iid) else EMPTY


def diff(a: str, b: str) -> pd.DataFrame:
    if not (has(a) and has(b)):
        return EMPTY
    m = get(a).merge(get(b), on="date", suffixes=("_a", "_b"))
    return pd.DataFrame({"date": m["date"], "value": m["value_a"] - m["value_b"]})


# ======================= formatting =======================
def fmt_value(v, unit):
    if v is None or pd.isna(v):
        return "–"
    if unit == "inr_crore":
        return f"₹{v / 1e5:,.2f} lakh cr" if abs(v) >= 1e5 else f"₹{v:,.0f} cr"
    if unit == "usd_million":
        return f"${v / 1e3:,.1f} bn" if abs(v) >= 1e3 else f"${v:,.0f} mn"
    if unit == "usd":
        return f"${v / 1e9:,.1f} bn" if abs(v) >= 1e9 else f"${v:,.0f}"
    if unit == "eur_million":
        return f"€{v / 1e6:,.2f} tn"
    if unit == "jpy_billion":
        return f"¥{v / 1e3:,.0f} tn"
    return {"percent": f"{v:.2f}%", "percent_of_gdp": f"{v:.1f}% of GDP", "inr_per_usd": f"₹{v:,.2f}",
            "inr": f"₹{v:,.2f}", "usd_per_barrel": f"${v:,.2f}", "usd_billion": f"${v:,.1f} bn",
            "usd_per_eur": f"${v:,.4f}", "cny": f"¥{v:,.4f}", "jpy": f"¥{v:,.2f}"}.get(unit, f"{v:,.2f}")


def fmt_delta(d, unit) -> str:
    if unit in ("percent", "percent_of_gdp", "pp_spread"):
        return f"{d:+.1f} pp" if unit == "percent_of_gdp" else f"{d * 100:+.0f} bp"
    s = fmt_value(abs(d), unit)
    return ("+" if d >= 0 else "−") + s


def period_label(ts, frequency) -> str:
    ts = pd.Timestamp(ts)
    if frequency == "annual":
        return str(ts.year)
    if frequency == "quarterly":
        return f"{ts:%b}–{ts + pd.DateOffset(months=2):%b %Y}"
    if frequency == "monthly":
        return f"{ts:%b %Y}"
    return f"{ts:%d %b %Y}"


# ======================= cards =======================
def card(iid: str, label: str, topic: str, *, df: pd.DataFrame | None = None, unit: str | None = None,
         signal: sg.Signal | None = None, good: str | None = None, derived: bool = False) -> str:
    """HTML for one card. `df` overrides the stored series (e.g. a derived YoY %);
    `good` = 'up' or 'down' colours the change badge (None = grey)."""
    if iid not in ROWS.index:
        return ""
    row = ROWS.loc[iid]
    data = (get(iid) if df is None else df).dropna()
    if data.empty:
        return ""
    unit = unit or row["unit"]
    v = float(data["value"].iloc[-1])
    prev = float(data["value"].iloc[-2]) if len(data) > 1 else None
    if row["frequency"] == "event" and df is None:
        changes = data[data["value"].diff().fillna(0) != 0]
        prev = float(data[data["date"] < changes["date"].iloc[-1]]["value"].iloc[-1]) if not changes.empty else None
    accent, bg, _ = TOPIC[topic]
    badge = ""
    if prev is not None and abs(v - prev) > 1e-12:
        d = v - prev
        tone = "neutral" if good is None else ("good" if (d > 0) == (good == "up") else "bad")
        _, bbg, bfg = LIGHT[tone]
        badge = f'<p class="d"><span style="background:{bbg};color:{bfg}">{"▲" if d > 0 else "▼"} {fmt_delta(abs(d), unit).lstrip("+")}</span></p>'
    sig = ""
    if signal and signal.text:
        dot, _, fg = LIGHT[signal.level]
        sig = f'<p class="s" style="color:{fg}"><i style="background:{dot}"></i>{signal.text}</p>'
    when = period_label(data["date"].iloc[-1], row["frequency"])
    value = f"{v:+.2f} pp" if unit == "pp_spread" else (f"{v:.2f}%" if derived else fmt_value(v, unit))
    return (f'<div class="ml-card" style="background:{bg}"><p class="l" style="color:{accent}">{label}'
            f'{" · derived" if derived else ""}</p><p class="v">{value}</p>{badge}{sig}'
            f'<p class="w">{when} · {row["source"]}</p></div>')


def cards(items: list[str]):
    html = "".join(i for i in items if i)
    if html:
        st.markdown(f'<div class="ml-grid">{html}</div>', unsafe_allow_html=True)


def section(topic: str, title: str | None = None):
    accent, _, name = TOPIC[topic]
    st.markdown(f'<div class="ml-sec" style="color:{accent}"><i style="background:{accent}"></i>{title or name}</div>',
                unsafe_allow_html=True)


def legend():
    items = "".join(f'<span><i style="background:{LIGHT[k][0]}"></i>{t}</span>' for k, t in
                    [("good", "within target / improving"), ("watch", "drifting / worth watching"),
                     ("bad", "outside target / deteriorating"), ("neutral", "descriptive")])
    st.markdown(f'<div class="ml-legend">{items}<span>Signals compare official data with official targets or '
                f'recent history; they are not forecasts.</span></div>', unsafe_allow_html=True)


# ======================= charts =======================
DAYS = None  # set by the range control


def clip(df: pd.DataFrame, frequency: str) -> pd.DataFrame:
    if DAYS is None or df.empty or frequency in ("quarterly", "annual"):
        return df
    return df[df["date"] >= pd.Timestamp(date.today()) - pd.Timedelta(days=DAYS)]


def line(iid: str, label: str, color: str | None = None, dash: str | None = None, df: pd.DataFrame | None = None,
         kind: str = "line", scale: float = 1.0):
    if iid not in ROWS.index:
        return None
    row = ROWS.loc[iid]
    data = get(iid) if df is None else df
    if data.empty:
        return None
    data = data.assign(value=data["value"] * scale)
    shape = "linear"
    if row["frequency"] == "event":
        data = pd.concat([data, pd.DataFrame({"date": [pd.Timestamp(date.today())], "value": [data["value"].iloc[-1]]})])
        shape = "hv"
    return {"df": clip(data, row["frequency"]), "name": label, "color": color or COUNTRY_COLOR.get(row["country"]),
            "dash": dash, "shape": shape, "kind": kind}


def chart(title: str, traces: list, unit: str, src: tuple = (), note: str = "", height: int = 300,
          band=None, hlines=(), barmode: str = "group"):
    traces = [t for t in traces if t is not None and not t["df"].empty]
    st.markdown(f"**{title}**")
    if not traces:
        st.caption("Data for this chart is not available yet.")
        return
    fig = go.Figure()
    if band:
        fig.add_hrect(y0=band[0], y1=band[1], fillcolor="#16A34A", opacity=0.07, line_width=0)
    for i, t in enumerate(traces):
        color = t["color"] or SERIES_PALETTE[i % len(SERIES_PALETTE)]
        if t["kind"] == "bar":
            fig.add_trace(go.Bar(x=t["df"]["date"], y=t["df"]["value"], name=t["name"], marker_color=color))
        else:
            fig.add_trace(go.Scatter(x=t["df"]["date"], y=t["df"]["value"], name=t["name"], mode="lines",
                                     line=dict(color=color, width=2.2, shape=t["shape"], dash=t["dash"])))
    for y, text in hlines:
        fig.add_hline(y=y, line_dash="dot", line_color="#94A3B8", annotation_text=text,
                      annotation_position="top left", annotation_font_color=MUTED)
    many = len(traces) > 1
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=34 if many else 8, b=8), yaxis_title=unit,
                      showlegend=many, legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, font=dict(size=12)),
                      hovermode="x unified", barmode=barmode, plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
                      font=dict(color=INK, size=12))
    fig.update_xaxes(showgrid=False, linecolor=LINE)
    fig.update_yaxes(gridcolor="#EEF1F5", zerolinecolor="#CBD5E1")
    vals = pd.concat([t["df"]["value"] for t in traces])
    if vals.max() - vals.min() < 1e-9:
        fig.update_yaxes(range=[vals.min() - 1, vals.max() + 1])
    st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
    src = [i for i in src if i in ROWS.index]
    if src or note:
        links = ", ".join(dict.fromkeys(f'<a href="{ROWS.loc[i, "source_url"]}" target="_blank">{ROWS.loc[i, "source"]}</a>' for i in src))
        notes = " ".join(dict.fromkeys(ROWS.loc[i, "note"] for i in src if isinstance(ROWS.loc[i, "note"], str)))
        st.markdown(f'<div class="ml-cap">{"Source: " + links if links else ""} {notes} {note}</div>', unsafe_allow_html=True)


def pair(left, right):
    c1, c2 = st.columns(2, gap="large")
    with c1:
        left()
    with c2:
        right()


def summary_line(parts: list[str]):
    parts = [p for p in parts if p]
    if parts:
        st.markdown('<div class="ml-sum">' + " · ".join(parts) + "</div>", unsafe_allow_html=True)


# ======================= header =======================
upd = pd.to_datetime(summary["fetched_at"].dropna(), utc=True).max() if summary["fetched_at"].notna().any() else None
upd_txt = f"Updated {upd.tz_convert(timezone(timedelta(hours=5, minutes=30))):%d %b %Y, %H:%M} IST" if upd is not None else ""
st.markdown(f'<div class="ml-head"><div class="ml-brand">MacroLens <span>●</span></div><div class="ml-upd">{upd_txt}</div></div>'
            '<div class="ml-tag">Official macro and market data for investors and businesses, updated every morning.</div>',
            unsafe_allow_html=True)

c1, c2 = st.columns([5, 2])
with c1:
    country = st.segmented_control("Country", ["India", "United States", "Euro area", "China", "Japan", "Compare"],
                                   default="India", label_visibility="collapsed", key="country") or "India"
with c2:
    window = st.segmented_control("Chart range", list(RANGES), default="3Y", label_visibility="collapsed",
                                  key="range") or "3Y"
DAYS = RANGES[window]


# ======================= India =======================
def india():
    infl, liq, rupee = last("in_cpi_inflation"), last("in_net_liquidity"), sg.local_currency(get("inr_usd"))
    stance = sg.policy_stance(get("in_repo_rate"))
    gdp = get("in_gdp_growth")
    summary_line([
        f"<b>{stance.text}</b> (repo {last('in_repo_rate'):.2f}%)" if stance.text and has("in_repo_rate") else "",
        f"inflation {infl:.2f}%, {sg.inflation_band(infl, 2, 6, 4).text}" if infl is not None else "",
        f"{rupee.text} (₹{last('inr_usd'):.2f} per US$)" if rupee.text else "",
        sg.liquidity(liq).text,
        f"GDP growth {gdp['value'].iloc[-1]:.1f}% ({period_label(gdp['date'].iloc[-1], 'quarterly')})" if not gdp.empty else "",
    ])
    tabs = st.tabs(["Overview", "Policy rates", "Currency", "Bonds", "Liquidity", "Inflation", "Growth",
                    "External", "Fiscal", "Jobs"])
    with tabs[0]:
        legend()
        section("rates")
        cards([card("in_repo_rate", "Repo rate", "rates", signal=stance),
               card("in_sdf_rate", "SDF (floor)", "rates"), card("in_msf_rate", "MSF (ceiling)", "rates"),
               card("in_crr", "CRR", "rates")])
        section("currency")
        cards([card("inr_usd", "₹ per US$", "currency", good="down", signal=rupee),
               card("inr_eur", "₹ per €", "currency", good="down"), card("inr_gbp", "₹ per £", "currency", good="down"),
               card("inr_jpy100", "₹ per 100 ¥", "currency", good="down")])
        section("bonds")
        cards([card("in_10y", "10Y G-sec yield", "bonds", signal=sg.yield_move(get("in_10y"))),
               card("in_gsec_2y", "2Y G-sec yield", "bonds"), card("in_tbill_91d", "91-day T-bill", "bonds"),
               card("in_10y", "India − US 10Y spread", "bonds", df=diff("in_10y", "us_10y"), unit="pp_spread", derived=True)])
        section("liquidity")
        cards([card("in_wacr", "Call rate (WACR)", "liquidity"),
               card("in_net_liquidity", "Net LAF liquidity", "liquidity", signal=sg.liquidity(liq)),
               card("in_m3_yoy", "M3 growth, YoY", "liquidity"), card("in_bank_credit_yoy", "Bank credit growth, YoY", "liquidity")])
        section("inflation")
        cards([card("in_cpi_inflation", "CPI inflation", "inflation", good="down",
                    signal=sg.inflation_band(infl, 2, 6, 4)),
               card("in_food_inflation", "Food inflation", "inflation", good="down")])
        section("growth")
        g = last("in_gdp_growth")
        cards([card("in_gdp_growth", "Real GDP growth", "growth", good="up", signal=sg.growth(g, 7, 5)),
               card("in_gdp_growth_nominal", "Nominal GDP growth", "growth", good="up"),
               card("in_gdp_growth_imf_proj", imf_label(), "growth", df=get("in_gdp_growth_imf_proj").head(1))])
        section("external")
        cards([card("in_fx_reserves", "Forex reserves", "external", good="up", signal=sg.reserves(get("in_fx_reserves"))),
               card("in_total_trade_balance", "Trade balance (goods + services)", "external", good="up"),
               card("in_current_account", "Current account (monthly)", "external", good="up"),
               card("in_fdi_india_net", "FDI into India, net", "external", good="up")])
        section("fiscal")
        fd = last("in_fiscal_deficit_gdp_est")
        cards([card("in_fiscal_deficit_gdp_est", "Fiscal deficit (latest RE/BE)", "fiscal",
                    signal=sg.at_most(fd, 4.5, "the 4.5% glide path")),
               card("in_cga_fiscal_deficit_pct_target", "Deficit used so far, % of target", "fiscal"),
               card("in_gov_debt_gdp", "General govt debt (IMF)", "fiscal",
                    signal=sg.at_most(last("in_gov_debt_gdp"), 60, "the 60% FRBM anchor"))])
        section("jobs")
        cards([card("in_unemployment", "Unemployment (PLFS)", "jobs", good="down",
                    signal=sg.trend_lower_is_better(get("in_unemployment"), 180, "unemployment")),
               card("in_lfpr", "Labour force participation", "jobs", good="up")])

    with tabs[1]:
        section("rates")
        pair(lambda: chart("RBI policy corridor", [line("in_msf_rate", "MSF (ceiling)", "#B91C1C", "dot"),
                                                   line("in_repo_rate", "Repo rate", NAVY),
                                                   line("in_sdf_rate", "SDF (floor)", "#047857", "dot")], "%", ("in_repo_rate",),
                           note="History 2008-2025 from RBI Handbook Table 40; later changes from MPC releases."),
             lambda: chart("Real repo rate (repo minus CPI inflation, derived)",
                           [line("in_repo_rate", "Real repo rate", "#4338CA", df=real_repo())], "%",
                           ("in_repo_rate", "in_cpi_inflation"), hlines=[(0, "")]))
        chart("Reserve requirements: CRR and SLR", [line("in_slr", "SLR", "#1D4ED8"), line("in_crr", "CRR", SAFFRON)],
              "% of NDTL", ("in_crr",), height=260)

    with tabs[2]:
        section("currency")
        pair(lambda: chart("Rupee per US dollar", [line("inr_usd", "₹ per US$", "#7C3AED")], "₹ per US$", ("inr_usd",),
                           note="Higher = weaker rupee. Latest day from the RBI home page; history from FBIL."),
             lambda: chart("Rupee vs euro, pound, yen, dirham",
                           [line("inr_eur", "₹ per €", NAVY), line("inr_gbp", "₹ per £", SAFFRON),
                            line("inr_jpy100", "₹ per 100 ¥", "#047857"), line("inr_aed", "₹ per AED", "#B91C1C")],
                           "₹", ("inr_eur",)))

    with tabs[3]:
        section("bonds")
        pair(lambda: yield_curves(),
             lambda: chart("India G-sec yields over time", [line("in_gsec_1y", "1Y", "#94A3B8"), line("in_gsec_5y", "5Y", SAFFRON),
                                                            line("in_10y", "10Y", NAVY), line("in_gsec_30y", "30Y", "#7C3AED")],
                           "%", ("in_10y",)))
        pair(lambda: chart("India − US 10Y spread (derived)", [line("in_10y", "Spread", "#1D4ED8", df=diff("in_10y", "us_10y"))],
                           "pp", ("in_10y", "us_10y")),
             lambda: chart("Short end: T-bills and CDs", [line("in_tbill_91d", "91-day T-bill", NAVY),
                                                          line("in_tbill_364d", "364-day T-bill", SAFFRON),
                                                          line("in_cd_3m", "3-month CD", "#B91C1C")], "%", ("in_tbill_91d",)))

    with tabs[4]:
        section("liquidity")
        pair(lambda: chart("Overnight rates inside the RBI corridor",
                           [line("in_msf_rate", "MSF", "#B91C1C", "dot"), line("in_repo_rate", "Repo", NAVY),
                            line("in_sdf_rate", "SDF", "#047857", "dot"), line("in_wacr", "Call rate (WACR)", SAFFRON),
                            line("in_treps_rate", "TREPS", "#7C3AED"), line("in_mibor_overnight", "Overnight MIBOR", "#0F766E")],
                           "%", ("in_wacr",), note="Above repo = tight liquidity; near the SDF floor = surplus."),
             lambda: chart("Net liquidity in the banking system", [
                 line("in_net_liquidity", "Net LAF (+ injected / − absorbed)", "#0F766E", kind="bar"),
                 line("in_net_durable_liquidity", "Net durable liquidity", NAVY)], "₹ crore", ("in_net_liquidity",),
                 hlines=[(0, "")]))
        chart("Money and credit growth, YoY", [line("in_m3_yoy", "M3", NAVY), line("in_bank_credit_yoy", "Bank credit", SAFFRON),
                                               line("in_deposits_yoy", "Deposits", "#047857")], "% YoY", ("in_m3_yoy",), height=270)

    with tabs[5]:
        section("inflation")
        chart("CPI inflation with RBI's 2–6% band", [line("in_cpi_inflation", "Headline (2024 base)", "#B91C1C"),
                                                     line("in_cpi_inflation_back", "Headline (official back series)", "#94A3B8", "dot"),
                                                     line("in_food_inflation", "Food and beverages", SAFFRON)],
              "% YoY", ("in_cpi_inflation",), band=(2, 6), hlines=[(4, "4% target")], height=340,
              note="Live and back series are separate lines, never joined.")

    with tabs[6]:
        section("growth")
        pair(lambda: chart("GDP growth, YoY (2022-23 base)", [line("in_gdp_growth", "Real", "#047857", kind="bar"),
                                                              line("in_gdp_growth_nominal", "Nominal", "#A7D7C5", kind="bar")],
                           "% YoY", ("in_gdp_growth",), note="Quarters of India's fiscal year (Q1 = Apr–Jun)."),
             lambda: chart("IMF real GDP growth projection", [line("in_gdp_growth_imf_proj", "India", "#047857")], "%",
                           ("in_gdp_growth_imf_proj",)))
        gdp_mix()
        pair(lambda: chart("GNI per capita, Atlas (US$)", [line("in_gni_pc", "India", SAFFRON)], "US$", ("in_gni_pc",)),
             lambda: chart("Investment (GFCF), % of GDP", [line("in_gfcf_gdp", "India", SAFFRON)], "% of GDP", ("in_gfcf_gdp",)))

    with tabs[7]:
        section("external")
        pair(lambda: chart("Foreign exchange reserves", [line("in_fx_reserves", "Total", "#B45309", scale=1e-3),
                                                         line("in_fx_fca", "Foreign currency assets", NAVY, scale=1e-3),
                                                         line("in_fx_gold", "Gold", "#D4AC0D", scale=1e-3)], "US$ bn", ("in_fx_reserves",)),
             lambda: chart("Monthly trade, goods and services", [line("in_total_exports", "Exports", "#047857"),
                                                                 line("in_total_imports", "Imports", "#B91C1C"),
                                                                 line("in_total_trade_balance", "Balance", "#94A3B8", kind="bar")],
                           "US$ bn", ("in_total_exports",)))
        pair(lambda: chart("Balance of payments: current account and capital flows",
                           [line("in_current_account", "Current account", "#B45309", kind="bar"),
                            line("in_fdi_net", "Net FDI", NAVY, kind="bar"), line("in_fpi_net", "Net FPI", "#7C3AED", kind="bar")],
                           "US$ bn", ("in_current_account",)),
             lambda: chart("FDI net inflows, annual", [line("in_fdi_inflows", "India", "#B45309", scale=1e-9)], "US$ bn",
                           ("in_fdi_inflows",)))

    with tabs[8]:
        section("fiscal")
        pair(lambda: chart("Union Budget deficits, % of GDP", [line("in_fiscal_deficit_gdp", "Fiscal deficit (actual)", NAVY, kind="bar"),
                                                              line("in_fiscal_deficit_gdp_est", "Fiscal deficit (RE/BE)", "#94A3B8", kind="bar"),
                                                              line("in_primary_deficit_gdp", "Primary deficit", SAFFRON)],
                           "% of GDP", ("in_fiscal_deficit_gdp",), hlines=[(4.5, "4.5% glide path")]),
             lambda: chart("Fiscal deficit used so far this year, % of target (CGA)",
                           [line("in_cga_fiscal_deficit_pct_target", "% of target", "#334155", kind="bar")], "%",
                           ("in_cga_fiscal_deficit_pct_target",)))
        pair(lambda: chart("Capex vs interest payments (₹ lakh crore)", [
                 line("in_capex_cr", "Capex (actual)", "#047857", kind="bar", scale=1e-5),
                 line("in_capex_cr_est", "Capex (RE/BE)", "#A7D7C5", kind="bar", scale=1e-5),
                 line("in_interest_cr", "Interest (actual)", "#B91C1C", scale=1e-5),
                 line("in_interest_cr_est", "Interest (RE/BE)", "#B91C1C", "dot", scale=1e-5)], "₹ lakh crore", ("in_capex_cr",)),
             lambda: chart("General government debt, % of GDP (IMF)", [line("in_gov_debt_gdp", "India", NAVY),
                                                                         line("in_gov_debt_gdp_proj", "IMF projection", NAVY, "dot")],
                           "% of GDP", ("in_gov_debt_gdp",), hlines=[(60, "60% FRBM anchor")]))

    with tabs[9]:
        section("jobs")
        pair(lambda: chart("PLFS monthly", [line("in_lfpr", "LFPR", NAVY), line("in_wpr", "Worker population ratio", "#047857"),
                                            line("in_unemployment", "Unemployment rate", "#BE185D")], "%", ("in_unemployment",)),
             lambda: chart("Participation by gender (ILO modelled)", [line("in_lfpr_male_ilo", "Male", NAVY),
                                                                      line("in_lfpr_female_ilo", "Female", "#BE185D")],
                           "% of population 15+", ("in_lfpr_female_ilo",)))


def imf_label() -> str:
    """'IMF projection, FY 2026-27' from the first projected year (IMF India data are fiscal years)."""
    p = get("in_gdp_growth_imf_proj")
    if p.empty:
        return "IMF projection"
    y = p["date"].iloc[0].year
    return f"IMF projection, FY {y}-{str(y + 1)[-2:]}"


def real_repo() -> pd.DataFrame:
    if not (has("in_repo_rate") and has("in_cpi_inflation")):
        return EMPTY
    infl = pd.concat([get("in_cpi_inflation_back"), get("in_cpi_inflation")]).sort_values("date")
    repo = get("in_repo_rate").set_index("date")["value"]
    out = [(r["date"], repo[repo.index <= r["date"] + pd.offsets.MonthEnd(0)].iloc[-1] - r["value"])
           for _, r in infl.iterrows() if not repo[repo.index <= r["date"] + pd.offsets.MonthEnd(0)].empty]
    return pd.DataFrame(out, columns=["date", "value"])


def yield_curves():
    st.markdown("**Yield curves today**")
    fig = go.Figure()
    for label, pts, color in [("India G-sec", [(1, "in_gsec_1y"), (2, "in_gsec_2y"), (5, "in_gsec_5y"), (10, "in_10y"),
                                                (30, "in_gsec_30y")], SAFFRON),
                              ("US Treasury", [(0.25, "us_3m"), (2, "us_2y"), (10, "us_10y"), (30, "us_30y")], "#1D4ED8")]:
        xs = [(t, last(i)) for t, i in pts if has(i)]
        if xs:
            fig.add_trace(go.Scatter(x=[x for x, _ in xs], y=[y for _, y in xs], mode="lines+markers", name=label,
                                     line=dict(color=color, width=2.4)))
    fig.update_layout(height=300, margin=dict(l=8, r=8, t=34, b=8), xaxis_title="maturity (years)", yaxis_title="%",
                      legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0), plot_bgcolor="#FFFFFF",
                      paper_bgcolor="#FFFFFF", font=dict(color=INK, size=12))
    fig.update_yaxes(gridcolor="#EEF1F5")
    st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
    st.markdown('<div class="ml-cap">Source: FBIL par yields (India), FRED (US)</div>', unsafe_allow_html=True)


def gdp_mix():
    parts = {"Private consumption (C)": "in_pfce_real", "Government consumption (G)": "in_gfce_real",
             "Fixed investment (I)": "in_gfcf_real", "Change in stocks": "in_change_stock_real",
             "Valuables": "in_valuables_real", "Exports (X)": "in_exports_real", "Imports (M)": "in_imports_real"}
    if not has("in_gdp_real"):
        return
    real = get("in_gdp_real").set_index("date")["value"]
    shares = pd.DataFrame({k: get(i).set_index("date")["value"] / real * 100 * (-1 if i == "in_imports_real" else 1)
                           for k, i in parts.items() if has(i)}).dropna(how="all")
    st.markdown("**How India's GDP is spent: Y = C + I + G + (X − M), % of real GDP (derived)**")
    fig = go.Figure([go.Bar(x=shares.index, y=shares[c], name=c, marker_color=col) for c, col in
                     zip(shares.columns, [SAFFRON, NAVY, "#047857", "#7C3AED", "#D4AC0D", "#0F766E", "#B91C1C"])])
    fig.update_layout(barmode="relative", height=340, margin=dict(l=8, r=8, t=34, b=8), yaxis_title="% of real GDP",
                      legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0), plot_bgcolor="#FFFFFF",
                      paper_bgcolor="#FFFFFF", font=dict(color=INK, size=12))
    fig.update_yaxes(gridcolor="#EEF1F5")
    st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
    st.markdown('<div class="ml-cap">Source: MoSPI national accounts. Imports shown as negative.</div>', unsafe_allow_html=True)


# ======================= other countries =======================
def united_states():
    cpi, core = yoy("us_cpi"), yoy("us_core_pce")
    stance = sg.policy_stance(get("us_policy_rate"), "Fed")
    summary_line([f"<b>{stance.text}</b> (target {last('us_policy_rate') - 0.25:.2f}–{last('us_policy_rate'):.2f}%)"
                  if stance.text and has("us_policy_rate") else "",
                  f"CPI inflation {cpi['value'].iloc[-1]:.1f}% (derived), {sg.inflation_target(cpi['value'].iloc[-1]).text}"
                  if not cpi.empty else "",
                  f"10Y Treasury {last('us_10y'):.2f}%" if has("us_10y") else "",
                  f"unemployment {last('us_unemployment'):.1f}%" if has("us_unemployment") else ""])
    tabs = st.tabs(["Overview", "Rates and bonds", "Liquidity", "Inflation", "Growth and jobs", "Fiscal"])
    with tabs[0]:
        legend()
        section("rates")
        cards([card("us_policy_rate", "Fed funds target (upper)", "rates", signal=stance),
               card("us_fed_funds_effective", "Fed funds effective", "rates"),
               card("us_dollar_broad", "Dollar index (broad)", "currency")])
        section("bonds")
        cards([card("us_10y", "10Y Treasury", "bonds", signal=sg.yield_move(get("us_10y"))), card("us_2y", "2Y Treasury", "bonds"),
               card("us_10y", "10Y − 2Y slope", "bonds", df=diff("us_10y", "us_2y"), unit="pp_spread", derived=True),
               card("us_10y_real", "10Y real yield (TIPS)", "bonds")])
        section("inflation")
        cards([card("us_cpi", "CPI inflation", "inflation", df=cpi, derived=True, good="down",
                    signal=sg.inflation_target(cpi["value"].iloc[-1]) if not cpi.empty else None),
               card("us_core_pce", "Core PCE inflation", "inflation", df=core, derived=True, good="down",
                    signal=sg.inflation_target(core["value"].iloc[-1]) if not core.empty else None)])
        section("growth")
        cards([card("us_gdp_growth", "Real GDP growth (q/q SAAR)", "growth", good="up", signal=sg.growth(last("us_gdp_growth"), 2, 0)),
               card("us_unemployment", "Unemployment", "jobs", good="down",
                    signal=sg.trend_lower_is_better(get("us_unemployment"), 180, "unemployment")),
               card("us_gov_debt_gdp", "General govt debt (IMF)", "fiscal")])
    with tabs[1]:
        section("bonds")
        pair(lambda: chart("Fed funds: target and effective", [line("us_policy_rate", "Target (upper)", NAVY),
                                                              line("us_fed_funds_effective", "Effective", "#1D4ED8", "dot")], "%",
                           ("us_policy_rate",)),
             lambda: chart("Treasury yields", [line("us_3m", "3M", "#94A3B8"), line("us_2y", "2Y", SAFFRON),
                                               line("us_10y", "10Y", NAVY), line("us_30y", "30Y", "#7C3AED")], "%", ("us_10y",)))
    with tabs[2]:
        section("liquidity")
        pair(lambda: chart("Fed balance sheet and bank reserves", [line("us_fed_balance_sheet", "Fed total assets", NAVY, scale=1e-3),
                                                                  line("us_bank_reserves", "Bank reserves", "#0F766E", scale=1e-3)],
                           "US$ bn", ("us_fed_balance_sheet",)),
             lambda: chart("Overnight reverse repo usage", [line("us_reverse_repo", "ON RRP", "#0F766E")], "US$ bn",
                           ("us_reverse_repo",)))
    with tabs[3]:
        section("inflation")
        chart("CPI, core CPI and core PCE (derived YoY)", [line("us_cpi", "CPI", "#B91C1C", df=cpi),
                                                         line("us_core_cpi", "Core CPI", SAFFRON, df=yoy("us_core_cpi")),
                                                         line("us_core_pce", "Core PCE", NAVY, df=core)], "% YoY",
              ("us_cpi", "us_core_pce"), hlines=[(2, "2% target")], height=330)
    with tabs[4]:
        section("growth")
        pair(lambda: chart("Real GDP growth (q/q annualised)", [line("us_gdp_growth", "US", "#047857", kind="bar")], "%",
                           ("us_gdp_growth",)),
             lambda: chart("Unemployment and participation", [line("us_unemployment", "Unemployment", "#BE185D"),
                                                             line("us_lfpr", "Participation", NAVY)], "%", ("us_unemployment",)))
    with tabs[5]:
        section("fiscal")
        pair(lambda: chart("Federal debt, % of GDP (quarterly)", [line("us_federal_debt_gdp", "Federal debt", "#334155")],
                           "% of GDP", ("us_federal_debt_gdp",)),
             lambda: chart("General government fiscal balance (IMF)", [line("us_gov_balance_gdp", "US", "#334155")],
                           "% of GDP", ("us_gov_balance_gdp",), hlines=[(0, "")]))


def euro_area():
    hicp = yoy("ea_hicp")
    gdp = yoy("ea_gdp_real", 4)
    stance = sg.policy_stance(get("ea_ecb_deposit_rate"), "ECB")
    summary_line([f"<b>{stance.text}</b> (deposit rate {last('ea_ecb_deposit_rate'):.2f}%)" if stance.text else "",
                  f"HICP inflation {hicp['value'].iloc[-1]:.1f}% (derived), {sg.inflation_target(hicp['value'].iloc[-1]).text}"
                  if not hicp.empty else "",
                  f"German 10Y {last('de_10y'):.2f}%" if has("de_10y") else ""])
    legend()
    section("rates")
    cards([card("ea_ecb_deposit_rate", "ECB deposit rate", "rates", signal=stance), card("ea_ecb_mro_rate", "ECB refi rate", "rates"),
           card("usd_eur", "US$ per €", "currency"), card("de_10y", "Germany 10Y", "bonds")])
    section("inflation")
    cards([card("ea_hicp", "HICP inflation", "inflation", df=hicp, derived=True, good="down",
                signal=sg.inflation_target(hicp["value"].iloc[-1]) if not hicp.empty else None),
           card("ea_gdp_real", "Real GDP growth, YoY", "growth", df=gdp, derived=True, good="up",
                signal=sg.growth(gdp["value"].iloc[-1], 1.5, 0) if not gdp.empty else None)])
    pair(lambda: chart("ECB policy rates", [line("ea_ecb_deposit_rate", "Deposit rate", "#047857"),
                                            line("ea_ecb_mro_rate", "Refi rate", NAVY, "dot")], "%", ("ea_ecb_deposit_rate",)),
         lambda: chart("HICP inflation (derived YoY)", [line("ea_hicp", "Euro area", "#B91C1C", df=hicp)], "% YoY",
                       ("ea_hicp",), hlines=[(2, "2% target")]))
    pair(lambda: chart("Real GDP growth, YoY (derived)", [line("ea_gdp_real", "Euro area", "#047857", df=gdp, kind="bar")],
                       "% YoY", ("ea_gdp_real",)),
         lambda: chart("EUR/USD", [line("usd_eur", "US$ per €", "#7C3AED")], "US$ per €", ("usd_eur",)))


def china():
    cg = last("cn_gdp_growth")
    summary_line([f"GDP growth {cg:.1f}% (IMF, annual)" if cg is not None else "",
                  f"inflation {last('cn_inflation'):.1f}% (IMF, annual)" if has("cn_inflation") else "",
                  f"¥{last('cny_usd'):.4f} per US$" if has("cny_usd") else ""])
    legend()
    section("growth")
    cards([card("cn_gdp_growth", "Real GDP growth", "growth", good="up", signal=sg.growth(cg, 5, 3)),
           card("cn_inflation", "CPI inflation", "inflation"), card("cny_usd", "CNY per US$", "currency"),
           card("cn_gov_debt_gdp", "General govt debt (IMF)", "fiscal"),
           card("cn_unemployment_ilo", "Unemployment (ILO)", "jobs")])
    pair(lambda: chart("Real GDP growth (IMF)", [line("cn_gdp_growth", "Actual/estimate", "#B91C1C", kind="bar"),
                                                 line("cn_gdp_growth_imf_proj", "IMF projection", "#F3A5A5", kind="bar")],
                       "%", ("cn_gdp_growth",)),
         lambda: chart("Yuan per US dollar", [line("cny_usd", "CNY per US$", "#7C3AED")], "CNY per US$", ("cny_usd",)))
    pair(lambda: chart("Government debt and fiscal balance, % of GDP (IMF)", [line("cn_gov_debt_gdp", "Debt", "#334155"),
                                                                              line("cn_gov_balance_gdp", "Fiscal balance", "#B91C1C")],
                       "% of GDP", ("cn_gov_debt_gdp",)),
         lambda: chart("GNI per capita vs India (US$)", [line("cn_gni_pc", "China", "#B91C1C"), line("in_gni_pc", "India", SAFFRON)],
                       "US$", ("cn_gni_pc",)))
    st.markdown('<div class="ml-cap">China monthly CPI is not used: no current official source we can fetch automatically '
                '(FRED\'s copy stopped in 2025). Annual IMF figures are shown instead.</div>', unsafe_allow_html=True)


def japan():
    jg = last("jp_gdp_growth")
    summary_line([f"10Y JGB {last('jp_10y'):.2f}%" if has("jp_10y") else "",
                  f"¥{last('usd_jpy'):.2f} per US$" if has("usd_jpy") else "",
                  f"unemployment {last('jp_unemployment'):.1f}%" if has("jp_unemployment") else "",
                  f"inflation {last('jp_inflation'):.1f}% (IMF, annual)" if has("jp_inflation") else ""])
    legend()
    jgdp = yoy("jp_gdp_real", 4)
    cards([card("jp_10y", "10Y JGB yield", "bonds", signal=sg.yield_move(get("jp_10y"), 60)),
           card("usd_jpy", "¥ per US$", "currency", signal=sg.local_currency(get("usd_jpy"), "yen", 30)),
           card("jp_gdp_real", "Real GDP growth, YoY", "growth", df=jgdp, derived=True, good="up",
                signal=sg.growth(jgdp["value"].iloc[-1], 1, 0) if not jgdp.empty else None),
           card("jp_inflation", "CPI inflation (IMF)", "inflation", signal=sg.inflation_target(last("jp_inflation"))),
           card("jp_unemployment", "Unemployment", "jobs", good="down"),
           card("jp_gov_debt_gdp", "General govt debt (IMF)", "fiscal")])
    pair(lambda: chart("10Y JGB and 3-month rate", [line("jp_10y", "10Y JGB", "#7C3AED"), line("jp_3m", "3-month interbank", NAVY)],
                       "%", ("jp_10y",)),
         lambda: chart("Yen per US dollar", [line("usd_jpy", "¥ per US$", "#7C3AED")], "¥ per US$", ("usd_jpy",)))
    pair(lambda: chart("Real GDP growth, YoY (derived)", [line("jp_gdp_real", "Japan", "#047857", df=jgdp, kind="bar")], "% YoY",
                       ("jp_gdp_real",)),
         lambda: chart("Government debt, % of GDP (IMF)", [line("jp_gov_debt_gdp", "Japan", "#334155")], "% of GDP",
                       ("jp_gov_debt_gdp",)))
    st.markdown('<div class="ml-cap">The Bank of Japan policy rate is not shown: no current official series we can fetch '
                'automatically.</div>', unsafe_allow_html=True)


def compare():
    legend()
    pair(lambda: chart("Policy rates", [line("in_repo_rate", "RBI repo", SAFFRON), line("us_policy_rate", "Fed (upper)", "#1D4ED8"),
                                        line("ea_ecb_deposit_rate", "ECB deposit", "#047857")], "%",
                       ("in_repo_rate", "us_policy_rate", "ea_ecb_deposit_rate")),
         lambda: chart("10-year government bond yields", [line("in_10y", "India", SAFFRON), line("us_10y", "US", "#1D4ED8"),
                                                          line("de_10y", "Germany", "#047857"), line("jp_10y", "Japan", "#7C3AED")],
                       "%", ("in_10y", "us_10y", "de_10y", "jp_10y")))
    pair(lambda: chart("Headline inflation", [line("in_cpi_inflation", "India", SAFFRON),
                                              line("in_cpi_inflation_back", "India back series", SAFFRON, "dot"),
                                              line("us_cpi", "US (derived)", "#1D4ED8", df=yoy("us_cpi")),
                                              line("ea_hicp", "Euro area (derived)", "#047857", df=yoy("ea_hicp"))],
                       "% YoY", ("in_cpi_inflation", "us_cpi", "ea_hicp")),
         lambda: chart("Real GDP growth outlook (IMF projections)", [line("in_gdp_growth_imf_proj", "India", SAFFRON),
                                                                     line("us_gdp_growth_imf_proj", "US", "#1D4ED8"),
                                                                     line("cn_gdp_growth_imf_proj", "China", "#B91C1C"),
                                                                     line("jp_gdp_growth_imf_proj", "Japan", "#7C3AED")],
                       "%", ("in_gdp_growth_imf_proj",)))
    pair(lambda: chart("General government debt, % of GDP (IMF)", [line("in_gov_debt_gdp", "India", SAFFRON),
                                                                   line("us_gov_debt_gdp", "US", "#1D4ED8"),
                                                                   line("cn_gov_debt_gdp", "China", "#B91C1C"),
                                                                   line("jp_gov_debt_gdp", "Japan", "#7C3AED")],
                       "% of GDP", ("in_gov_debt_gdp",)),
         lambda: chart("Unemployment", [line("in_unemployment_ilo", "India (ILO)", SAFFRON), line("us_unemployment", "US", "#1D4ED8"),
                                        line("cn_unemployment_ilo", "China (ILO)", "#B91C1C"),
                                        line("jp_unemployment", "Japan", "#7C3AED")], "%", ("in_unemployment_ilo",)))
    chart("Brent crude", [line("brent", "Brent", "#92400E")], "US$ per barrel", ("brent",), height=260,
          note="India imports most of its oil, so oil prices feed into inflation, the current account and the rupee.")


VIEWS = {"India": india, "United States": united_states, "Euro area": euro_area, "China": china, "Japan": japan,
         "Compare": compare}
VIEWS[country]()

# ======================= data footer =======================
st.divider()
with st.expander("About the data: sources, quality checks and downloads"):
    st.markdown(f"{summary['date'].notna().sum()} series from RBI, MoSPI, FBIL, Union Budget, CGA, Ministry of Commerce, "
                "FRED, IMF and the World Bank, fetched automatically every morning. FBIL market data (bond yields, "
                "T-bills, MIBOR) reaches the public with about a one-week lag; the latest rupee rates come from the "
                "RBI home page. Derived values (YoY %, spreads, shares, real rate) are computed by MacroLens and labelled.")
    q = quality(stamp)
    st.markdown(f"**Quality checks:** {int((q['severity'] == 'error').sum())} errors, {int((q['severity'] == 'warn').sum())} "
                "warnings (a warning usually marks a real market event).")
    if not q.empty:
        st.dataframe(q, use_container_width=True, hide_index=True)
    table = summary[["indicator_id", "name", "topic", "country", "value", "unit", "date", "frequency", "source",
                     "source_url", "fetched_at"]]
    st.dataframe(table, use_container_width=True, hide_index=True,
                 column_config={"source_url": st.column_config.LinkColumn("source link")})
    pick = st.selectbox("Download one series", summary["indicator_id"], format_func=lambda i: f"{i} — {ROWS.loc[i, 'name']}")
    st.download_button("Download CSV", get(pick).to_csv(index=False).encode("utf-8"), file_name=f"{pick}.csv", mime="text/csv")
st.caption("Data from the official sources linked on each chart; figures may be revised by the source.")
