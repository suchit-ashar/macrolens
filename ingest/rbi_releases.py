"""Fetch numbers published in RBI press releases (rbi.org.in, HTML pages only).

Three kinds of recurring release are read:
  mmo  "Money Market Operations as on <date>"  (daily)
       wacr, treps_rate, market_repo_rate     weighted average overnight rates, per cent
       sdf_amount, msf_amount                  today's SDF / MSF operations, Rs crore
       net_liquidity                           "F. Net liquidity injected (outstanding including
                                               today's operations)", Rs crore, injection (+) /
                                               absorption (-) as published
       net_durable_liquidity                   Rs crore, surplus (+) / deficit (-), dated to its own
                                               "as on" date (lags the release by weeks)
       Observation date = the "as on" date in the title, not the release date.
  wss  "Bulletin Weekly Statistical Supplement - Extract"  (weekly)
       fx_reserves_total, fx_fca, fx_gold, fx_sdr, fx_imf   US$ million (Table 2, "As on" date)
       bank_credit, deposits (Rs crore), bank_credit_yoy, deposits_yoy (per cent)  (Table 4,
       scheduled commercial banks, "Outstanding as on" date; YoY = published growth row)
       m3 (Rs crore), m3_yoy (per cent)                     (Table 6, its own fortnight date)
  bop  "Developments in India's Balance of Payments for the Month of <Month YYYY>"  (monthly,
       from April 2026). US$ billion: current_account, fdi_net, fdi_india_net, fpi_net. Dated
       the first day of the month. Each release also gives the same month a year earlier
       (partially revised); that value is kept too.

source_series is "<kind>:<key>", e.g. "mmo:wacr", "wss:m3_yoy", "bop:current_account".

Releases are found in the press-release list (GET, last ~10 days) and its month archive
(ASP.NET POST with hdnYear/hdnMonth). Many series share one release, so each release is
parsed once and cached in data/raw/rbi/<kind>/<obs date>_<prid>.json (raw page next to it as
.html.gz); fetch() only downloads releases it has not cached. Without `since`, the archive is
read from BACKFILL_START[kind]; with `since`, from since's month onward. When two releases give
a value for the same date (corrections, revisions), the later prid wins.
rbidocs.rbi.org.in (PDFs) is never used: it serves a bot-check page to scripts.
"""
import gzip
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path

import pandas as pd
import requests

from ingest.http import USER_AGENT, FetchError, get

LIST_URL = "https://rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"
RELEASE_URL = LIST_URL + "?prid={prid}"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "rbi"
IST = timezone(timedelta(hours=5, minutes=30))
BACKFILL_START = {"mmo": date(2025, 1, 1), "wss": date(2023, 1, 1), "bop": date(2024, 1, 1)}
SLEEP = 0.3            # seconds between requests to rbi.org.in
MAX_DOWNLOADS = 1200   # release pages per fetch() call; the rest is picked up next run
LIST_MEMO_SECONDS = 900
PARSER_VERSION = 2     # bump when a parser changes: cached JSON is re-parsed from the saved page

SERIES = {
    "mmo": {"wacr", "treps_rate", "market_repo_rate", "net_liquidity", "net_liquidity_today",
            "sdf_amount", "msf_amount", "net_durable_liquidity"},
    "wss": {"fx_reserves_total", "fx_fca", "fx_gold", "fx_sdr", "fx_imf", "m3", "m3_yoy",
            "bank_credit", "bank_credit_yoy", "deposits", "deposits_yoy"},
    "bop": {"current_account", "fdi_net", "fdi_india_net", "fpi_net"},
}
TITLES = {
    "mmo": re.compile(r"^Money Market Operations as on\s+([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})", re.I),
    "wss": re.compile(r"Bulletin Weekly Statistical Supplement", re.I),
    "bop": re.compile(r"Balance of Payments for the Month of\s+([A-Z][a-z]+\s+\d{4})", re.I),
}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
                                      "oct", "nov", "dec"], 1)}
DATE_RE = re.compile(r"([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),?\s+(\d{4})")
NUM_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?|[-+]?\.\d+")
RELEASE_DATE = re.compile(r"Date\s*:\s*([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s+\d{4})")

_LIST_MEMO: dict = {}   # (year, month) or "recent" -> (time, entries); shared by fetch() calls in one run


class RbiReleaseError(FetchError):
    pass


# ---------------------------------------------------------------- small parsing helpers
def _clean(s: str) -> str:
    s = unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def parse_date(s: str) -> date | None:
    """'November 19, 2026', 'Nov. 13, 2026', 'Sept. 2, 2025' -> date."""
    m = DATE_RE.search(s or "")
    if not m or m.group(1)[:3].lower() not in MONTHS:
        return None
    return date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))


def parse_month(s: str) -> date | None:
    """'September 2026' -> 2026-09-01."""
    m = re.search(r"([A-Z][a-z]+)\s+(\d{4})", s or "")
    if not m or m.group(1)[:3].lower() not in MONTHS:
        return None
    return date(int(m.group(2)), MONTHS[m.group(1)[:3].lower()], 1)


def parse_number(cell: str) -> float | None:
    """One table cell -> float. Handles 3,37,68,416, stray spaces inside the number and
    unicode minus signs; anything else (dates, ranges, '-', text) -> None."""
    s = re.sub(r"\s+", "", (cell or "").replace("−", "-").replace("–", "-").replace("—", "-"))
    if not s or not NUM_RE.fullmatch(s):
        return None
    return float(s.replace(",", "").replace("+", ""))


def table_rows(html: str) -> list[list[str]]:
    """Every <tr> as a list of cleaned cell texts (empty cells kept). Regex only: no lxml/bs4."""
    rows = []
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"<(script|style)\b.*?</\1\s*>", " ", html, flags=re.S | re.I)
    for chunk in re.split(r"<tr\b[^>]*>", html, flags=re.I)[1:]:
        chunk = re.split(r"</tr\s*>", chunk, flags=re.I)[0]
        cells = re.split(r"<t[dh]\b[^>]*>", chunk, flags=re.I)[1:]
        cells = [_clean(c) for c in cells]
        if any(cells):
            rows.append(cells)
    return rows


def _label(row: list[str]) -> str:
    return next((c for c in row if c), "")


def _numbers(row: list[str]) -> list[float]:
    """Numeric cells after the label cell."""
    cells = row[row.index(_label(row)) + 1:] if _label(row) else row
    return [v for v in (parse_number(c) for c in cells) if v is not None]


def _find(rows, pattern, start=0, end=None) -> int | None:
    rx = re.compile(pattern, re.I)
    for i in range(start, len(rows) if end is None else end):
        if rx.search(_label(rows[i])):
            return i
    return None


def release_date(html: str) -> date | None:
    m = RELEASE_DATE.search(_clean(html))
    return parse_date(m.group(1)) if m else None


# ---------------------------------------------------------------- release parsers
def parse_mmo(html: str) -> dict:
    """Money Market Operations release -> {"as_on": iso, "obs": {key: [[iso date, value]]}}."""
    text = _clean(html)
    m = re.search(r"Money Market Operations as on\s+([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})", text)
    as_on = parse_date(m.group(1)) if m else None
    if as_on is None:
        raise RbiReleaseError("Money Market Operations: 'as on' date not found")
    rows = table_rows(html)
    obs, day = {}, as_on.isoformat()

    def put(key, value, when=day):
        if value is not None:
            obs[key] = [[when, value]]

    overnight = _find(rows, r"Overnight Segment")
    term = _find(rows, r"Term Segment", start=overnight or 0)
    if overnight is not None:
        for key, pat in (("wacr", r"^I\.\s*Call Money"), ("treps_rate", r"^II\.\s*Tri-?party Repo"),
                         ("market_repo_rate", r"^III\.\s*Market Repo")):
            i = _find(rows, pat, overnight, term)
            nums = _numbers(rows[i]) if i is not None else []
            put(key, nums[1] if len(nums) >= 2 else None)  # [volume, weighted average rate]

    today = _find(rows, r"^I\.\s*Today.s Operations")
    outstanding = _find(rows, r"^II\.\s*Outstanding Operations", start=today or 0)
    if today is not None:
        for key, pat in (("msf_amount", r"^\d\.\s*MSF"), ("sdf_amount", r"^\d\.\s*SDF")):
            i = _find(rows, pat, today, outstanding)
            nums = _numbers(rows[i]) if i is not None else []
            put(key, nums[-2] if len(nums) >= 3 else None)  # [tenor, amount, rate]
        i = _find(rows, r"Net liquidity injected from today", today, outstanding)
        put("net_liquidity_today", (_numbers(rows[i]) or [None])[0] if i is not None else None)
    i = _find(rows, r"Net liquidity injected \(outstanding including today")
    put("net_liquidity", (_numbers(rows[i]) or [None])[0] if i is not None else None)
    i = _find(rows, r"Net durable liquidity")
    if i is not None:
        when = next((parse_date(c) for c in rows[i][1:] if parse_date(c)), None)
        nums = [parse_number(c) for c in rows[i][1:] if parse_date(c) is None]
        nums = [v for v in nums if v is not None]
        if when and nums:
            put("net_durable_liquidity", nums[-1], when.isoformat())
    if not {"wacr", "net_liquidity"} & obs.keys():
        raise RbiReleaseError(f"Money Market Operations as on {as_on}: no rates or liquidity rows found")
    return {"as_on": day, "obs": obs}


def _section(rows, title_pattern) -> list[list[str]]:
    """Rows of one numbered WSS table ('2. Foreign Exchange Reserves') up to the next table."""
    start = _find(rows, r"^\d+\.\s+" + title_pattern)
    if start is None:
        return []
    end = _find(rows, r"^\d+\.\s+[A-Z]", start + 1)
    return rows[start:end]


def parse_wss(html: str, released: date) -> dict:
    """Weekly Statistical Supplement extract -> {"as_on": iso, "obs": {...}}; every table
    is dated by its own 'as on' date."""
    rows = table_rows(html)
    obs = {}

    fx = _section(rows, r"Foreign Exchange Reserves")
    fx_day = next((parse_date(c) for r in fx for c in r if re.search(r"As on", c, re.I) and parse_date(c)), None)
    if fx_day:
        for key, pat in (("fx_reserves_total", r"^1\s+Total Reserves"), ("fx_fca", r"^1\.1\s+Foreign Currency"),
                         ("fx_gold", r"^1\.2\s+Gold"), ("fx_sdr", r"^1\.3\s+SDR"),
                         ("fx_imf", r"^1\.4\s+Reserve Position")):
            i = _find(fx, pat)
            nums = _numbers(fx[i]) if i is not None else []
            if len(nums) >= 2:
                obs[key] = [[fx_day.isoformat(), nums[1]]]  # [Rs crore, US$ million, variations...]

    scb = _section(rows, r"Scheduled Commercial Banks")
    scb_day = next((parse_date(c) for r in scb for c in r if re.search(r"as on", c, re.I) and parse_date(c)), None)
    if scb_day:
        for key, pat in (("deposits", r"^2\.1\s+Aggregate Deposits"), ("bank_credit", r"^7\s+Bank Credit")):
            i = _find(scb, pat)
            if i is None:
                continue
            nums = _numbers(scb[i])
            if nums:
                obs[key] = [[scb_day.isoformat(), nums[0]]]
            g = _find(scb, r"Growth", i + 1, min(i + 3, len(scb)))
            growth = _numbers(scb[g]) if g is not None else []
            if growth:
                obs[key + "_yoy"] = [[scb_day.isoformat(), growth[-1]]]  # last column = YoY, latest year

    ms = _section(rows, r"Money Stock")
    i = _find(ms, r"^M3$")
    if i is not None:
        # Header row "Mar. 31 | Oct. 31 | Amount | % ...": the 2nd date is the current fortnight.
        # Cells can carry footnote marks ("Dec. 31*").
        day_cell = re.compile(r"([A-Z][a-z]{2,4})\.?\s+(\d{1,2})\W*")
        heads = next(([c for c in r if day_cell.fullmatch(c)] for r in ms[:i]
                      if sum(bool(day_cell.fullmatch(c)) for c in r) >= 2), [])
        nums = _numbers(ms[i])
        if len(heads) >= 2 and len(nums) >= 2:
            m = day_cell.fullmatch(heads[1])
            mon, dd = MONTHS[m.group(1)[:3].lower()], int(m.group(2))
            year = released.year if (mon, dd) <= (released.month, released.day) else released.year - 1
            day = date(year, mon, dd).isoformat()
            obs["m3"] = [[day, nums[1]]]       # [Mar. 31 level, current level, variations...]
            obs["m3_yoy"] = [[day, nums[-1]]]  # last column = YoY %, latest year
    if not obs:
        raise RbiReleaseError(f"Weekly Statistical Supplement of {released}: no tables recognised")
    return {"as_on": released.isoformat(), "obs": obs}


def parse_bop(html: str) -> dict:
    """Monthly BoP release -> {"as_on": first day of month, "obs": {...}} (US$ billion).
    Values for every single-month column (this month and the same month a year earlier)."""
    text = _clean(html)
    m = TITLES["bop"].search(text)
    month = parse_month(m.group(1)) if m else None
    if month is None:
        raise RbiReleaseError("Balance of Payments: reference month not found in title")
    rows = table_rows(html)
    h = _find(rows, r"^Item$")
    if h is None:
        raise RbiReleaseError(f"Balance of Payments {month:%B %Y}: table header not found")
    head = [c for c in rows[h][1:] if c]
    cols = [parse_month(c) if re.fullmatch(r"[A-Z][a-z]+\s+\d{4}(\s+\S+)?", c) else None for c in head]
    obs = {}
    b1 = _find(rows, r"^B\.1\s+Foreign Direct")
    b2 = _find(rows, r"^B\.2\s+Foreign Portfolio")
    found = {"current_account": _find(rows, r"^A\.\s*Current Account"), "fdi_net": b1, "fpi_net": b2,
             "fdi_india_net": _find(rows, r"^a\.\s*In India", b1, b2) if b1 is not None and b2 else None}
    for key, i in found.items():
        if i is None:
            continue
        cells = [c for c in rows[i] if c][1:]  # values after the label, aligned with the header
        pairs = [[d.isoformat(), parse_number(c)] for d, c in zip(cols, cells) if d is not None]
        pairs = [p for p in pairs if p[1] is not None]
        if pairs:
            obs[key] = sorted(pairs)
    if not any(p[0] == month.isoformat() for v in obs.values() for p in v):
        raise RbiReleaseError(f"Balance of Payments {month:%B %Y}: no values for that month")
    return {"as_on": month.isoformat(), "obs": obs}


def parse_release(kind: str, html: str) -> dict:
    released = release_date(html)
    if released is None:
        raise RbiReleaseError(f"{kind}: release date ('Date : ...') not found")
    out = {"mmo": lambda: parse_mmo(html), "wss": lambda: parse_wss(html, released),
           "bop": lambda: parse_bop(html)}[kind]()
    return {"kind": kind, "release_date": released.isoformat(), **out}


# ---------------------------------------------------------------- listing
def parse_listing(html: str) -> list[dict]:
    """Press-release list or month archive -> [{prid, title, date (release, may be None)}]."""
    out, current = [], None
    pattern = re.compile(r"class=\"tableheader\"[^>]*>(.*?)</td>|href=['\"]?[^'\" >]*?prid=(\d+)['\"]?[^>]*>(.*?)</a>",
                         re.I | re.S)
    for m in pattern.finditer(html):
        if m.group(1) is not None:
            current = parse_date(_clean(m.group(1))) or current
        else:
            title = _clean(m.group(3))
            if title:
                out.append({"prid": int(m.group(2)), "title": title,
                            "date": current.isoformat() if current else None})
    return out


def classify(title: str) -> str | None:
    for kind, rx in TITLES.items():
        if rx.search(title):
            return kind
    return None


def _hidden(html: str) -> dict:
    out = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        m = re.search(r'name="%s"[^>]*value="([^"]*)"' % re.escape(name), html)
        out[name] = m.group(1) if m else ""
    return out


class _Lister:
    """Reads the recent list and month archives; complete past months are cached on disk."""

    def __init__(self, session, save_raw: bool):
        self.session, self.save_raw, self.requests, self.form = session, save_raw, 0, None

    def _memo(self, key):
        hit = _LIST_MEMO.get(key)
        return hit[1] if hit and time.time() - hit[0] < LIST_MEMO_SECONDS else None

    def recent(self) -> list[dict]:
        hit = self._memo("recent")
        if hit is not None and self.form is not None:
            return hit
        html = get(LIST_URL, session=self.session).text
        self.requests += 1
        self.form = _hidden(html)
        if not self.form["__VIEWSTATE"]:
            raise RbiReleaseError("Press-release list: ASP.NET form fields not found (layout changed?)")
        entries = parse_listing(html)
        if not entries:
            raise RbiReleaseError("Press-release list: no releases found (layout changed?)")
        _LIST_MEMO["recent"] = (time.time(), entries)
        return entries

    def month(self, year: int, month: int, today: date) -> list[dict]:
        hit = self._memo((year, month))
        if hit is not None:
            return hit
        cache = RAW_DIR / "lists" / f"{year}-{month:02d}.json"
        if cache.exists():
            entries = json.loads(cache.read_text(encoding="utf-8"))
            _LIST_MEMO[(year, month)] = (time.time(), entries)
            return entries
        if self.form is None:
            self.recent()
        html = self._post(year, month)
        entries = parse_listing(html)
        _LIST_MEMO[(year, month)] = (time.time(), entries)
        month_end = (pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0)).date()
        if self.save_raw and entries and (today - month_end).days >= 2:  # month complete: never changes
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(entries), encoding="utf-8")
        return entries

    def _post(self, year: int, month: int) -> str:
        data = {**self.form, "hdnYear": str(year), "hdnMonth": str(month), "UsrFontCntr$btn": ""}
        last = None
        for attempt in range(3):
            time.sleep(SLEEP)
            self.requests += 1
            try:
                r = self.session.post(LIST_URL, data=data, headers={"User-Agent": USER_AGENT}, timeout=90)
                if r.status_code == 200 and "prid=" in r.text:
                    form = _hidden(r.text)
                    if form["__VIEWSTATE"]:
                        self.form = form
                    return r.text
                last = f"HTTP {r.status_code}" + ("" if r.status_code != 200 else ", no releases in page")
            except requests.RequestException as e:
                last = str(e)
            time.sleep(2 ** attempt)
        raise RbiReleaseError(f"Press-release archive {year}-{month:02d}: {last}")


def _months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


# ---------------------------------------------------------------- cache
def _cached(kind: str) -> dict[int, Path]:
    folder = RAW_DIR / kind
    if not folder.exists():
        return {}
    out = {}
    for p in folder.glob("*_*.json"):
        try:
            out[int(p.stem.rsplit("_", 1)[1])] = p
        except ValueError:
            continue
    return out


def _download(kind: str, prid: int, session, save_raw: bool) -> dict:
    html = get(RELEASE_URL.format(prid=prid), session=session).text
    parsed = {"prid": prid, "parser": PARSER_VERSION, **parse_release(kind, html)}
    if save_raw:
        folder = RAW_DIR / kind
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{parsed['as_on']}_{prid}"
        with gzip.open(folder / f"{stem}.html.gz", "wt", encoding="utf-8") as f:
            f.write(html)
        (folder / f"{stem}.json").write_text(json.dumps(parsed, indent=1), encoding="utf-8")
    return parsed


def _load_cached(kind: str, path: Path, save_raw: bool) -> dict:
    """Cached parse; re-parsed from the saved page (no download) if the parser has changed."""
    parsed = json.loads(path.read_text(encoding="utf-8"))
    page = path.with_name(path.stem + ".html.gz")
    if parsed.get("parser") != PARSER_VERSION and page.exists():
        with gzip.open(page, "rt", encoding="utf-8") as f:
            parsed = {"prid": parsed["prid"], "parser": PARSER_VERSION, **parse_release(kind, f.read())}
        if save_raw:
            path.write_text(json.dumps(parsed, indent=1), encoding="utf-8")
    return parsed


def combine(parsed: list[dict], key: str) -> tuple[pd.DataFrame, str | None]:
    """One row per date; when releases disagree the later prid wins. -> (df, release date of last row)."""
    best = {}
    for rel in sorted(parsed, key=lambda r: r["prid"]):
        for day, value in rel.get("obs", {}).get(key, []):
            best[day] = (float(value), rel.get("release_date"))
    df = pd.DataFrame({"date": pd.to_datetime(list(best)), "value": [v for v, _ in best.values()]})
    df = df.sort_values("date").reset_index(drop=True)
    last = best[df["date"].iloc[-1].date().isoformat()][1] if len(df) else None
    return df, last


# ---------------------------------------------------------------- fetch
def fetch(source_series: str, since=None, session=None, save_raw: bool = True):
    kind, _, key = source_series.partition(":")
    if kind not in SERIES or key not in SERIES[kind]:
        raise RbiReleaseError(f"Unknown RBI release source_series '{source_series}'")
    session = session or requests.Session()
    fetched_at = datetime.now(timezone.utc)
    today = fetched_at.astimezone(IST).date()
    if isinstance(since, (datetime, pd.Timestamp)):
        since = since.date()
    start = since.replace(day=1) if since else BACKFILL_START[kind]

    lister = _Lister(session, save_raw)
    wanted = {}
    for entry in lister.recent():
        if classify(entry["title"]) == kind:
            wanted[entry["prid"]] = entry
    for y, m in _months(start, today):
        for entry in lister.month(y, m, today):
            if classify(entry["title"]) == kind:
                wanted[entry["prid"]] = entry

    cached = _cached(kind)
    parsed, errors, downloads = [], [], 0
    for prid, path in cached.items():
        try:
            parsed.append(_load_cached(kind, path, save_raw))
        except (ValueError, KeyError, FetchError) as e:
            errors.append(f"cached prid={prid}: {e}")
    for prid in sorted(set(wanted) - set(cached)):
        if downloads >= MAX_DOWNLOADS:
            errors.append(f"download cap {MAX_DOWNLOADS} reached; rest left for next run")
            break
        if downloads:
            time.sleep(SLEEP)
        downloads += 1
        try:
            parsed.append(_download(kind, prid, session, save_raw))
        except FetchError as e:
            errors.append(f"prid={prid} ({wanted[prid]['title'][:60]}): {e}")

    df, last_release = combine(parsed, key)
    if df.empty:
        detail = "; ".join(errors[:3]) or f"no '{kind}' releases found since {start}"
        raise RbiReleaseError(f"{source_series}: no observations ({detail})")
    return df, {"last_updated": last_release, "fetched_at": fetched_at.isoformat(timespec="seconds"),
                "requests": lister.requests + downloads, "releases_downloaded": downloads,
                "errors": errors}
