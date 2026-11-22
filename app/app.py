"""MacroLens dashboard (Streamlit) — design B + C.

B: clean finance layout (white, navy, India saffron accent) with a one-line summary.
C: each topic has its own colour; every card carries a rule-based traffic light
   (analytics/signals.py) comparing the number with an official target or recent history.

Run:  streamlit run app/app.py
A country selector drives the page: India, United States, Euro area, China, Japan, Compare.
Charts and cards skip series that are missing, so a failed fetch never breaks the page.
"""
import re
import sys
from datetime import date, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from html import escape as html_escape  # noqa: E402

from analytics import briefing as bf  # noqa: E402
from analytics import signals as sg  # noqa: E402
from ingest.registry import load_registry  # noqa: E402
from storage import db  # noqa: E402
from transform.checks import run_checks  # noqa: E402
from transform.normalize import yoy_pct  # noqa: E402

st.set_page_config(page_title="MacroLens", page_icon="📈", layout="wide", initial_sidebar_state="expanded")
BRAND = "MacroLens"

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
BLUE = "#2563EB"


def _data_uri(svg_text: str) -> str:
    import base64
    return "data:image/svg+xml;base64," + base64.b64encode(svg_text.encode("utf-8")).decode("ascii")


# Dotted world globe behind the page header: app/static/globe.webp, drawn by tools/make_globe.py from Natural Earth
# land outlines and served by Streamlit's static file serving ([server] enableStaticServing in .streamlit/config.toml).
GLOBE_URL = "./app/static/globe.webp"

WAVE_URI = _data_uri(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 160" preserveAspectRatio="none">'
    '<path d="M0 110 C60 70 110 140 170 100 S260 40 300 60 V160 H0Z" fill="#3B82F6" fill-opacity=".18"/>'
    '<path d="M0 135 C70 100 120 150 190 125 S270 90 300 100 V160 H0Z" fill="#60A5FA" fill-opacity=".14"/></svg>')
CANDLES_URI = _data_uri(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 120">'
    '<polyline points="0,104 30,96 55,100 80,84 105,88 130,66 155,72 180,48 205,52 240,18" fill="none" '
    'stroke="#60A5FA" stroke-opacity=".55" stroke-width="2"/>'
    + "".join(f'<rect x="{18 + i * 24}" y="{98 - i * 8 - (i % 3) * 4}" width="6" height="{14 + (i % 4) * 5}" '
              f'fill="#93C5FD" fill-opacity=".35"/>' for i in range(9))
    + '</svg>')

LATIN = ("U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,"
         "U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD")
LATIN_EXT = ("U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,"
             "U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF")

# Font: Inter (open source), hosted in app/static/fonts and set as theme.font in .streamlit/config.toml.
# The @font-face rules are repeated here so the font also loads when the config file is not picked up.
st.markdown(f"""<style>
@font-face{{font-family:"Inter";font-style:normal;font-weight:100 900;font-display:swap;
  src:url("./app/static/fonts/inter-latin-wght-normal.woff2") format("woff2");unicode-range:{LATIN}}}
@font-face{{font-family:"Inter";font-style:normal;font-weight:100 900;font-display:swap;
  src:url("./app/static/fonts/inter-latin-ext-wght-normal.woff2") format("woff2");unicode-range:{LATIN_EXT}}}
.stApp strong,.stApp b{{font-weight:700}}
.stApp h1,.stApp h2,.stApp h3{{letter-spacing:-.015em}}
.kpi-v,.kt td,.pr .v,.pr .dd,.kpi-d{{font-variant-numeric:tabular-nums}}
.block-container{{padding-top:3rem;max-width:1380px}}
header[data-testid="stHeader"]{{background:transparent}}
[data-testid="stMain"]{{background:url("{GLOBE_URL}") no-repeat right -110px top -90px / 520px,
  linear-gradient(180deg,#EDF3FC 0,#F7FAFE 360px,#FFFFFF 640px);background-attachment:local,local}}
@media (max-width:900px){{[data-testid="stMain"]{{background:url("{GLOBE_URL}") no-repeat right -90px top -50px / 300px,
  linear-gradient(180deg,#EDF3FC 0,#F7FAFE 360px,#FFFFFF 640px);background-attachment:local,local}}}}
section[data-testid="stSidebar"]{{background:url("{WAVE_URI}") no-repeat bottom / 100% 190px,
  linear-gradient(180deg,#0B2545 0%,#0E3260 55%,#123C74 100%);border-right:none}}
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] button,
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button{{color:#CBD5E1}}
section[data-testid="stSidebar"] [role="radiogroup"] label{{padding:.6rem .8rem;border-radius:10px;margin:2px 0;width:100%}}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){{background:{BLUE}}}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p{{color:#FFFFFF !important}}
section[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:first-child:not([data-testid]),
section[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child:not(:has([data-testid])){{display:none !important}}
section[data-testid="stSidebar"] [data-testid="stRadioOption"]{{width:100%;padding:.6rem .8rem;border-radius:10px}}
section[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"]{{background:{BLUE};box-shadow:0 4px 14px rgba(37,99,235,.35)}}
section[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] p{{color:#FFFFFF !important}}
section[data-testid="stSidebar"] [data-testid="stRadioOption"]:not([data-selected="true"]):hover,
section[data-testid="stSidebar"] [role="radiogroup"] label:not(:has(input:checked)):hover{{background:rgba(255,255,255,.08)}}
section[data-testid="stSidebar"] [role="radiogroup"] label p{{font-size:.97rem;font-weight:500;color:#DCE6F5}}
section[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] p,
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p{{font-weight:600}}
section[data-testid="stSidebar"] .stButton button p{{font-weight:500;font-size:.9rem}}
section[data-testid="stSidebar"] [data-testid="stIconMaterial"]{{color:inherit}}
section[data-testid="stSidebar"] .stButton button{{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.18);
  border-radius:10px;justify-content:flex-start}}
section[data-testid="stSidebar"] .stButton button p{{color:#E2E8F0}}
section[data-testid="stSidebar"] .stButton button:hover{{background:rgba(255,255,255,.14);border-color:rgba(255,255,255,.3)}}
.sb-brand{{display:flex;align-items:center;gap:.5rem;font-size:1.4rem;font-weight:700;color:#FFFFFF;margin:.2rem 0 1rem}}
.sb-sub{{font-size:.72rem;font-weight:700;color:#8FA6C8;letter-spacing:.08em;margin:1.2rem 0 .4rem;
  border-top:1px solid rgba(255,255,255,.12);padding-top:1rem}}
.tb{{display:flex;align-items:center;gap:.8rem;flex-wrap:wrap}}
.tb-title{{font-size:1.45rem;font-weight:700;color:{NAVY}}}
.tb-tag{{color:#334155;font-size:.92rem;font-weight:500;border-left:1px solid {LINE};padding-left:.8rem}}
.tb-upd{{color:#334155;font-size:.85rem;text-align:right;margin-top:.35rem;padding:.3rem .6rem;border-radius:8px;
  background:rgba(255,255,255,.82);float:right}}
.ov-h{{display:flex;align-items:center;gap:.7rem;margin:.6rem 0 .1rem;border-left:4px solid {BLUE};padding-left:.8rem}}
.ov-h img{{height:28px;border-radius:4px;border:1px solid {LINE}}}
.ov-h h1{{font-size:2.1rem;font-weight:800;color:{NAVY};margin:0;padding:0;letter-spacing:-.01em}}
.ov-h h1 span{{color:{BLUE}}}
@media (max-width:700px){{.ov-h h1{{font-size:1.45rem}}}}
.ov-ok{{background:#DCFCE7;color:#166534;border-radius:8px;padding:2px 10px;font-size:.82rem;font-weight:600}}
.ov-warn{{background:#FEF3C7;color:#92400E;border-radius:8px;padding:2px 10px;font-size:.82rem;font-weight:600}}
.ov-sub{{color:{MUTED};font-size:.98rem;margin:0 0 .9rem;padding-left:calc(.8rem + 4px)}}
.kpi-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.9rem;margin-bottom:.9rem}}
.kpi{{background:#FFFFFF;border:1px solid {LINE};border-radius:14px;padding:.9rem 1rem;
  box-shadow:0 1px 2px rgba(15,23,42,.04),0 6px 18px rgba(15,23,42,.05)}}
.kpi-good{{background:linear-gradient(180deg,#F0FDF4,#FFFFFF 70%);border-color:#D1FAE5}}
.kpi-bad{{background:linear-gradient(180deg,#FEF2F2,#FFFFFF 70%);border-color:#FEE2E2}}
.kpi-watch{{background:linear-gradient(180deg,#FFFBEB,#FFFFFF 70%);border-color:#FEF3C7}}
.panel,[data-testid="stVerticalBlockBorderWrapper"]{{box-shadow:0 1px 2px rgba(15,23,42,.03),0 6px 18px rgba(15,23,42,.04)}}
.panel,div[class*="st-key-bsec_"],.st-key-bkey{{background:#FFFFFF}}
.bh{{display:flex;align-items:center;gap:.55rem;font-size:1.2rem;font-weight:700;color:{NAVY};margin:.1rem 0 .5rem}}
.bh svg{{width:24px;height:24px;stroke:{BLUE};flex:none}}
.st-key-bexec{{background:url("{CANDLES_URI}") no-repeat right 14px bottom 10px / 230px,
  linear-gradient(135deg,#0B2545 0%,#0F3466 60%,#1B4F9C 100%);border-radius:16px;padding:1.2rem 1.4rem 1rem;
  box-shadow:0 10px 28px rgba(11,37,69,.28)}}
.st-key-bexec .bh{{color:#FFFFFF;font-size:1.45rem}}
.st-key-bexec .bh svg{{stroke:#93C5FD}}
.st-key-bexec p,.st-key-bexec li,.st-key-bexec strong,.st-key-bexec em,.st-key-bexec td,.st-key-bexec th{{color:#E6EEF9 !important}}
.st-key-bexec strong{{color:#FFFFFF !important}}
.st-key-bexec p,.st-key-bexec li{{font-size:.95rem;line-height:1.6}}
.st-key-bexec a{{color:#93C5FD !important}}
.bmeta{{display:flex;align-items:center;gap:.5rem;color:{NAVY};font-size:.9rem;background:#FFFFFF;border:1px solid {LINE};
  border-radius:10px;padding:.55rem .8rem;box-shadow:0 1px 2px rgba(15,23,42,.04)}}
.bmeta svg{{width:20px;height:20px;stroke:{BLUE};flex:none}}
.bsnap{{color:{MUTED};font-size:.8rem;margin:-.3rem 0 .9rem}}
.bnotes{{color:{MUTED};font-size:.8rem;line-height:1.5;margin:.6rem 0}}
div[class*="st-key-bsec_"] p,div[class*="st-key-bsec_"] li,.st-key-bkey p,.st-key-bkey li{{font-size:.93rem;line-height:1.6}}
div[class*="st-key-bsec_"] h3{{font-size:1rem !important;color:{NAVY}}}
div[class*="st-key-bsec_"] table{{font-size:.86rem}}
.kpi-top{{display:flex;gap:.6rem;align-items:flex-start}}
.kpi-top svg{{width:26px;height:26px;stroke:{NAVY};flex:none;margin-top:2px}}
.kpi-t{{font-weight:700;color:{NAVY};font-size:1rem;line-height:1.2}}
.kpi-s{{color:{MUTED};font-size:.78rem}}
.kpi-mid{{display:flex;align-items:center;justify-content:space-between;gap:.4rem;margin:.55rem 0 .35rem}}
.kpi-v{{font-size:1.7rem;font-weight:700;line-height:1;letter-spacing:-.02em}}
.kpi-mid > div{{white-space:nowrap}}
.kpi-mid > svg{{flex:1 1 40px;min-width:0;max-width:96px;height:auto}}
.kpi{{overflow:hidden}}
.kpi-d{{font-size:.85rem;font-weight:600;white-space:nowrap;margin-left:.35rem}}
.kpi-f{{color:{MUTED};font-size:.78rem}}
.panel{{background:#FFFFFF;border:1px solid {LINE};border-radius:14px;padding:1rem 1.1rem}}
.panel h3{{font-size:1.25rem;font-weight:700;color:{NAVY};margin:0}}
.panel .ps{{color:{MUTED};font-size:.85rem;margin:.1rem 0 .6rem}}
.pr{{display:grid;grid-template-columns:26px minmax(64px,1fr) auto auto;grid-template-areas:"i n v p" "i n d p";
  column-gap:.6rem;row-gap:.1rem;align-items:center;padding:.6rem 0;border-bottom:1px solid #F1F5F9}}
.pr > svg{{grid-area:i}} .pr > .n{{grid-area:n}} .pr > .v{{grid-area:v;align-self:end}}
.pr > .dd{{grid-area:d;align-self:start}} .pr > :last-child{{grid-area:p}}
.pr svg{{width:22px;height:22px;stroke:#334155}}
.pr .n{{font-weight:700;color:{NAVY};font-size:.9rem;line-height:1.2;overflow-wrap:normal;word-break:normal}}
.pr .n span{{display:block;font-weight:400;color:{MUTED};font-size:.74rem}}
.pr .v{{font-weight:700;font-size:.95rem;text-align:right;white-space:nowrap}}
.pr .dd{{font-size:.74rem;font-weight:600;text-align:right;white-space:nowrap}}
.pr .pill{{font-size:.7rem;padding:3px 8px}}
.pill{{border-radius:999px;padding:3px 10px;font-size:.75rem;font-weight:600;white-space:nowrap}}
.kt{{width:100%;border-collapse:collapse;font-size:.9rem}}
.kt th{{text-align:left;font-size:.72rem;letter-spacing:.05em;color:{MUTED};background:#F8FAFC;padding:.55rem .6rem;font-weight:700}}
.kt td{{padding:.55rem .6rem;border-bottom:1px solid #F1F5F9;color:{NAVY}}}
.kt td b{{font-weight:700}} .kt td small{{color:{MUTED};margin-left:.3rem}}
.kt a{{color:{NAVY};text-decoration:none;border-bottom:1px dotted {MUTED}}}
.note{{background:#EEF4FB;border:1px solid #D6E4F5;border-radius:12px;padding:.8rem 1rem;color:{NAVY};margin:1rem 0}}
.note b{{margin-right:.6rem}}
.st-key-brief{{padding:.6rem 1.2rem}}
.st-key-brief h1{{font-size:1.55rem !important;color:{NAVY};padding-top:.2rem}}
.st-key-brief h2{{font-size:1.15rem !important;color:{NAVY};border-bottom:1px solid {LINE};padding:.9rem 0 .3rem;margin-top:.6rem}}
.st-key-brief h3{{font-size:1rem !important;color:{NAVY}}}
.st-key-brief p,.st-key-brief li{{font-size:.95rem;line-height:1.6}}
.st-key-brief blockquote{{background:#EEF4FB;border-left:3px solid #1D4ED8;border-radius:0;padding:.4rem .8rem;margin:.6rem 0}}
.st-key-brief table{{font-size:.88rem}}
@media (max-width:1280px){{.kpi-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
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
MONEY_UNITS = {"inr_crore", "usd_million", "usd", "eur_million", "jpy_billion", "usd_billion"}


def fmt_value(v, unit):
    if v is None or pd.isna(v):
        return "–"
    if unit in MONEY_UNITS and v < 0:
        return "−" + fmt_value(-v, unit)
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
COMPARE_CODES = None  # set by the Compare page to filter lines by country


def clip(df: pd.DataFrame, frequency: str) -> pd.DataFrame:
    if DAYS is None or df.empty or frequency in ("quarterly", "annual"):
        return df
    return df[df["date"] >= pd.Timestamp(date.today()) - pd.Timedelta(days=DAYS)]


def line(iid: str, label: str, color: str | None = None, dash: str | None = None, df: pd.DataFrame | None = None,
         kind: str = "line", scale: float = 1.0):
    if iid not in ROWS.index:
        return None
    row = ROWS.loc[iid]
    if COMPARE_CODES is not None and row["country"] not in COMPARE_CODES | {"GLOBAL"}:
        return None
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
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
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
upd_txt = f"Last updated: {upd.tz_convert(timezone(timedelta(hours=5, minutes=30))):%d %b %Y, %H:%M} IST" if upd is not None else ""
COUNTRY_LIST = ["India", "United States", "Euro area", "China", "Japan"]
FLAGS = {"India": "in", "United States": "us", "Euro area": "eu", "China": "cn", "Japan": "jp"}
PAGES = {":material/home: Overview": "Overview", ":material/newspaper: Daily briefing": "Daily briefing",
         ":material/public: Countries": "Countries",
         ":material/bar_chart: Indicators": "Indicators", ":material/compare_arrows: Compare": "Compare",
         ":material/database: Data sources": "Data sources"}
st.session_state.setdefault("page", ":material/home: Overview")
st.session_state.setdefault("country_pick", "India")
st.session_state.setdefault("compare_set", ["India", "United States", "Euro area", "China", "Japan"])


def go_to(page: str, **state):
    st.session_state["page"] = next(k for k, v in PAGES.items() if v == page)
    for k, v in state.items():
        st.session_state[k] = v


with st.sidebar:
    st.markdown(f'<div class="sb-brand"><svg width="26" height="26" viewBox="0 0 24 24"><rect x="3" y="12" width="4" height="9" '
                f'rx="1" fill="{SAFFRON}"/><rect x="10" y="7" width="4" height="14" rx="1" fill="#3B82F6"/><rect x="17" y="3" '
                f'width="4" height="18" rx="1" fill="#60A5FA"/></svg>{BRAND}</div>', unsafe_allow_html=True)
    page = PAGES[st.radio("Navigate", list(PAGES), key="page", label_visibility="collapsed")]
    st.markdown('<div class="sb-sub">QUICK COMPARE</div>', unsafe_allow_html=True)
    st.button("India vs United States", width="stretch", on_click=go_to,
              args=("Compare",), kwargs={"compare_set": ["India", "United States"]})
    st.button("India vs China", width="stretch", on_click=go_to,
              args=("Compare",), kwargs={"compare_set": ["India", "China"]})
    st.button("India vs Euro area", width="stretch", on_click=go_to,
              args=("Compare",), kwargs={"compare_set": ["India", "Euro area"]})

t1, t2, t3, t4 = st.columns([3.6, 1.7, 1.8, 2.3])
with t1:
    st.markdown(f'<div class="tb"><span class="tb-title">{BRAND}</span><span class="tb-tag">Macroeconomic intelligence '
                'for investors and businesses</span></div>', unsafe_allow_html=True)
with t2:
    country = st.selectbox("Country", COUNTRY_LIST, key="country_pick", label_visibility="collapsed")
with t3:
    this_year = date.today().year
    span = st.selectbox("Range", list(RANGES), index=1, label_visibility="collapsed", key="range",
                        format_func=lambda k: f"{this_year - RANGES[k] // 365}–{str(this_year)[2:]}" if RANGES[k] else "All years")
with t4:
    st.markdown(f'<div class="tb-upd">⟳ {upd_txt}</div>', unsafe_allow_html=True)
DAYS = RANGES[span]


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
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
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
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
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


def compare(codes: set | None = None):
    """Cross-country charts; `codes` (e.g. {'IN', 'US'}) limits which countries' lines are drawn."""
    global COMPARE_CODES
    COMPARE_CODES = codes
    if codes is not None and not codes:
        st.info("Pick at least one country above.")
        return
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


# ======================= overview (reference design) =======================
ICON = {
    "gdp": '<path d="M3 21h18M5 21V12h3v9M10.5 21V7h3v14M16 21V3h3v18"/>',
    "infl": '<path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9-9-9z"/><circle cx="7.5" cy="7.5" r="1.2"/>',
    "jobs": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20v-1.5a4.5 4.5 0 0 1 4.5-4.5h4a4.5 4.5 0 0 1 4.5 4.5V20M16 4.3a3.5 3.5 0 0 1 0 7.4M21.5 20v-1.5a4.5 4.5 0 0 0-3.4-4.4"/>',
    "debt": '<ellipse cx="12" cy="5.5" rx="8" ry="2.8"/><path d="M4 5.5v6.5c0 1.6 3.6 2.8 8 2.8s8-1.2 8-2.8V5.5M4 12v6.3c0 1.6 3.6 2.8 8 2.8s8-1.2 8-2.8V12"/>',
    "bank": '<path d="M3 21h18M3 10h18M5 6.5L12 3l7 3.5M4.5 10v11M19.5 10v11M8.5 13.5v4M12 13.5v4M15.5 13.5v4"/>',
    "fx": '<circle cx="12" cy="12" r="9"/><path d="M14.8 9A2 2 0 0 0 13 8h-2a2 2 0 0 0 0 4h2a2 2 0 0 1 0 4h-2a2 2 0 0 1-1.8-1M12 6.5v11"/>',
    "yield": '<path d="M3 17l6-6 4 4 8-8M14.5 7H21v6.5"/>',
    "shield": '<path d="M12 3l8 3.5v5.5c0 4.8-3.4 7.9-8 9-4.6-1.1-8-4.2-8-9V6.5z"/>',
    "drop": '<path d="M12 3.5l5.6 7.4a6.6 6.6 0 1 1-11.2 0z"/>',
    "scale": '<path d="M7 20h10M12 4v16M5 7l7-2 7 2M5 7l-3 6.5a3 3 0 0 0 6 0zM19 7l-3 6.5a3 3 0 0 0 6 0z"/>',
    "ship": '<path d="M3 18l-1-5h20l-2 5M5 13V8h9l4 5M8 8V4h3"/><path d="M2 21c1.5 0 1.5-1 3-1s1.5 1 3 1 1.5-1 3-1 1.5 1 3 1 1.5-1 3-1 1.5 1 3 1"/>',
    "credit": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18M7 15h3"/>',
    "flow": '<path d="M4 7h13l-3-3M20 17H7l3 3"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/>',
    "link": '<path d="M10 14a4.5 4.5 0 0 0 6.4 0l3.2-3.2a4.5 4.5 0 0 0-6.4-6.4L12 5.6M14 10a4.5 4.5 0 0 0-6.4 0l-3.2 3.2a4.5 4.5 0 0 0 6.4 6.4l1.2-1.2"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.3"/>',
    "alert": '<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5M12 17.3v.2"/>',
    "bulb": '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.4 1.1 2.2h5c0-.8.4-1.6 1.1-2.2A6 6 0 0 0 12 3z"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.3a2.5 2.5 0 1 1 3.6 2.3c-.8.4-1.2 1-1.2 1.9v.5M12 16.8v.2"/>',
    "doc": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 11h6M9 14.5h6M9 18h4"/>',
    "story": '<path d="M4 5h16v11H8l-4 4z"/><path d="M8 9h8M8 12.5h5"/>',
}
LEVEL_COLOR = {"good": "#15803D", "watch": "#B45309", "bad": "#B91C1C", "neutral": NAVY}


def svg(name: str) -> str:
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
            f'{ICON.get(name, ICON["gdp"])}</svg>')


def spark(df: pd.DataFrame, color: str, n: int = 24) -> str:
    """Tiny area sparkline (last n points) as inline SVG."""
    d = df.dropna().tail(n)
    if len(d) < 2:
        return ""
    v = d["value"].astype(float).tolist()
    lo, hi = min(v), max(v)
    rng = (hi - lo) or 1.0
    w, h = 96, 34
    pts = [(i * w / (len(v) - 1), h - 3 - (x - lo) / rng * (h - 6)) for i, x in enumerate(v)]
    line_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"0,{h} " + line_pts + f" {w},{h}"
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><polygon points="{area}" fill="{color}" fill-opacity=".12"/>'
            f'<polyline points="{line_pts}" fill="none" stroke="{color}" stroke-width="1.8"/></svg>')


def fmt_change(d: float, how: str, unit: str) -> str:
    if how == "bp":
        return f"{d * 100:+.0f} bp"
    if how == "pp":
        return f"{d:+.1f} pp"
    if how == "pct":
        return f"{d:+.1f}%"
    return fmt_delta(d, unit)


def kpi(icon: str, title: str, sub: str, iid: str, *, df: pd.DataFrame | None = None, unit: str | None = None,
        how: str = "pp", good: str | None = None, signal: sg.Signal | None = None) -> str:
    """Reference-style KPI card: icon, title, value coloured by signal, change, sparkline, period and previous."""
    if iid not in ROWS.index:
        return ""
    row = ROWS.loc[iid]
    data = (get(iid) if df is None else df).dropna()
    if data.empty:
        return ""
    unit = unit or row["unit"]
    v, prev = float(data["value"].iloc[-1]), (float(data["value"].iloc[-2]) if len(data) > 1 else None)
    prev_date = data["date"].iloc[-2] if len(data) > 1 else None
    if row["frequency"] == "event" and len(data) > 1:  # previous = rate before the last change
        ch = data[data["value"].diff().fillna(0) != 0]
        if not ch.empty:
            before = data[data["date"] < ch["date"].iloc[-1]]
            prev, prev_date = float(before["value"].iloc[-1]), before["date"].iloc[-1]
    level = signal.level if signal and signal.text else "neutral"
    color = LEVEL_COLOR[level]
    change = ""
    if prev is not None and abs(v - prev) > 1e-12:
        d = v - prev
        if how == "pct" and prev:
            d = (v / prev - 1) * 100
        tone = "#64748B" if good is None else ("#15803D" if (d > 0) == (good == "up") else "#B91C1C")
        change = f'<span class="kpi-d" style="color:{tone}">{"▲" if d > 0 else "▼"} {fmt_change(d, how, unit)}</span>'
    short = unit == "percent_of_gdp" or (unit == "percent" and how == "pp")  # "% of GDP" is in the subtitle
    value = f"{v:.1f}%" if short else fmt_value(v, unit)
    when = period_label(data["date"].iloc[-1], row["frequency"])
    prev_txt = ""
    if prev is not None:
        pv = f"{prev:.1f}%" if short else fmt_value(prev, unit)
        prev_txt = f" &nbsp;|&nbsp; Prev: {pv}"
    sig = f'<div class="kpi-f" style="color:{color};margin-top:.15rem">{signal.text}</div>' if signal and signal.text else ""
    return (f'<div class="kpi kpi-{level}"><div class="kpi-top">{svg(icon)}<div><div class="kpi-t">{title}</div>'
            f'<div class="kpi-s">{sub}</div></div></div><div class="kpi-mid"><div><span class="kpi-v" style="color:{color}">'
            f'{value}</span>{change}</div>{spark(data, color if level != "neutral" else "#1D4ED8")}</div>'
            f'<div class="kpi-f">{when}{prev_txt}</div>{sig}</div>')


def kpi_row(items: list[str]):
    html = "".join(i for i in items if i)
    if html:
        st.markdown(f'<div class="kpi-grid">{html}</div>', unsafe_allow_html=True)


def pulse_row(icon: str, name: str, sub: str, iid: str, *, df: pd.DataFrame | None = None, unit: str | None = None,
              how: str = "abs", good: str | None = None, status: tuple[str, str] | None = None) -> str:
    if iid not in ROWS.index:
        return ""
    data = (get(iid) if df is None else df).dropna()
    if data.empty:
        return ""
    row = ROWS.loc[iid]
    unit = unit or row["unit"]
    v = float(data["value"].iloc[-1])
    prev = float(data["value"].iloc[-2]) if len(data) > 1 else None
    dd = ""
    if prev is not None and abs(v - prev) > 1e-12:
        d = (v / prev - 1) * 100 if how == "pct" and prev else v - prev
        tone = "#64748B" if good is None else ("#15803D" if (d > 0) == (good == "up") else "#B91C1C")
        dd = f'<span style="color:{tone}">{"▲" if d > 0 else "▼"} {fmt_change(d, how, unit)}</span>'
    level, label = status or ("neutral", "")
    _, pbg, pfg = LIGHT[level]
    pill = f'<span class="pill" style="background:{pbg};color:{pfg}">{label}</span>' if label else "<span></span>"
    value = f"{v:+.2f} pp" if unit == "pp_spread" else (f"{v:.1f}%" if unit == "percent" else fmt_value(v, unit))
    when = period_label(data["date"].iloc[-1], row["frequency"])
    return (f'<div class="pr">{svg(icon)}<div class="n">{name}<span>{sub}, {when}</span></div>'
            f'<div class="v" style="color:{LEVEL_COLOR[level]}">{value}</div><div class="dd">{dd}</div>{pill}</div>')


def change_status(df: pd.DataFrame, days: int, up: tuple[str, str], down: tuple[str, str], flat=("neutral", "Stable"),
                  tol: float = 0.0) -> tuple[str, str] | None:
    """Status pill from the change over `days` (or vs the previous point when days == 0)."""
    d = df.dropna()
    if len(d) < 2:
        return None
    ago = sg.value_ago(d, days) if days else float(d["value"].iloc[-2])
    if ago is None:
        return None
    ch = float(d["value"].iloc[-1]) - ago
    return flat if abs(ch) <= tol else (up if ch > 0 else down)


def level_status(v, rules: list[tuple[float, str, str]], else_: tuple[str, str]) -> tuple[str, str] | None:
    """First rule (threshold, level, label) with v >= threshold wins."""
    if v is None:
        return None
    for th, lv, lb in rules:
        if v >= th:
            return lv, lb
    return else_


def table_rows(specs: list[tuple]) -> tuple[str, pd.DataFrame]:
    """Indicator table: (name, iid, df or None, unit, frequency label)."""
    html, rows = [], []
    for name, iid, df, unit, freq in specs:
        if iid not in ROWS.index:
            continue
        data = (get(iid) if df is None else df).dropna()
        if data.empty:
            continue
        r = ROWS.loc[iid]
        u = unit or r["unit"]
        f = (lambda x: f"{x:.2f}%") if u == "percent" else (lambda x: fmt_value(x, u))
        cur = (float(data["value"].iloc[-1]), period_label(data["date"].iloc[-1], r["frequency"]))
        prv = (float(data["value"].iloc[-2]), period_label(data["date"].iloc[-2], r["frequency"])) if len(data) > 1 else None
        html.append(f'<tr><td>{name}</td><td><b>{f(cur[0])}</b><small>({cur[1]})</small></td>'
                    f'<td>{f(prv[0]) + "<small>(" + prv[1] + ")</small>" if prv else "–"}</td><td>{freq}</td>'
                    f'<td><a href="{r["source_url"]}" target="_blank">{r["source"]} ↗</a></td></tr>')
        rows.append({"indicator": name, "latest": cur[0], "latest_period": cur[1], "previous": prv[0] if prv else None,
                     "previous_period": prv[1] if prv else None, "frequency": freq, "source": r["source"],
                     "source_url": r["source_url"]})
    return "".join(html), pd.DataFrame(rows)


def growth_inflation_chart(gdp: pd.DataFrame, gdp_name: str, infl: pd.DataFrame, infl_name: str, note: str = ""):
    fig = go.Figure()
    cut = pd.Timestamp(date.today()) - pd.Timedelta(days=DAYS) if DAYS else None
    for df, name, color in [(gdp, gdp_name, "#1E3A8A"), (infl, infl_name, "#16A34A")]:
        if df is None or df.empty:
            continue
        d = df[df["date"] >= cut] if cut is not None else df
        fig.add_trace(go.Scatter(x=d["date"], y=d["value"], name=name, mode="lines+markers",
                                 line=dict(color=color, width=2.4), marker=dict(size=5)))
    fig.add_hline(y=0, line_color="#CBD5E1")
    fig.update_layout(height=330, margin=dict(l=8, r=8, t=10, b=8), yaxis_title="%", hovermode="x unified",
                      legend=dict(orientation="h", y=-0.15, x=0.25), plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
                      font=dict(color=INK, size=12))
    fig.update_xaxes(showgrid=False, linecolor=LINE)
    fig.update_yaxes(gridcolor="#EEF1F5", ticksuffix="%")
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
    if note:
        st.markdown(f'<div class="ml-cap">{note}</div>', unsafe_allow_html=True)


def overview(c: str):
    q = quality(stamp)
    ok = int((q["severity"] == "error").sum()) == 0
    badge = '<span class="ov-ok">✓ Data verified</span>' if ok else '<span class="ov-warn">Data check pending</span>'
    st.markdown(f'<div class="ov-h"><img src="https://flagcdn.com/w80/{FLAGS[c]}.png" alt=""><h1>{c} | <span>Economic overview</span></h1>'
                f'{badge}</div><div class="ov-sub">Key macroeconomic indicators, trends and outlook for {c}, '
                'from official sources.</div>', unsafe_allow_html=True)
    spec = COUNTRY_SPECS[c]()
    kpi_row(spec["kpis"])
    if spec.get("kpis2"):
        kpi_row(spec["kpis2"])
    left, right = st.columns([1.35, 1], gap="medium")
    with left:
        with st.container(border=True):
            st.markdown(f'<h3 style="margin:0;color:{NAVY};font-size:1.25rem">Growth and inflation</h3>'
                        f'<div style="color:{MUTED};font-size:.85rem">{spec["chart_sub"]}</div>', unsafe_allow_html=True)
            growth_inflation_chart(*spec["chart"])
    with right:
        rows = "".join(r for r in spec["pulse"] if r)
        st.markdown(f'<div class="panel"><h3>Economic pulse</h3><div class="ps">High-frequency indicators and trends</div>'
                    f'{rows or "<p>No high-frequency data yet.</p>"}</div>', unsafe_allow_html=True)
    html, table = table_rows(spec["table"])
    with st.container(border=True):
        h1, h2 = st.columns([4, 1])
        h1.markdown(f'<h3 style="margin:0;color:{NAVY};font-size:1.25rem">Explore key indicators</h3>'
                    f'<div style="color:{MUTED};font-size:.85rem">Latest data for {c} with sources</div>',
                    unsafe_allow_html=True)
        h2.download_button("⤓ Download data (CSV)", table.to_csv(index=False).encode("utf-8"),
                           file_name=f"macrolens_{FLAGS[c]}_key_indicators.csv", mime="text/csv", width="stretch")
        st.markdown(f'<table class="kt"><tr><th>INDICATOR</th><th>LATEST</th><th>PREVIOUS</th><th>FREQUENCY</th>'
                    f'<th>SOURCE</th></tr>{html}</table>', unsafe_allow_html=True)
    if spec.get("note"):
        st.markdown(f'<div class="note"><b>ⓘ Summary (rule-based):</b>{spec["note"]}</div>', unsafe_allow_html=True)


def _first(df: pd.DataFrame):
    return None if df is None or df.empty else float(df["value"].iloc[-1])


def spec_india():
    infl, liq = last("in_cpi_inflation"), last("in_net_liquidity")
    stance, rupee = sg.policy_stance(get("in_repo_rate")), sg.local_currency(get("inr_usd"))
    g = last("in_gdp_growth")
    credit = last("in_bank_credit_yoy")
    parts = [stance.text and f"{stance.text}",
             infl is not None and f"inflation {infl:.2f}% is {sg.inflation_band(infl, 2, 6, 4).text}",
             g is not None and f"real GDP growth {g:.1f}% ({period_label(get('in_gdp_growth')['date'].iloc[-1], 'quarterly')})",
             rupee.text, sg.liquidity(liq).text]
    return {
        "kpis": [kpi("gdp", "GDP growth", "Real, YoY (2022-23 base)", "in_gdp_growth", good="up", signal=sg.growth(g, 7, 5)),
                 kpi("infl", "Inflation", "CPI, YoY (2024 base)", "in_cpi_inflation", good="down",
                     signal=sg.inflation_band(infl, 2, 6, 4)),
                 kpi("jobs", "Unemployment", "PLFS, CWS, age 15+", "in_unemployment", good="down",
                     signal=sg.trend_lower_is_better(get("in_unemployment"), 180, "unemployment")),
                 kpi("debt", "Public debt", "General govt, % of GDP (IMF)", "in_gov_debt_gdp", good="down",
                     signal=sg.at_most(last("in_gov_debt_gdp"), 60, "the 60% FRBM anchor"))],
        "kpis2": [kpi("bank", "Repo rate", "RBI policy rate", "in_repo_rate", how="bp", signal=stance),
                  kpi("fx", "Rupee", "₹ per US$ (FBIL reference)", "inr_usd", how="pct", good="down", signal=rupee),
                  kpi("yield", "10Y G-sec yield", "FBIL par yield", "in_10y", how="bp", signal=sg.yield_move(get("in_10y"))),
                  kpi("shield", "Forex reserves", "RBI, weekly", "in_fx_reserves", how="pct", good="up",
                      signal=sg.reserves(get("in_fx_reserves")))],
        "chart_sub": "Real GDP growth (quarterly, YoY) and CPI inflation (monthly, YoY)",
        "chart": (get("in_gdp_growth"), "Real GDP growth (YoY)", get("in_cpi_inflation"), "CPI inflation (YoY)",
                  "Source: MoSPI. CPI 2024 base from Jan 2026; GDP 2022-23 base."),
        "pulse": [pulse_row("drop", "Banking liquidity", "Net LAF, RBI", "in_net_liquidity",
                            status=("good", "Surplus") if liq is not None and liq < 0 else ("watch", "Deficit")),
                  pulse_row("shield", "Forex reserves", "US$, weekly", "in_fx_reserves", how="pct", good="up",
                            status=change_status(get("in_fx_reserves"), 28, ("good", "Rising"), ("watch", "Falling"))),
                  pulse_row("ship", "Trade balance", "Goods + services", "in_total_trade_balance", good="up",
                            status=change_status(get("in_total_trade_balance"), 0, ("good", "Narrowing"), ("watch", "Widening"))),
                  pulse_row("credit", "Bank credit growth", "YoY", "in_bank_credit_yoy", how="pp", good="up",
                            status=level_status(credit, [(12, "good", "Strong"), (8, "watch", "Moderate")], ("bad", "Weak"))),
                  pulse_row("scale", "Current account", "Monthly BoP", "in_current_account", good="up",
                            status=("good", "Surplus") if (last("in_current_account") or -1) >= 0 else
                            change_status(get("in_current_account"), 0, ("good", "Improving"), ("watch", "Deteriorating"))),
                  pulse_row("flow", "FDI into India, net", "Monthly BoP", "in_fdi_india_net", good="up",
                            status=("good", "Inflow") if (last("in_fdi_india_net") or 0) > 0 else ("bad", "Outflow"))],
        "table": [("GDP (real growth, YoY)", "in_gdp_growth", None, None, "Quarterly"),
                  ("CPI inflation (YoY)", "in_cpi_inflation", None, None, "Monthly"),
                  ("Food inflation (YoY)", "in_food_inflation", None, None, "Monthly"),
                  ("Unemployment rate (PLFS)", "in_unemployment", None, None, "Monthly"),
                  ("Policy repo rate", "in_repo_rate", None, None, "As announced"),
                  ("10Y G-sec yield", "in_10y", None, None, "Daily"),
                  ("Rupee per US$", "inr_usd", None, None, "Daily"),
                  ("Forex reserves", "in_fx_reserves", None, None, "Weekly"),
                  ("Trade balance (goods + services)", "in_total_trade_balance", None, None, "Monthly"),
                  ("Current account balance", "in_current_account", None, None, "Monthly"),
                  ("Fiscal deficit, % of GDP (latest RE/BE)", "in_fiscal_deficit_gdp_est", None, None, "Annual"),
                  ("Public debt, % of GDP (IMF)", "in_gov_debt_gdp", None, None, "Annual")],
        "note": " " + "; ".join(p for p in parts if p) + ".",
    }


def spec_us():
    cpi, core = yoy("us_cpi"), yoy("us_core_pce")
    stance = sg.policy_stance(get("us_policy_rate"), "Fed")
    slope = diff("us_10y", "us_2y")
    parts = [stance.text, not cpi.empty and f"CPI inflation {_first(cpi):.1f}% is {sg.inflation_target(_first(cpi)).text}",
             has("us_unemployment") and f"unemployment {last('us_unemployment'):.1f}%"]
    return {
        "kpis": [kpi("gdp", "GDP growth", "Real, q/q annualised", "us_gdp_growth", good="up",
                     signal=sg.growth(last("us_gdp_growth"), 2, 0)),
                 kpi("infl", "Inflation", "CPI, YoY (derived)", "us_cpi", df=cpi, unit="percent", good="down",
                     signal=sg.inflation_target(_first(cpi))),
                 kpi("jobs", "Unemployment", "BLS, seasonally adjusted", "us_unemployment", good="down",
                     signal=sg.trend_lower_is_better(get("us_unemployment"), 180, "unemployment")),
                 kpi("debt", "Public debt", "General govt, % of GDP (IMF)", "us_gov_debt_gdp", good="down")],
        "kpis2": [kpi("bank", "Fed funds rate", "Target, upper bound", "us_policy_rate", how="bp", signal=stance),
                  kpi("fx", "Dollar index", "Broad, Federal Reserve", "us_dollar_broad", how="pct"),
                  kpi("yield", "10Y Treasury", "Constant maturity", "us_10y", how="bp", signal=sg.yield_move(get("us_10y"))),
                  kpi("infl", "Core PCE", "YoY (derived), Fed target 2%", "us_core_pce", df=core, unit="percent", good="down",
                      signal=sg.inflation_target(_first(core)))],
        "chart_sub": "Real GDP growth (q/q annualised) and CPI inflation (YoY, derived)",
        "chart": (get("us_gdp_growth"), "Real GDP growth (q/q SAAR)", cpi, "CPI inflation (YoY)", "Source: FRED (BEA, BLS)."),
        "pulse": [pulse_row("bank", "Fed balance sheet", "Total assets, weekly", "us_fed_balance_sheet", how="pct",
                            status=change_status(get("us_fed_balance_sheet"), 28, ("neutral", "Expanding"), ("neutral", "Shrinking"))),
                  pulse_row("drop", "Bank reserves", "At the Fed, weekly", "us_bank_reserves", how="pct", good="up"),
                  pulse_row("flow", "Overnight reverse repo", "Fed ON RRP", "us_reverse_repo"),
                  pulse_row("yield", "Yield curve, 10Y − 2Y", "Derived", "us_10y", df=slope, unit="pp_spread", how="bp",
                            status=("good", "Positive") if (_first(slope) or 0) >= 0 else ("watch", "Inverted")),
                  pulse_row("credit", "M2 money stock", "Monthly", "us_m2", how="pct")],
        "table": [("GDP (real, q/q SAAR)", "us_gdp_growth", None, None, "Quarterly"),
                  ("CPI inflation (YoY, derived)", "us_cpi", cpi, "percent", "Monthly"),
                  ("Core PCE inflation (YoY, derived)", "us_core_pce", core, "percent", "Monthly"),
                  ("Unemployment rate", "us_unemployment", None, None, "Monthly"),
                  ("Fed funds target (upper)", "us_policy_rate", None, None, "As announced"),
                  ("10Y Treasury yield", "us_10y", None, None, "Daily"),
                  ("Public debt, % of GDP (IMF)", "us_gov_debt_gdp", None, None, "Annual"),
                  ("Federal debt, % of GDP", "us_federal_debt_gdp", None, None, "Quarterly")],
        "note": " " + "; ".join(p for p in parts if p) + ".",
    }


def spec_ea():
    hicp, gdp = yoy("ea_hicp"), yoy("ea_gdp_real", 4)
    stance = sg.policy_stance(get("ea_ecb_deposit_rate"), "ECB")
    parts = [stance.text, not hicp.empty and f"HICP inflation {_first(hicp):.1f}% is {sg.inflation_target(_first(hicp)).text}",
             not gdp.empty and f"real GDP growth {_first(gdp):.1f}% YoY"]
    return {
        "kpis": [kpi("gdp", "GDP growth", "Real, YoY (derived)", "ea_gdp_real", df=gdp, unit="percent", good="up",
                     signal=sg.growth(_first(gdp), 1.5, 0)),
                 kpi("infl", "Inflation", "HICP, YoY (derived)", "ea_hicp", df=hicp, unit="percent", good="down",
                     signal=sg.inflation_target(_first(hicp))),
                 kpi("bank", "ECB deposit rate", "Main policy signal", "ea_ecb_deposit_rate", how="bp", signal=stance),
                 kpi("yield", "Germany 10Y", "Bund, monthly average", "de_10y", how="bp")],
        "kpis2": [kpi("fx", "EUR/USD", "US$ per euro", "usd_eur", how="pct", good="up")],
        "chart_sub": "Real GDP growth and HICP inflation (YoY, derived)",
        "chart": (gdp, "Real GDP growth (YoY)", hicp, "HICP inflation (YoY)", "Source: FRED (Eurostat, ECB)."),
        "pulse": [pulse_row("fx", "EUR/USD", "Daily", "usd_eur", how="pct",
                            status=change_status(get("usd_eur"), 30, ("good", "Euro firmer"), ("watch", "Euro weaker"))),
                  pulse_row("yield", "Germany 10Y", "Monthly average", "de_10y", how="bp"),
                  pulse_row("bank", "ECB refi rate", "Main refinancing", "ea_ecb_mro_rate", how="bp")],
        "table": [("Real GDP growth (YoY, derived)", "ea_gdp_real", gdp, "percent", "Quarterly"),
                  ("HICP inflation (YoY, derived)", "ea_hicp", hicp, "percent", "Monthly"),
                  ("ECB deposit rate", "ea_ecb_deposit_rate", None, None, "As announced"),
                  ("Germany 10Y yield", "de_10y", None, None, "Monthly"),
                  ("EUR/USD", "usd_eur", None, None, "Daily")],
        "note": " " + "; ".join(p for p in parts if p) + ". Euro area unemployment and debt are not shown: no current "
                "official series we can fetch automatically.",
    }


def spec_cn():
    g = last("cn_gdp_growth")
    parts = [g is not None and f"real GDP growth {g:.1f}% (IMF, annual)",
             has("cn_inflation") and f"CPI inflation {last('cn_inflation'):.1f}% (IMF, annual)"]
    return {
        "kpis": [kpi("gdp", "GDP growth", "Real, annual (IMF)", "cn_gdp_growth", good="up", signal=sg.growth(g, 5, 3)),
                 kpi("infl", "Inflation", "CPI, annual average (IMF)", "cn_inflation"),
                 kpi("jobs", "Unemployment", "ILO modelled", "cn_unemployment_ilo", good="down"),
                 kpi("debt", "Public debt", "General govt, % of GDP (IMF)", "cn_gov_debt_gdp", good="down")],
        "kpis2": [kpi("fx", "Yuan", "CNY per US$", "cny_usd", how="pct", good="down",
                      signal=sg.local_currency(get("cny_usd"), "yuan", 30))],
        "chart_sub": "Real GDP growth and CPI inflation (annual, IMF)",
        "chart": (get("cn_gdp_growth"), "Real GDP growth", get("cn_inflation"), "CPI inflation", "Source: IMF World Economic Outlook."),
        "pulse": [pulse_row("fx", "CNY per US$", "Daily", "cny_usd", how="pct",
                            status=change_status(get("cny_usd"), 30, ("watch", "Yuan weaker"), ("good", "Yuan firmer"))),
                  pulse_row("gdp", "IMF growth projection", "Next year", "cn_gdp_growth_imf_proj",
                            df=get("cn_gdp_growth_imf_proj").head(1)),
                  pulse_row("scale", "Fiscal balance", "% of GDP (IMF)", "cn_gov_balance_gdp", unit="percent_of_gdp")],
        "table": [("Real GDP growth (IMF)", "cn_gdp_growth", None, None, "Annual"),
                  ("CPI inflation (IMF)", "cn_inflation", None, None, "Annual"),
                  ("Unemployment (ILO)", "cn_unemployment_ilo", None, None, "Annual"),
                  ("Public debt, % of GDP (IMF)", "cn_gov_debt_gdp", None, None, "Annual"),
                  ("CNY per US$", "cny_usd", None, None, "Daily")],
        "note": " " + "; ".join(p for p in parts if p) + ". China monthly CPI is not shown: no current official series "
                "we can fetch automatically.",
    }


def spec_jp():
    gdp = yoy("jp_gdp_real", 4)
    parts = [not gdp.empty and f"real GDP growth {_first(gdp):.1f}% YoY",
             has("jp_10y") and f"10Y JGB {last('jp_10y'):.2f}%",
             has("usd_jpy") and f"¥{last('usd_jpy'):.2f} per US$"]
    return {
        "kpis": [kpi("gdp", "GDP growth", "Real, YoY (derived)", "jp_gdp_real", df=gdp, unit="percent", good="up",
                     signal=sg.growth(_first(gdp), 1, 0)),
                 kpi("infl", "Inflation", "CPI, annual (IMF)", "jp_inflation", signal=sg.inflation_target(last("jp_inflation"))),
                 kpi("jobs", "Unemployment", "Ages 15-64", "jp_unemployment", good="down",
                     signal=sg.trend_lower_is_better(get("jp_unemployment"), 180, "unemployment")),
                 kpi("debt", "Public debt", "General govt, % of GDP (IMF)", "jp_gov_debt_gdp", good="down")],
        "kpis2": [kpi("yield", "10Y JGB", "Monthly average", "jp_10y", how="bp"),
                  kpi("fx", "Yen", "¥ per US$", "usd_jpy", how="pct", good="down",
                      signal=sg.local_currency(get("usd_jpy"), "yen", 30))],
        "chart_sub": "Real GDP growth (YoY, derived) and CPI inflation (annual, IMF)",
        "chart": (gdp, "Real GDP growth (YoY)", get("jp_inflation"), "CPI inflation (annual)", "Source: FRED, IMF."),
        "pulse": [pulse_row("fx", "USD/JPY", "Daily", "usd_jpy", how="pct",
                            status=change_status(get("usd_jpy"), 30, ("watch", "Yen weaker"), ("good", "Yen firmer"))),
                  pulse_row("yield", "10Y JGB", "Monthly average", "jp_10y", how="bp"),
                  pulse_row("drop", "3-month interbank rate", "Monthly", "jp_3m", how="bp")],
        "table": [("Real GDP growth (YoY, derived)", "jp_gdp_real", gdp, "percent", "Quarterly"),
                  ("CPI inflation (IMF)", "jp_inflation", None, None, "Annual"),
                  ("Unemployment rate", "jp_unemployment", None, None, "Monthly"),
                  ("10Y JGB yield", "jp_10y", None, None, "Monthly"),
                  ("Yen per US$", "usd_jpy", None, None, "Daily"),
                  ("Public debt, % of GDP (IMF)", "jp_gov_debt_gdp", None, None, "Annual")],
        "note": " " + "; ".join(p for p in parts if p) + ". The Bank of Japan policy rate is not shown: no current "
                "official series we can fetch automatically.",
    }


COUNTRY_SPECS = {"India": spec_india, "United States": spec_us, "Euro area": spec_ea, "China": spec_cn, "Japan": spec_jp}
VIEWS = {"India": india, "United States": united_states, "Euro area": euro_area, "China": china, "Japan": japan}


def countries_page():
    st.markdown(f'<div class="ov-h"><h1>Countries</h1></div><div class="ov-sub">Snapshot of every country we track. '
                'Open one for its full overview.</div>', unsafe_allow_html=True)
    for c in COUNTRY_LIST:
        spec = COUNTRY_SPECS[c]()
        with st.container(border=True):
            a, b = st.columns([5, 1])
            a.markdown(f'<div class="ov-h" style="margin:0"><img src="https://flagcdn.com/w80/{FLAGS[c]}.png" alt="">'
                       f'<h1 style="font-size:1.3rem">{c}</h1></div>', unsafe_allow_html=True)
            b.button("Open overview", key=f"open_{c}", width="stretch", on_click=go_to,
                     args=("Overview",), kwargs={"country_pick": c})
            kpi_row(spec["kpis"])


def compare_page():
    st.markdown(f'<div class="ov-h"><h1>Compare</h1></div><div class="ov-sub">Same indicators side by side.</div>',
                unsafe_allow_html=True)
    sel = st.multiselect("Countries", COUNTRY_LIST, key="compare_set")
    codes = {{"India": "IN", "United States": "US", "Euro area": "EA", "China": "CN", "Japan": "JP"}[c] for c in sel}
    compare(codes)


# ======================= daily briefing =======================
# Written each morning (08:40 IST) by the owner's scheduled AI task (ChatGPT since 2026-11-22) and pushed to the `claude/briefings`
# branch as briefings/YYYY-MM-DD.md plus briefings/index.json. The site reads them straight from
# GitHub, so new briefings appear without a redeploy. A local briefings/ folder is used as fallback.
BRIEF_RAW = "https://raw.githubusercontent.com/suchit-ashar/macrolens/refs/heads/claude/briefings/briefings/"
BRIEF_LOCAL = Path(__file__).resolve().parent.parent / "briefings"


@st.cache_data(ttl=900, show_spinner=False)
def briefing_index() -> list[dict]:
    import json
    import requests
    try:
        r = requests.get(BRIEF_RAW + "index.json", timeout=15)
        if r.status_code == 200:
            items = r.json()
            if isinstance(items, list):
                return sorted([i for i in items if isinstance(i, dict) and i.get("date")],
                              key=lambda i: i["date"], reverse=True)
    except (requests.RequestException, ValueError):
        pass
    if BRIEF_LOCAL.exists():  # fallback: local folder (development, or before the first run)
        idx = BRIEF_LOCAL / "index.json"
        if idx.exists():
            try:
                return sorted(json.loads(idx.read_text(encoding="utf-8")), key=lambda i: i["date"], reverse=True)
            except ValueError:
                pass
        return [{"date": p.stem, "file": p.name, "title": f"Daily Market Briefing — {p.stem}", "summary": ""}
                for p in sorted(BRIEF_LOCAL.glob("20*.md"), reverse=True)]
    return []


@st.cache_data(ttl=900, show_spinner=False)
def briefing_text(file: str) -> str | None:
    import requests
    if not file or "/" in file or "\\" in file or not file.endswith(".md"):
        return None
    try:
        r = requests.get(BRIEF_RAW + file, timeout=15)
        if r.status_code == 200:
            return r.content.decode("utf-8-sig", errors="replace")
    except requests.RequestException:
        pass
    p = BRIEF_LOCAL / file
    return p.read_text(encoding="utf-8-sig") if p.exists() else None




def briefing_card():
    idx = briefing_index()
    if not idx:
        return
    latest = idx[0]
    with st.container(border=True):
        a, b = st.columns([5, 1])
        a.markdown(f'<h3 style="margin:0;color:{NAVY};font-size:1.25rem">📰 Today\'s market briefing</h3>'
                   f'<div style="color:{MUTED};font-size:.85rem">{latest["date"]} · AI-generated at 08:40 IST</div>',
                   unsafe_allow_html=True)
        b.button("Read briefing", on_click=go_to, args=("Daily briefing",), width="stretch")
        if latest.get("summary"):
            st.markdown(latest["summary"])


def bsection(key: str, title: str, body: str, icon: str | None = None, border: bool = True):
    """One briefing card: icon heading + the section's Markdown (rendered without raw HTML)."""
    with st.container(border=border, key=key):
        st.markdown(f'<div class="bh">{svg(icon or bf.icon_for(title))}{html_escape(title)}</div>', unsafe_allow_html=True)
        st.markdown(body or "_Not included in this briefing._")


def briefing_page():
    st.markdown('<div class="ov-h"><h1>Daily Market <span>Briefing</span></h1></div>'
                '<div class="ov-sub">Global and Indian markets, every morning before the Indian open.</div>',
                unsafe_allow_html=True)
    idx = briefing_index()
    if not idx:
        st.info("The first briefing will appear after the next 08:40 IST run.")
        return
    dates = [i["date"] for i in idx]
    c1, c2 = st.columns([1.25, 3], vertical_alignment="bottom")
    pick = c1.selectbox("Briefing date", dates, index=0, key="brief_date",
                        format_func=lambda d: f"{pd.Timestamp(d):%A, %d %b %Y}" + ("  (latest)" if d == dates[0] else ""))
    item = next(i for i in idx if i["date"] == pick)
    text = briefing_text(item.get("file") or f"{pick}.md")
    if text is None:
        st.warning("This briefing could not be loaded right now. Try again in a minute.")
        return
    b = bf.split_briefing(text)
    if b.cutoff:  # the file says "Data cut-off: ..."; the page shows it as "As of ..."
        c2.caption(re.sub(r"data cut-?off(\s+timestamp)?\s*:?", "As of", b.cutoff, flags=re.IGNORECASE))

    # Market snapshot from MacroLens's own feeds (not from the AI text), so the headline numbers are verified data.
    kpi_row([kpi("yield", "US 10Y Treasury", "Yield, constant maturity (FRED)", "us_10y", how="bp",
                 signal=sg.yield_move(get("us_10y"))),
             kpi("drop", "Brent crude", "US$ per barrel, spot (FRED)", "brent", how="pct"),
             kpi("fx", "Rupee", "₹ per US$ (FBIL reference)", "inr_usd", how="pct", good="down",
                 signal=sg.local_currency(get("inr_usd"))),
             kpi("globe", "US dollar index", "Broad, Federal Reserve", "us_dollar_broad", how="pct")])
    st.markdown('<div class="bsnap">Snapshot: latest official data in MacroLens (dates on each card). '
                'The briefing below is written separately by AI.</div>', unsafe_allow_html=True)

    execsum = b.take("executive summary")
    if execsum is None:  # unexpected format: show the file as it is
        with st.container(border=True, key="brief"):
            st.markdown(text)
        return
    events = b.take("what to watch", "today's key events", "key events")
    left, right = st.columns([1.35, 1], gap="medium")
    with left:
        bsection("bexec", "Executive Summary", execsum[1], "doc", border=False)
    with right:
        bsection("bsec_events", "Today's key events", events[1] if events else "", "calendar")

    takeaways = [s for s in (b.take("3 things"), b.take("2 risks", "risks"), b.take("2 opportunities", "opportunities"))
                 if s]
    if takeaways:
        for col, (i, (h, body)) in zip(st.columns(len(takeaways), gap="medium"), enumerate(takeaways)):
            with col:
                bsection(f"bsec_take{i}", h, body)
    pair_secs = [s for s in (b.take("today's market narrative", "market narrative"), b.take("1 key question", "key question"))
                 if s]
    if pair_secs:
        for col, (i, (h, body)) in zip(st.columns(len(pair_secs), gap="medium"), enumerate(pair_secs)):
            with col:
                bsection(f"bsec_pair{i}", h, body)
    for i, (h, body) in enumerate(b.sections):
        bsection(f"bsec_{i}", h, body)
    if b.notes:
        st.caption(b.notes)


def data_sources_page():
    st.markdown(f'<div class="ov-h"><h1>Data sources</h1></div>', unsafe_allow_html=True)
    st.markdown(f"{summary['date'].notna().sum()} series from RBI, MoSPI, FBIL, Union Budget, CGA, Ministry of Commerce, "
                "FRED, IMF and the World Bank, fetched automatically every morning at about 07:00 IST. FBIL market data "
                "(bond yields, T-bills, MIBOR) reaches the public with about a one-week lag; the latest rupee rates come "
                "from the RBI home page. Derived values (YoY %, spreads, shares, real rate) are computed by MacroLens and "
                "labelled. IMF projections and budget estimates are kept as separate, labelled series.")
    q = quality(stamp)
    st.markdown(f"**Quality checks:** {int((q['severity'] == 'error').sum())} errors, {int((q['severity'] == 'warn').sum())} "
                "warnings (a warning usually marks a real market event).")
    if not q.empty:
        st.dataframe(q, width="stretch", hide_index=True)
    table = summary[["indicator_id", "name", "topic", "country", "value", "unit", "date", "frequency", "source",
                     "source_url", "fetched_at"]]
    st.dataframe(table, width="stretch", hide_index=True,
                 column_config={"source_url": st.column_config.LinkColumn("source link")})
    pick = st.selectbox("Download one series", summary["indicator_id"], format_func=lambda i: f"{i} — {ROWS.loc[i, 'name']}")
    st.download_button("Download CSV", get(pick).to_csv(index=False).encode("utf-8"), file_name=f"{pick}.csv", mime="text/csv")


if page == "Overview":
    overview(country)
    briefing_card()
elif page == "Daily briefing":
    briefing_page()
elif page == "Countries":
    countries_page()
elif page == "Indicators":
    st.markdown(f'<div class="ov-h"><img src="https://flagcdn.com/w80/{FLAGS[country]}.png" alt=""><h1>{country} | '
                f'<span>Indicators</span></h1></div><div class="ov-sub">Every series we track for {country}, by topic.</div>',
                unsafe_allow_html=True)
    VIEWS[country]()
elif page == "Compare":
    compare_page()
else:
    data_sources_page()
st.caption("Data from the official sources linked on each chart; figures may be revised by the source.")
