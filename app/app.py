"""MacroLens dashboard (Streamlit).

Run:  streamlit run app/app.py
Reads data/clean/*.parquet through storage/db.py (DuckDB).
Tabs are ordered by what investors and business decision-makers check first:
policy rates, currency, bonds, liquidity, inflation, growth, external, fiscal, jobs, commodities.
Charts skip series that are not registered or have no data yet.
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

DATA_NOTE = "Data from the official sources linked on each chart; figures may be revised by the source."
COUNTRY_NAMES = {"IN": "India", "US": "United States", "EA": "Euro area", "CN": "China", "GLOBAL": "Global"}
COLORS = {"IN": "#E07B39", "US": "#3B6FB6", "EA": "#2E8B57", "CN": "#C0392B", "GLOBAL": "#7F8C8D"}
EXTRA = ["#8E5EA2", "#D4AC0D", "#16A085", "#C0392B", "#5D6D7E", "#AF601A"]
GREY = "#999999"
RANGES = {"1Y": 365, "3Y": 3 * 365, "5Y": 5 * 365, "10Y": 10 * 365, "Max": None}

st.set_page_config(page_title="MacroLens", page_icon="📈", layout="wide")
st.markdown("<style>[data-testid='stMetricValue']{font-size:1.45rem}"
            "[data-testid='stMetricLabel'] p{font-size:0.85rem}</style>", unsafe_allow_html=True)


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


def has(iid: str) -> bool:
    return iid in ROWS.index and iid in S and not S[iid].empty


def get(iid: str) -> pd.DataFrame:
    return S.get(iid, pd.DataFrame(columns=["date", "value"]))


# ======================= formatting =======================
def fmt_value(v, unit):
    if pd.isna(v):
        return "–"
    if unit == "inr_crore":
        return f"₹{v / 1e5:,.2f} lakh cr" if abs(v) >= 1e5 else f"₹{v:,.0f} cr"
    if unit == "usd_million":
        return f"${v / 1e3:,.1f} bn" if abs(v) >= 1e3 else f"${v:,.0f} mn"
    if unit == "eur_million":
        return f"€{v / 1e6:,.2f} tn"
    if unit == "usd":
        return f"${v / 1e9:,.1f} bn" if abs(v) >= 1e9 else f"${v:,.0f}"
    return {"percent": f"{v:.2f}%", "percent_of_gdp": f"{v:.1f}% of GDP", "inr_per_usd": f"₹{v:,.2f}",
            "inr": f"₹{v:,.2f}", "usd_per_barrel": f"${v:,.2f}/bbl", "usd_billion": f"${v:,.1f} bn",
            "usd_per_eur": f"${v:,.4f}", "cny": f"¥{v:,.4f}"}.get(unit, f"{v:,.2f}")


def fmt_change(row):
    if pd.isna(row["prev_value"]) or pd.isna(row["value"]):
        return None
    d = row["value"] - row["prev_value"]
    if row["unit"] == "percent":
        return f"{d * 100:+.0f} bp"
    if row["unit"] == "percent_of_gdp":
        return f"{d:+.1f} pp"
    if row["unit"] in ("inr_crore", "usd_million", "usd_billion"):
        return fmt_value(d, row["unit"]).replace("₹-", "-₹").replace("$-", "-$")
    return f"{d / abs(row['prev_value']) * 100:+.2f}%" if row["prev_value"] else None


def period_label(ts, frequency) -> str:
    ts = pd.Timestamp(ts)
    if frequency == "annual":
        return str(ts.year)
    if frequency == "quarterly":
        return f"{ts:%b}–{ts + pd.DateOffset(months=2):%b %Y}"
    if frequency == "monthly":
        return f"{ts:%b %Y}"
    return f"{ts:%d %b %Y}"


UNIT_LABEL = {"percent": "%", "percent_of_gdp": "% of GDP", "index": "index", "inr_per_usd": "₹ per US$",
              "inr": "₹", "usd_per_barrel": "US$ per barrel", "inr_crore": "₹ crore", "usd": "US$",
              "usd_million": "US$ million", "usd_billion": "US$ billion", "usd_per_eur": "US$ per €",
              "cny": "CNY per US$", "eur_million": "€ million"}


# ======================= sidebar =======================
st.title("MacroLens")
st.caption("India, US, euro area and China: policy rates, currency, bonds, liquidity, inflation, growth, "
           "external sector and public finances, from official sources, updated automatically every day.")
with st.sidebar:
    st.header("View")
    window = st.radio("Chart range (daily, weekly, monthly data)", list(RANGES), index=1, horizontal=True)
    st.caption("Quarterly and annual charts always show their full history.")
    st.divider()
    if summary["fetched_at"].notna().any():
        st.caption(f"Data last updated: {pd.to_datetime(summary['fetched_at'].dropna()).max():%d %b %Y}")
    st.caption(f"{summary['date'].notna().sum()} series · RBI, MoSPI, FBIL, Union Budget, CGA, Ministry of "
               "Commerce, FRED, IMF, World Bank.")
    st.caption("FBIL market data (India bond yields, T-bills, MIBOR, INR reference rates) is published to the "
               "public with about a one-week lag.")
DAYS = RANGES[window]


# ======================= chart helpers =======================
def clip(df: pd.DataFrame, frequency: str) -> pd.DataFrame:
    if DAYS is None or df.empty or frequency in ("quarterly", "annual"):
        return df
    return df[df["date"] >= pd.Timestamp(date.today()) - pd.Timedelta(days=DAYS)]


def steps_to_today(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    tail = pd.DataFrame({"date": [pd.Timestamp(date.today())], "value": [df["value"].iloc[-1]]})
    return pd.concat([df, tail], ignore_index=True)


def yoy(iid: str, periods: int = 12) -> pd.DataFrame:
    return yoy_pct(get(iid), periods) if has(iid) else pd.DataFrame(columns=["date", "value"])


def trace(iid: str, label: str | None = None, color: str | None = None, dash: str | None = None,
          df: pd.DataFrame | None = None, kind: str = "line", scale: float = 1.0) -> dict | None:
    """A chart line for a stored series (or a derived df). None if the series is not available."""
    if iid not in ROWS.index:
        return None
    row = ROWS.loc[iid]
    data = get(iid) if df is None else df
    if data.empty:
        return None
    data = data.assign(value=data["value"] * scale)
    shape = "linear"
    if row["frequency"] == "event":
        data, shape = steps_to_today(data), "hv"
    return {"df": clip(data, row["frequency"]), "name": label or row["name"], "kind": kind,
            "color": color or COLORS.get(row["country"]), "dash": dash, "shape": shape}


def chart(traces: list, unit_label: str, height: int = 320, band=None, hlines=(), barmode="group"):
    traces = [t for t in traces if t is not None and not t["df"].empty]
    if not traces:
        st.info("Data for this chart is not available yet.")
        return
    fig = go.Figure()
    if band:
        fig.add_hrect(y0=band[0], y1=band[1], fillcolor="#5B8C5A", opacity=0.10, line_width=0)
    for t in traces:
        if t["kind"] == "bar":
            fig.add_trace(go.Bar(x=t["df"]["date"], y=t["df"]["value"], name=t["name"], marker_color=t["color"]))
        else:
            fig.add_trace(go.Scatter(x=t["df"]["date"], y=t["df"]["value"], name=t["name"], mode="lines",
                                     line=dict(color=t["color"], width=2, shape=t["shape"], dash=t["dash"])))
    for y, text in hlines:
        fig.add_hline(y=y, line_dash="dash", line_color=GREY, annotation_text=text, annotation_position="top left")
    many = len(traces) > 1
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=40 if many else 10, b=10), yaxis_title=unit_label,
                      showlegend=many, legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0),
                      hovermode="x unified", barmode=barmode)
    values = pd.concat([t["df"]["value"] for t in traces])
    if values.max() - values.min() < 1e-9:
        fig.update_yaxes(range=[values.min() - 1, values.max() + 1])
    st.plotly_chart(fig, use_container_width=True)


def sources(*iids: str, extra: str = ""):
    iids = [i for i in iids if i in ROWS.index]
    if not iids:
        return
    seen, parts = set(), []
    for iid in iids:
        row = ROWS.loc[iid]
        if (row["source"], row["source_url"]) not in seen:
            seen.add((row["source"], row["source_url"]))
            parts.append(f"[{row['source']}]({row['source_url']})")
    latest = [period_label(ROWS.loc[i, "date"], ROWS.loc[i, "frequency"]) for i in iids if pd.notna(ROWS.loc[i, "date"])]
    notes = [ROWS.loc[i, "note"] for i in iids if isinstance(ROWS.loc[i, "note"], str)]
    text = "Source: " + ", ".join(parts) + (" · latest " + ", ".join(dict.fromkeys(latest)) if latest else "")
    st.caption(" ".join([text] + list(dict.fromkeys(notes)) + ([extra] if extra else [])))


def card(iid: str, label: str, value_df: pd.DataFrame | None = None, derived: bool = False):
    if iid not in ROWS.index:
        return
    row = ROWS.loc[iid]
    if value_df is not None:
        if value_df.empty:
            return
        v = value_df["value"].iloc[-1]
        delta = (v - value_df["value"].iloc[-2]) * 100 if len(value_df) > 1 else None
        st.metric(label + (" (derived)" if derived else ""), f"{v:.2f}%",
                  f"{delta:+.0f} bp" if delta is not None else None, delta_color="off", help=row["name"])
        when = period_label(value_df["date"].iloc[-1], row["frequency"])
    else:
        if pd.isna(row["value"]):
            return
        st.metric(label, fmt_value(row["value"], row["unit"]), fmt_change(row), delta_color="off", help=row["name"])
        when = period_label(row["date"], row["frequency"])
    st.caption(f"{when} · [{row['source']}]({row['source_url']})")


def cards(specs: list[tuple]):
    specs = [s for s in specs if s[0] in ROWS.index]
    if not specs:
        return
    cols = st.columns(max(len(specs), 4))
    for col, spec in zip(cols, specs):
        with col:
            card(*spec)


def two(left, right):
    c1, c2 = st.columns(2)
    with c1:
        left()
    with c2:
        right()


def block(title: str, traces: list, unit: str, src: tuple, extra: str = "", **kw):
    def draw():
        st.markdown(f"**{title}**")
        chart(traces, unit, **kw)
        sources(*src, extra=extra)
    return draw


def merge_diff(a: str, b: str) -> pd.DataFrame:
    """a - b on common dates (derived)."""
    if not (has(a) and has(b)):
        return pd.DataFrame(columns=["date", "value"])
    m = get(a).merge(get(b), on="date", suffixes=("_a", "_b"))
    return pd.DataFrame({"date": m["date"], "value": m["value_a"] - m["value_b"]})


def real_rate() -> pd.DataFrame:
    """Repo rate minus latest CPI inflation, monthly (derived)."""
    if not (has("in_repo_rate") and has("in_cpi_inflation")):
        return pd.DataFrame(columns=["date", "value"])
    infl = pd.concat([get("in_cpi_inflation_back"), get("in_cpi_inflation")]) if has("in_cpi_inflation_back") \
        else get("in_cpi_inflation")
    repo = get("in_repo_rate").set_index("date")["value"]
    out = []
    for _, r in infl.sort_values("date").iterrows():
        month_end = r["date"] + pd.offsets.MonthEnd(0)
        rr = repo[repo.index <= month_end]
        if not rr.empty:
            out.append((r["date"], rr.iloc[-1] - r["value"]))
    return pd.DataFrame(out, columns=["date", "value"])


# derived series used in several places
DER = {
    "us_cpi_yoy": yoy("us_cpi"), "us_core_yoy": yoy("us_core_cpi"), "us_core_pce_yoy": yoy("us_core_pce"),
    "ea_hicp_yoy": yoy("ea_hicp"), "ea_gdp_yoy": yoy("ea_gdp_real", 4),
    "in_us_10y": merge_diff("in_10y", "us_10y"), "us_10y_2y": merge_diff("us_10y", "us_2y"),
    "in_10y_1y": merge_diff("in_10y", "in_gsec_1y"), "in_real_repo": real_rate(),
}

TABS = ["Overview", "Policy rates", "Currency", "Bonds", "Liquidity", "Inflation", "Growth", "External",
        "Fiscal", "Jobs", "Commodities", "Data quality", "Data & sources"]
tabs = dict(zip(TABS, st.tabs(TABS)))

# ======================= Overview =======================
with tabs["Overview"]:
    st.markdown("##### Policy rates · currency · bonds")
    cards([("in_repo_rate", "RBI repo rate"), ("us_policy_rate", "Fed funds (upper)"),
           ("ea_ecb_deposit_rate", "ECB deposit rate"), ("inr_usd", "₹ per US$")])
    cards([("in_10y", "India 10Y"), ("us_10y", "US 10Y"), ("usd_eur", "EUR/USD"), ("us_dollar_broad", "Dollar index")])
    st.markdown("##### Liquidity · inflation · growth")
    cards([("in_wacr", "Call rate (WACR)"), ("in_net_liquidity", "Net LAF liquidity"),
           ("in_cpi_inflation", "India CPI inflation"), ("us_cpi", "US CPI inflation", DER["us_cpi_yoy"], True)])
    cards([("in_gdp_growth", "India real GDP growth"), ("us_gdp_growth", "US GDP growth (SAAR)"),
           ("in_unemployment", "India unemployment"), ("us_unemployment", "US unemployment")])
    st.markdown("##### External · fiscal · commodities")
    cards([("in_fx_reserves", "India forex reserves"), ("in_total_trade_balance", "Trade balance (G&S)"),
           ("in_fiscal_deficit_gdp_est", "Fiscal deficit (Budget)"), ("brent", "Brent crude")])
    st.caption("Change is versus the previous observation. bp = basis points (0.01 percentage point); "
               "pp = percentage points. Derived = computed by MacroLens from official data.")

# ======================= Policy rates =======================
with tabs["Policy rates"]:
    cards([("in_repo_rate", "RBI repo"), ("in_sdf_rate", "SDF (floor)"), ("in_msf_rate", "MSF (ceiling)"),
           ("in_crr", "CRR"), ("in_slr", "SLR")])
    cards([("us_policy_rate", "Fed funds target (upper)"), ("us_fed_funds_effective", "Fed funds effective"),
           ("ea_ecb_deposit_rate", "ECB deposit rate"), ("ea_ecb_mro_rate", "ECB refi rate")])
    two(block("RBI policy corridor: SDF floor, repo, MSF ceiling",
              [trace("in_msf_rate", "MSF (ceiling)", "#C0392B"), trace("in_repo_rate", "Repo rate"),
               trace("in_sdf_rate", "SDF (floor)", "#5B8C5A")], "%", ("in_repo_rate",),
              extra="Bank Rate = MSF. History 2008-2025 from RBI Handbook Table 40; changes since dated from MPC releases."),
        block("Policy rates: RBI vs Fed vs ECB",
              [trace("in_repo_rate", "RBI repo"), trace("us_policy_rate", "Fed funds (upper)"),
               trace("ea_ecb_deposit_rate", "ECB deposit rate")], "%",
              ("in_repo_rate", "us_policy_rate", "ea_ecb_deposit_rate")))
    two(block("Real policy rate: repo minus CPI inflation (derived)",
              [trace("in_repo_rate", "Real repo rate", df=DER["in_real_repo"])], "%", ("in_repo_rate", "in_cpi_inflation"),
              hlines=[(0, "")]),
        block("Reserve requirements: CRR and SLR",
              [trace("in_slr", "SLR", "#3B6FB6"), trace("in_crr", "CRR")], "% of NDTL", ("in_crr",)))

# ======================= Currency =======================
with tabs["Currency"]:
    cards([("inr_usd", "₹ per US$"), ("inr_eur", "₹ per €"), ("inr_gbp", "₹ per £"), ("inr_jpy100", "₹ per 100 ¥"),
           ("inr_aed", "₹ per AED")])
    cards([("us_dollar_broad", "Dollar index (broad)"), ("usd_eur", "US$ per €"), ("cny_usd", "CNY per US$")])
    two(block("Rupee per US dollar", [trace("inr_usd", "₹ per US$")], "₹ per US$", ("inr_usd",),
              extra="Higher = weaker rupee."),
        block("Rupee vs euro, pound, yen, dirham",
              [trace("inr_eur", "₹ per €", EXTRA[0]), trace("inr_gbp", "₹ per £", EXTRA[1]),
               trace("inr_jpy100", "₹ per 100 ¥", EXTRA[2]), trace("inr_aed", "₹ per AED", EXTRA[3])], "₹", ("inr_eur",)))
    two(block("Broad US dollar index", [trace("us_dollar_broad", "Dollar index")], "index", ("us_dollar_broad",)),
        block("EUR/USD and USD/CNY",
              [trace("usd_eur", "US$ per €")], "US$ per €", ("usd_eur",)))
    chart([trace("cny_usd", "CNY per US$")], "CNY per US$", height=260)
    sources("cny_usd")

# ======================= Bonds =======================
with tabs["Bonds"]:
    cards([("in_gsec_1y", "India 1Y"), ("in_gsec_2y", "India 2Y"), ("in_gsec_5y", "India 5Y"), ("in_10y", "India 10Y"),
           ("in_gsec_30y", "India 30Y")])
    cards([("us_3m", "US 3M"), ("us_2y", "US 2Y"), ("us_10y", "US 10Y"), ("us_30y", "US 30Y"), ("de_10y", "Germany 10Y")])

    def curve_now():
        st.markdown("**Yield curves today**")
        pts = []
        for label, ids, color in [("India G-sec (FBIL par)", [(1, "in_gsec_1y"), (2, "in_gsec_2y"), (5, "in_gsec_5y"),
                                                                (10, "in_10y"), (30, "in_gsec_30y")], COLORS["IN"]),
                                  ("US Treasury", [(0.25, "us_3m"), (2, "us_2y"), (10, "us_10y"), (30, "us_30y")], COLORS["US"])]:
            xs = [(t, get(i)["value"].iloc[-1]) for t, i in ids if has(i)]
            if xs:
                pts.append(go.Scatter(x=[x for x, _ in xs], y=[y for _, y in xs], mode="lines+markers", name=label,
                                      line=dict(color=color, width=2)))
        if pts:
            fig = go.Figure(pts)
            fig.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=10), xaxis_title="maturity (years)",
                              yaxis_title="%", legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0))
            st.plotly_chart(fig, use_container_width=True)
        sources("in_10y", "us_10y")

    two(curve_now,
        block("10-year yields: India, US, Germany",
              [trace("in_10y", "India 10Y"), trace("us_10y", "US 10Y"), trace("de_10y", "Germany 10Y (monthly)")], "%",
              ("in_10y", "us_10y", "de_10y")))
    two(block("India-US 10Y spread (derived)", [trace("in_10y", "India minus US 10Y", df=DER["in_us_10y"])], "pp",
              ("in_10y", "us_10y")),
        block("Curve slope: 10Y minus short end (derived)",
              [trace("in_10y", "India 10Y − 1Y", df=DER["in_10y_1y"]), trace("us_10y", "US 10Y − 2Y", df=DER["us_10y_2y"])],
              "pp", ("in_10y", "us_2y"), hlines=[(0, "inverted below 0")]))
    two(block("India G-sec curve over time",
              [trace("in_gsec_1y", "1Y", EXTRA[0]), trace("in_gsec_5y", "5Y", EXTRA[1]), trace("in_10y", "10Y"),
               trace("in_gsec_30y", "30Y", EXTRA[2])], "%", ("in_10y",)),
        block("US real 10Y yield (TIPS)", [trace("us_10y_real", "US 10Y real")], "%", ("us_10y_real",)))

# ======================= Liquidity =======================
with tabs["Liquidity"]:
    cards([("in_wacr", "Call rate (WACR)"), ("in_treps_rate", "TREPS rate"), ("in_mibor_overnight", "Overnight MIBOR"),
           ("in_net_liquidity", "Net LAF liquidity"), ("in_net_durable_liquidity", "Durable liquidity")])
    cards([("in_tbill_91d", "91-day T-bill"), ("in_tbill_364d", "364-day T-bill"), ("in_cd_3m", "3-month CD"),
           ("in_m3_yoy", "M3 growth"), ("in_bank_credit_yoy", "Bank credit growth")])
    two(block("Overnight rates inside the RBI corridor",
              [trace("in_msf_rate", "MSF (ceiling)", "#C0392B", "dot"), trace("in_repo_rate", "Repo"),
               trace("in_sdf_rate", "SDF (floor)", "#5B8C5A", "dot"), trace("in_wacr", "Call rate (WACR)", EXTRA[0]),
               trace("in_mibor_overnight", "Overnight MIBOR", EXTRA[1]), trace("in_market_repo_rate", "Market repo (MROR)", EXTRA[2])],
              "%", ("in_wacr", "in_mibor_overnight"),
              extra="Overnight rates above repo = tight liquidity; near the SDF floor = surplus."),
        block("Net liquidity in the banking system, ₹ crore",
              [trace("in_net_liquidity", "Net LAF liquidity (+ injected / − absorbed)", kind="bar"),
               trace("in_net_durable_liquidity", "Net durable liquidity", "#3B6FB6")], "₹ crore", ("in_net_liquidity",),
              hlines=[(0, "")]))
    two(block("Short-term rates: T-bills and CDs",
              [trace("in_tbill_91d", "91-day T-bill"), trace("in_tbill_364d", "364-day T-bill", EXTRA[1]),
               trace("in_cd_3m", "3-month CD", EXTRA[3])], "%", ("in_tbill_91d", "in_cd_3m")),
        block("Money and credit growth, YoY %",
              [trace("in_m3_yoy", "M3"), trace("in_bank_credit_yoy", "Bank credit", EXTRA[0]),
               trace("in_deposits_yoy", "Deposits", EXTRA[2])], "% YoY", ("in_m3_yoy",)))
    two(block("US: Fed balance sheet and bank reserves, US$ billion",
              [trace("us_fed_balance_sheet", "Fed total assets", scale=1e-3), trace("us_bank_reserves", "Bank reserves", EXTRA[2], scale=1e-3)],
              "US$ billion", ("us_fed_balance_sheet", "us_bank_reserves")),
        block("US: overnight reverse repo usage", [trace("us_reverse_repo", "ON RRP")], "US$ billion", ("us_reverse_repo",)))

# ======================= Inflation =======================
with tabs["Inflation"]:
    cards([("in_cpi_inflation", "India CPI"), ("in_food_inflation", "India food"),
           ("us_cpi", "US CPI", DER["us_cpi_yoy"], True), ("us_core_pce", "US core PCE", DER["us_core_pce_yoy"], True),
           ("ea_hicp", "Euro area HICP", DER["ea_hicp_yoy"], True)])
    two(block("India: headline vs food inflation, with RBI's 2-6% band",
              [trace("in_cpi_inflation", "Headline (2024 base, live)"),
               trace("in_cpi_inflation_back", "Headline (official back series)", GREY, "dot"),
               trace("in_food_inflation", "Food and beverages", "#C0392B")], "% YoY", ("in_cpi_inflation",),
              extra="Live and back series are separate lines, never joined.", band=(2, 6), hlines=[(4, "4% target")]),
        block("Headline inflation: India, US, euro area",
              [trace("in_cpi_inflation", "India"), trace("in_cpi_inflation_back", "India back series", COLORS["IN"], "dot"),
               trace("us_cpi", "US CPI (derived)", df=DER["us_cpi_yoy"]),
               trace("ea_hicp", "Euro area HICP (derived)", df=DER["ea_hicp_yoy"])], "% YoY",
              ("in_cpi_inflation", "us_cpi", "ea_hicp")))
    two(block("US: CPI, core CPI and core PCE (Fed's 2% target measure)",
              [trace("us_cpi", "CPI", df=DER["us_cpi_yoy"]), trace("us_core_cpi", "Core CPI", "#7FA7D9", "dash", df=DER["us_core_yoy"]),
               trace("us_core_pce", "Core PCE", EXTRA[0], df=DER["us_core_pce_yoy"])], "% YoY",
              ("us_cpi", "us_core_pce"), hlines=[(2, "2% target")]),
        block("China CPI inflation, annual (IMF)", [trace("cn_inflation", "China")], "%", ("cn_inflation",)))

# ======================= Growth =======================
with tabs["Growth"]:
    cards([("in_gdp_growth", "India real GDP"), ("in_gdp_growth_nominal", "India nominal GDP"),
           ("us_gdp_growth", "US real GDP (SAAR)"), ("ea_gdp_real", "Euro area real GDP", DER["ea_gdp_yoy"], True),
           ("cn_gdp_growth", "China real GDP")])
    nom, real = get("in_gdp_nominal").set_index("date")["value"], get("in_gdp_real").set_index("date")["value"]
    deflator = (nom / real * 100).dropna().rename("value").reset_index() if has("in_gdp_real") else pd.DataFrame(columns=["date", "value"])
    two(block("India GDP growth, YoY % (2022-23 base)",
              [trace("in_gdp_growth", "Real", kind="bar"), trace("in_gdp_growth_nominal", "Nominal", GREY, kind="bar")],
              "% YoY", ("in_gdp_growth",), extra="Quarters of India's fiscal year (Q1 = Apr-Jun)."),
        block("Real GDP growth outlook: IMF projections",
              [trace("in_gdp_growth_imf_proj", "India"), trace("us_gdp_growth_imf_proj", "US"),
               trace("cn_gdp_growth_imf_proj", "China")], "%", ("in_gdp_growth_imf_proj",)))
    st.markdown("**How India's GDP is spent: Y = C + I + G + (X − M), % of real GDP (derived)**")
    parts = {"Private consumption (C)": "in_pfce_real", "Government consumption (G)": "in_gfce_real",
             "Fixed investment (GFCF)": "in_gfcf_real", "Change in stocks": "in_change_stock_real",
             "Valuables": "in_valuables_real", "Exports (X)": "in_exports_real", "Imports (M)": "in_imports_real"}
    if has("in_gdp_real"):
        shares = pd.DataFrame({k: get(i).set_index("date")["value"] / real * 100 * (-1 if i == "in_imports_real" else 1)
                               for k, i in parts.items() if has(i)}).dropna(how="all")
        fig = go.Figure([go.Bar(x=shares.index, y=shares[c], name=c, marker_color=col)
                         for c, col in zip(shares.columns, ["#E07B39", "#3B6FB6", "#5B8C5A", "#8E5EA2", "#D4AC0D", "#16A085", "#C0392B"])])
        fig.update_layout(barmode="relative", height=360, margin=dict(l=10, r=10, t=40, b=10), yaxis_title="% of real GDP",
                          legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0))
        st.plotly_chart(fig, use_container_width=True)
        sources("in_pfce_real", extra="Imports shown as negative. Shares need not sum to 100 (discrepancies).")
    two(block("GDP deflator (derived): producing more, or paying more?",
              [trace("in_gdp_nominal", "Deflator (2022-23 = 100)", df=deflator)], "index", ("in_gdp_nominal",),
              extra="Nominal GDP / real GDP × 100."),
        block("Growth: US (q/q annualised), euro area (YoY), China (annual)",
              [trace("us_gdp_growth", "US"), trace("ea_gdp_real", "Euro area YoY (derived)", df=DER["ea_gdp_yoy"]),
               trace("cn_gdp_growth", "China")], "%", ("us_gdp_growth", "ea_gdp_real", "cn_gdp_growth")))
    two(block("GNI per capita, Atlas method (current US$)",
              [trace("in_gni_pc", "India"), trace("cn_gni_pc", "China")], "US$", ("in_gni_pc",)),
        block("Investment: gross fixed capital formation, % of GDP",
              [trace("in_gfcf_gdp", "India"), trace("cn_gfcf_gdp", "China")], "% of GDP", ("in_gfcf_gdp",)))

# ======================= External =======================
with tabs["External"]:
    cards([("in_fx_reserves", "Forex reserves"), ("in_total_exports", "Exports (G&S)"), ("in_total_imports", "Imports (G&S)"),
           ("in_total_trade_balance", "Trade balance (G&S)"), ("in_current_account", "Current account")])
    cards([("in_merch_trade_balance", "Merchandise balance"), ("in_fdi_india_net", "FDI into India (net)"),
           ("in_fdi_net", "Net FDI"), ("in_fpi_net", "Net FPI"), ("in_current_account_gdp", "Current account % GDP")])
    two(block("Foreign exchange reserves",
              [trace("in_fx_reserves", "Total", scale=1e-3), trace("in_fx_fca", "Foreign currency assets", EXTRA[0], scale=1e-3),
               trace("in_fx_gold", "Gold", EXTRA[1], scale=1e-3)], "US$ billion", ("in_fx_reserves",)),
        block("Monthly trade, goods and services",
              [trace("in_total_exports", "Exports", "#5B8C5A"), trace("in_total_imports", "Imports", "#C0392B"),
               trace("in_total_trade_balance", "Balance", GREY, kind="bar")], "US$ billion", ("in_total_exports",)))
    two(block("Merchandise vs services balance",
              [trace("in_merch_trade_balance", "Merchandise", "#C0392B", kind="bar"),
               trace("in_services_exports", "Services exports", "#5B8C5A")], "US$ billion", ("in_merch_trade_balance",)),
        block("Balance of payments: current account and capital flows",
              [trace("in_current_account", "Current account", kind="bar"), trace("in_fdi_net", "Net FDI", EXTRA[0], kind="bar"),
               trace("in_fpi_net", "Net FPI", EXTRA[2], kind="bar")], "US$ billion", ("in_current_account",)))
    two(block("FDI net inflows, annual (World Bank)", [trace("in_fdi_inflows", "India", scale=1e-9)], "US$ billion",
              ("in_fdi_inflows",)),
        block("Current account balance, % of GDP (annual)", [trace("in_current_account_gdp", "India")], "% of GDP",
              ("in_current_account_gdp",), hlines=[(0, "")]))

# ======================= Fiscal =======================
with tabs["Fiscal"]:
    cards([("in_fiscal_deficit_gdp", "Fiscal deficit (actual)"), ("in_fiscal_deficit_gdp_est", "Fiscal deficit (latest est.)"),
           ("in_revenue_deficit_gdp", "Revenue deficit (actual)"), ("in_primary_deficit_gdp", "Primary deficit (actual)"),
           ("in_cga_fiscal_deficit_pct_target", "Fiscal deficit YTD, % of target")])
    cards([("in_cga_fiscal_deficit", "Fiscal deficit YTD"), ("in_cga_capex", "Capex YTD"),
           ("in_cga_total_receipts", "Receipts YTD"), ("in_cga_interest", "Interest YTD")])
    cards([("in_gov_debt_gdp", "India govt debt (IMF)"), ("us_gov_debt_gdp", "US govt debt (IMF)"),
           ("cn_gov_debt_gdp", "China govt debt (IMF)"), ("us_federal_debt_gdp", "US federal debt")])
    two(block("Union Budget deficits, % of GDP",
              [trace("in_fiscal_deficit_gdp", "Fiscal deficit (actual)", kind="bar"),
               trace("in_fiscal_deficit_gdp_est", "Fiscal deficit (RE/BE)", GREY, kind="bar"),               trace("in_revenue_deficit_gdp", "Revenue deficit", EXTRA[0]),
               trace("in_primary_deficit_gdp", "Primary deficit", EXTRA[2])], "% of GDP", ("in_fiscal_deficit_gdp",),
              extra="Actuals and estimates are kept separate. FRBM glide path: below 4.5% of GDP by 2025-26.",
              hlines=[(4.5, "4.5% glide-path target")]),
        block("Union Government monthly accounts (CGA): fiscal deficit so far this year, % of target",
              [trace("in_cga_fiscal_deficit_pct_target", "Fiscal deficit, % of budget target", kind="bar")], "%",
              ("in_cga_fiscal_deficit_pct_target",), extra="Cumulative from April; resets each fiscal year."))
    two(block("Union capital expenditure vs interest payments, ₹ lakh crore",
              [trace("in_capex_cr", "Capex (actual)", "#5B8C5A", kind="bar", scale=1e-5),
               trace("in_capex_cr_est", "Capex (RE/BE)", "#A9CBA4", kind="bar", scale=1e-5),
               trace("in_interest_cr", "Interest (actual)", "#C0392B", scale=1e-5),
               trace("in_interest_cr_est", "Interest (RE/BE)", "#C0392B", "dot", scale=1e-5)], "₹ lakh crore",
              ("in_capex_cr",)),
        block("Union fiscal deficit: actual vs latest estimate, ₹ lakh crore",
              [trace("in_fiscal_deficit_cr", "Actual", kind="bar", scale=1e-5),
               trace("in_fiscal_deficit_cr_est", "RE/BE", GREY, kind="bar", scale=1e-5)], "₹ lakh crore",
              ("in_fiscal_deficit_cr",), extra="FY 2022-23 actual is not available from indiabudget.gov.in."))
    two(block("General government debt, % of GDP (IMF)",
              [trace("in_gov_debt_gdp", "India"), trace("in_gov_debt_gdp_proj", "India, IMF projection", COLORS["IN"], "dot"),
               trace("us_gov_debt_gdp", "US"), trace("cn_gov_debt_gdp", "China")], "% of GDP", ("in_gov_debt_gdp",),
              hlines=[(60, "FRBM target, India general govt: 60%")]),
        block("General government fiscal balance, % of GDP (IMF)",
              [trace("in_gov_balance_gdp", "India"), trace("in_gov_balance_gdp_proj", "India, IMF projection", COLORS["IN"], "dot"),
               trace("us_gov_balance_gdp", "US"), trace("cn_gov_balance_gdp", "China")], "% of GDP",
              ("in_gov_balance_gdp",), hlines=[(0, "")]))
    chart([trace("us_federal_debt_gdp", "US federal debt")], "% of GDP", height=240)
    sources("us_federal_debt_gdp")

# ======================= Jobs =======================
with tabs["Jobs"]:
    cards([("in_unemployment", "India unemployment"), ("in_lfpr", "India LFPR"), ("in_wpr", "India worker ratio"),
           ("us_unemployment", "US unemployment"), ("us_lfpr", "US LFPR")])
    two(block("India PLFS monthly",
              [trace("in_lfpr", "LFPR"), trace("in_wpr", "Worker population ratio", "#5B8C5A"),
               trace("in_unemployment", "Unemployment rate", "#C0392B")], "%", ("in_unemployment",),
              extra="Current weekly status, age 15+, rural + urban."),
        block("Unemployment: India, China (ILO modelled), US",
              [trace("in_unemployment_ilo", "India (ILO)"), trace("cn_unemployment_ilo", "China (ILO)"),
               trace("us_unemployment", "US (BLS)")], "%", ("in_unemployment_ilo", "us_unemployment"),
              extra="ILO estimates are modelled and differ from PLFS."))
    chart([trace("in_lfpr_male_ilo", "India, male", "#3B6FB6"), trace("in_lfpr_female_ilo", "India, female"),
           trace("cn_lfpr_female_ilo", "China, female")], "% of population 15+", height=280)
    sources("in_lfpr_female_ilo")

# ======================= Commodities =======================
with tabs["Commodities"]:
    cards([("brent", "Brent crude")])
    chart([trace("brent", "Brent")], "US$ per barrel")
    sources("brent", extra="India imports most of its crude oil, so oil prices feed into inflation, the current account and the rupee.")

# ======================= Data quality =======================
with tabs["Data quality"]:
    q = quality(stamp)
    if q.empty:
        st.success("All checks passed: no gaps, unusual jumps, stale or malformed series.")
    else:
        n_err, n_warn = (q["severity"] == "error").sum(), (q["severity"] == "warn").sum()
        (st.error if n_err else st.warning)(f"{n_err} error(s), {n_warn} warning(s)")
        st.dataframe(q, use_container_width=True, hide_index=True)
    st.caption("Checks: missing or future values, gaps longer than normal (last 2 years), unusually large moves "
               "in the last year versus the last 3 years, and series that have stopped updating. A warning about "
               "a large move usually marks a real market event.")

# ======================= Data & sources =======================
with tabs["Data & sources"]:
    table = summary[["indicator_id", "name", "topic", "country", "value", "unit", "date", "first_date",
                     "frequency", "source", "source_url", "release_date", "fetched_at"]].copy()
    st.dataframe(table, use_container_width=True, hide_index=True,
                 column_config={"source_url": st.column_config.LinkColumn("source link")})
    pick = st.selectbox("Download one series", summary["indicator_id"], format_func=lambda i: f"{i} — {ROWS.loc[i, 'name']}")
    out = get(pick).copy()
    if st.checkbox("Include every vintage (revisions)"):
        out = allv[allv["indicator_id"] == pick][["date", "value", "fetched_at"]].sort_values(["date", "fetched_at"])
    st.download_button("Download CSV", out.to_csv(index=False).encode("utf-8"), file_name=f"{pick}.csv", mime="text/csv")
    st.caption("Raw source files are kept unmodified in data/raw for audit. Derived values (YoY %, deflator, GDP "
               "shares, spreads, real rate) are computed in the app and labelled as derived.")

st.divider()
st.caption(DATA_NOTE)
