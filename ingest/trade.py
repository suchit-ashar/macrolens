"""India's monthly foreign trade (US$ billion) from the Ministry of Commerce press release on PIB.

Around the 15th of every month the Ministry of Commerce & Industry publishes "Table 1: Trade
during <Month YYYY>" (merchandise, services, total; exports and imports) for the previous
month. Services for the latest month are an estimate (RBI data arrive later). The table also
restates the same month one year earlier, so each release gives two months:
  - the reference month M (first estimate),
  - month M-12 (revised: final merchandise data and RBI services data).
When several releases give a value for the same month, the newest release wins.

Trade balances are always computed here as exports - imports: the printed balance sometimes
loses its minus sign (October 2026 release prints "20.09" for -20.08).

Finding releases: PIB's "all releases" page (www.pib.gov.in/allRel.aspx) is an ASP.NET form;
posting it with ministry 16 (Commerce & Industry), day 0 (all) and a month/year lists that
month's releases. Candidates are picked by title, then confirmed by parsing the release page
(PressReleaseIframePage.aspx: the PressReleaseDetail page has no tables).

Each parsed release is cached as data/raw/trade/<YYYY-MM>_<PRID>.json (+ the raw .html), where
YYYY-MM is the reference month, so every fetch() reads the cache and downloads only missing
months.

source_series: "pib:<series>" with <series> one of SERIES below.

Why PIB and not tradestat.commerce.gov.in: PIB gives merchandise, services and totals in one
consistent table, includes the latest month (tradestat lags a month and has merchandise only),
and its archive is navigable back to 2023 with the same table layout.
"""
import html
import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from ingest.http import USER_AGENT, FetchError, get

BASE = "https://www.pib.gov.in"  # pib.gov.in redirects there, and a redirected POST loses its form
LIST_URL = f"{BASE}/allRel.aspx?reg=3&lang=1"
RELEASE_URL = f"{BASE}/PressReleaseIframePage.aspx?PRID={{prid}}"
COMMERCE_MINISTRY = "16"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "trade"
BACKFILL_START = date(2024, 1, 1)  # first reference month downloaded on a first run
PAUSE = 0.3

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                      "august", "september", "october", "november", "december"], 1)}
# stored keys in a parsed release, per month
FIELDS = ["merch_exports", "merch_imports", "services_exports", "services_imports",
          "total_exports", "total_imports"]
BALANCES = {"merch_balance": ("merch_exports", "merch_imports"),
            "services_balance": ("services_exports", "services_imports"),
            "total_balance": ("total_exports", "total_imports")}
SERIES = FIELDS + list(BALANCES)

# Titles seen: "The cumulative exports (merchandise & services) during April-October 2026-27 are
# estimated at ...", "India's overall exports in November 2023 is estimated at USD ...",
# "India's merchandise exports in Jan 2024 registers 3.12 % growth at USD 36.92 Billion ..."
TITLE_RE = re.compile(r"export.*\b(estimated|cumulative|overall|merchandise)\b"
                      r"|\b(cumulative|overall|total|merchandise)\b.*export", re.I)

# per-process memos, so fetching the eight series in one run downloads each page once
_listing_memo: dict[tuple[int, int], list[tuple[str, str]]] = {}
_release_memo: dict[str, tuple[dict | None, str]] = {}


def _today() -> date:
    return datetime.now(timezone.utc).date()


class TradeError(FetchError):
    pass


# ----------------------------------------------------------------------------- parsing

def _cells(row_html: str) -> list[str]:
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
            for c in re.findall(r"<t[dh]\b.*?</t[dh]>", row_html, re.S | re.I)]


def _num(s: str) -> float | None:
    s = s.replace(",", "").replace("(-)", "-").replace(" ", "")
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else None


HEADER_RE = re.compile(r"([A-Za-z]+)\s*(\d{4})\s*\(\s*(?:US\$|USD)\s*Billion\s*\)", re.I)


def _month_header(cell: str) -> str | None:
    """'October 2026 (US$ Billion)' -> '2026-10'; cumulative headers ('April-October ...') -> None."""
    m = HEADER_RE.fullmatch(cell.strip())
    if not m or m.group(1).lower() not in MONTHS:
        return None
    return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}"


def parse_release(text: str) -> dict | None:
    """Parse the monthly trade table of a release page. None if the page has no such table.

    -> {"month": "2026-10", "release_date": "2026-11-13",
        "values": {"2026-10": {"merch_exports": 49.47, ...}, "2025-10": {...}}}
    """
    # innermost tables only (the page also wraps the whole text in a layout table)
    for tbl in re.findall(r"<table\b(?:(?!<table\b).)*?</table>", text, re.S | re.I):
        rows = [_cells(r) for r in re.findall(r"<tr\b.*?</tr>", tbl, re.S | re.I)]
        if not rows:
            continue
        months = [_month_header(c) for c in rows[0]]
        months = [m for m in months if m]
        if not months:
            continue
        values = {m: {} for m in months}
        section = None
        for cells in rows[1:]:
            for c in cells:
                low = c.lower()
                if low.startswith("merchandise"):
                    section = "merch"
                elif low.startswith("services"):
                    section = "services"
                elif low.startswith(("total trade", "overall trade")):
                    section = "total"
                elif low.startswith("trade balance"):
                    section = None
            flow = next((c.lower() for c in cells if c.lower() in ("exports", "imports")), None)
            nums = [n for n in (_num(c) for c in cells) if n is not None]
            if section and flow and len(nums) >= len(months):
                for m, v in zip(months, nums[-len(months):]):
                    values[m][f"{section}_{flow}"] = v
        if all(set(FIELDS) <= set(v) for v in values.values()):
            rd = re.search(r"(\d{1,2})\s+([A-Z]{3})\s+(\d{4})\s+\d{1,2}:\d{2}\s*[AP]M", text)
            release_date = None
            if rd:
                release_date = datetime.strptime(" ".join(rd.groups()).title(), "%d %b %Y").date().isoformat()
            return {"month": months[0], "release_date": release_date, "values": values}
    return None


# ----------------------------------------------------------------------------- network

def _post(session, url: str, data: dict, retries: int = 3, timeout: int = 60):
    last_err = None
    for attempt in range(retries):
        try:
            r = session.post(url, data=data, headers={"User-Agent": USER_AGENT, "Referer": url},
                             timeout=timeout)
            if r.status_code == 200:
                return r
            last_err = f"HTTP {r.status_code}"
            if 400 <= r.status_code < 500:
                break
        except requests.RequestException as e:
            last_err = str(e)
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    raise TradeError(f"POST {url} failed: {last_err}")


def _decode(r) -> str:
    return r.content.decode("utf-8", errors="replace")


def _form_fields(page: str) -> dict:
    return {n: html.unescape(v) for n, v in
            re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page)}


def parse_listing(page: str) -> list[tuple[str, str]]:
    """-> [(prid, title)] from a PIB release listing page."""
    out = []
    for attrs, inner in re.findall(r"<a\b([^>]*PRID=\d+[^>]*)>(.*?)</a>", page, re.S | re.I):
        prid = re.search(r"PRID=(\d+)", attrs).group(1)
        t = re.search(r"title=(['\"])(.*?)\1", attrs, re.S)
        title = t.group(2) if t else re.sub(r"<[^>]+>", "", inner)
        out.append((prid, re.sub(r"\s+", " ", html.unescape(title)).strip()))
    return out


def list_releases(year: int, month: int, session, state: dict) -> list[tuple[str, str]]:
    """Commerce & Industry releases published in one calendar month (memoised per process)."""
    if (year, month) in _listing_memo:
        return _listing_memo[(year, month)]
    if "fields" not in state:
        state["fields"] = _form_fields(_decode(get(LIST_URL, session=session)))
        if "__VIEWSTATE" not in state["fields"]:
            raise TradeError("PIB release list: no ASP.NET form state on the page")
    data = {**state["fields"], "__EVENTTARGET": "", "__EVENTARGUMENT": "",
            "ctl00$Bar1$ddlregion": "3", "ctl00$Bar1$ddlLang": "1",
            "ctl00$ContentPlaceHolder1$ddlMinistry": COMMERCE_MINISTRY,
            "ctl00$ContentPlaceHolder1$ddlday": "0",
            "ctl00$ContentPlaceHolder1$ddlMonth": str(month),
            "ctl00$ContentPlaceHolder1$ddlYear": str(year)}
    page = _decode(_post(session, LIST_URL, data))
    sel = re.search(r'name="ctl00\$ContentPlaceHolder1\$ddlMinistry".*?</select>', page, re.S)
    if not sel or f'selected="selected" value="{COMMERCE_MINISTRY}"' not in sel.group(0):
        raise TradeError(f"PIB release list for {year}-{month:02d}: the ministry filter was not applied")
    state["requests"] = state.get("requests", 0) + 1
    _listing_memo[(year, month)] = parse_listing(page)
    return _listing_memo[(year, month)]


# ----------------------------------------------------------------------------- cache

def _load_cache() -> list[dict]:
    out = []
    for p in sorted(RAW_DIR.glob("*_*.json")) if RAW_DIR.exists() else []:
        try:
            rel = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rel, dict) and rel.get("values"):
            out.append(rel)
    return out


def _save(rel: dict, page: str):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{rel['month']}_{rel['prid']}"
    (RAW_DIR / f"{stem}.html").write_text(page, encoding="utf-8")
    (RAW_DIR / f"{stem}.json").write_text(json.dumps(rel, indent=1), encoding="utf-8")


def _month_add(d: date, n: int) -> date:
    k = d.year * 12 + d.month - 1 + n
    return date(k // 12, k % 12 + 1, 1)


def _download_missing(needed: list[date], have: set[str], session, save_raw: bool) -> list[dict]:
    """Find and parse the release for every needed reference month not in `have`."""
    today = _today()
    state, new = {}, []
    for ref in needed:
        if ref.strftime("%Y-%m") in have:
            continue
        # The release for month M comes out mid-month M+1 (occasionally later)
        for lm in (_month_add(ref, 1), _month_add(ref, 2)):
            if lm > today:
                break
            releases = list_releases(lm.year, lm.month, session, state)
            cands = [p for p, t in releases if TITLE_RE.search(t)]
            found = None
            for prid in cands:
                if prid in _release_memo:  # already looked at in this process
                    rel, page = _release_memo[prid]
                else:
                    page = _decode(get(RELEASE_URL.format(prid=prid), session=session))
                    state["requests"] = state.get("requests", 0) + 1
                    time.sleep(PAUSE)
                    rel = parse_release(page)
                    _release_memo[prid] = (rel, page)
                if rel is None:
                    continue
                rel.update(prid=prid, title=dict(releases)[prid], url=RELEASE_URL.format(prid=prid))
                if rel["month"] not in have:
                    have.add(rel["month"])
                    new.append(rel)
                    if save_raw:
                        _save(rel, page)
                if rel["month"] == ref.strftime("%Y-%m"):
                    found = rel
            if found:
                break
    return new


def load_releases(since=None, session=None, save_raw: bool = True) -> list[dict]:
    """Cached + newly downloaded releases, oldest release first."""
    session = session or requests.Session()
    cached = _load_cache()
    have = {r["month"] for r in cached}
    today = _today()
    start = BACKFILL_START if since is None else max(BACKFILL_START, _month_add(date(since.year, since.month, 1), 1))
    last = _month_add(today.replace(day=1), -1)
    needed, m = [], start
    while m <= last:
        needed.append(m)
        m = _month_add(m, 1)
    rels = cached + _download_missing(needed, have, session, save_raw)
    return sorted(rels, key=lambda r: (r.get("release_date") or "", r["month"], int(r.get("prid") or 0)))


def combine(releases: list[dict], series: str) -> pd.DataFrame:
    """One value per month; a newer release overrides an older one."""
    vals = {}
    for rel in releases:  # oldest first, so newer releases overwrite
        for month, v in rel["values"].items():
            if series in BALANCES:
                ex, im = BALANCES[series]
                if ex in v and im in v:
                    vals[month] = round(v[ex] - v[im], 2)
            elif series in v:
                vals[month] = v[series]
    df = pd.DataFrame({"date": pd.to_datetime([f"{k}-01" for k in vals]), "value": list(vals.values())},
                      columns=["date", "value"])
    df["value"] = df["value"].astype(float)
    return df.sort_values("date").reset_index(drop=True)


def fetch(source_series: str, since=None, session=None, save_raw: bool = True):
    prefix, _, series = source_series.partition(":")
    if prefix != "pib" or series not in SERIES:
        raise TradeError(f"Unknown trade series '{source_series}' (use pib:<{'|'.join(SERIES)}>)")
    releases = load_releases(since, session, save_raw)
    if not releases:
        if since is not None:
            # Up to date: the next month's release is not out yet. Nothing new is not an error.
            return (pd.DataFrame(columns=["date", "value"]).astype({"value": float}),
                    {"last_updated": None, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        raise TradeError("No Ministry of Commerce trade releases found on PIB")
    df = combine(releases, series)
    meta = {"last_updated": max((r.get("release_date") or "" for r in releases), default="") or None,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return df, meta
