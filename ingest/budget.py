"""Union Government fiscal data: Union Budget ("Budget at a Glance") and CGA monthly accounts.

A) Union Budget, "Budget at a Glance" (indiabudget.gov.in). Each budget's workbook has four
   columns: Actuals for the year before last, Budget Estimates (BE) and Revised Estimates (RE)
   for the year ending, and BE for the coming year. The three kinds are never mixed:
     baag:<metric>:actual     Actuals only. Each year is taken from the newest budget that
                              has it, so history comes from archived budgets.
     baag:<metric>:estimate   Latest estimate per fiscal year: the newest RE if one exists,
                              else the newest BE. Includes the BE of a year not yet ended.
   Metrics (Rs crore): fiscal_deficit, revenue_deficit, primary_deficit, interest_payments,
   total_expenditure, capital_expenditure (expenditure on capital account), gross_tax_revenue
   (current workbook only). Deficits also have "<metric>_gdp" (% of GDP, as printed).
   Dates: 1 April of the fiscal year start (FY 2026-27 -> 2026-04-01).
   Older budgets publish one file per table (bag1 = Budget at a Glance); some only as Excel
   97-2003 (.xls), read here by a small stdlib BIFF8 reader (no xlrd).

B) CGA monthly accounts (cga.nic.in/MonthlyReport/Published/<month>/<FY>.aspx): cumulative
   fiscal-year-to-date figures (April to the reported month), unaudited provisional.
     cga:<metric>              Rs crore, cumulative April to month, dated the first day of
                               the reported month (Sep 2026 -> 2026-09-01)
     cga:<metric>_pct_be       actual as % of Budget Estimates, as printed; only months
                               where CGA compares against BE
     cga:<metric>_pct_target   actual as % of the estimate CGA compares against (BE early
                               in the year, RE in the last months and the March provisional)
   Metrics: fiscal_deficit, revenue_deficit, primary_deficit, total_receipts (excluding
   borrowings), revenue_receipts, tax_revenue_net, non_tax_revenue, total_expenditure,
   revenue_expenditure, capital_expenditure, interest_payments.

Raw files and parsed JSON are cached in data/raw/budget/. The current Budget workbook is
downloaded again only when its Last-Modified or size changes (every version is kept and
read, so years survive the next budget's rollover); archived budgets once; CGA months once,
except the latest month, which is downloaded again every run because it can be revised.
"""
import json
import math
import re
import struct
import time
from datetime import datetime, timezone
from html import unescape
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests

from ingest.http import USER_AGENT, FetchError, get

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "budget"
BAAG_URL = "https://www.indiabudget.gov.in/doc/Budget_at_Glance/budget_at_a_glance.xlsx"
_IB = "https://www.indiabudget.gov.in"
# Archived "Budget at a Glance" tables (bag1). Budget -> URL. The Budget 2024-25 files are
# missing on the site (404) and the interim 2024-25 link serves the 2023-24 file, so
# Actuals 2022-23 are not available from this source.
ARCHIVE = {
    "2025-26": f"{_IB}/budget2025-26/doc/Budget_at_Glance/bag1.xlsx",
    "2023-24": f"{_IB}/budget2023-24/doc/Budget_at_Glance/bag1.xls",
    "2022-23": f"{_IB}/budget2022-23/doc/Budget_at_Glance/bag1.xls",
    "2021-22": f"{_IB}/budget2021-22/doc/Budget_at_Glance/bag1.xls",
    "2020-21": f"{_IB}/budget2020-21/doc/Budget_at_Glance/bag1.xlsx",
    "2019-20": f"{_IB}/budget2019-20/doc/Budget_at_Glance/bag1.xlsx",
    "2018-19": f"{_IB}/budget2018-2019/ub2018-19/bag/bag1.xlsx",
    "2017-18": f"{_IB}/budget2017-2018/ub2017-18/bag/bag1.xlsx",
    "2016-17": f"{_IB}/budget2016-2017/ub2016-17/bag/bag1.xls",
}
CGA_URL = "https://cga.nic.in/MonthlyReport/Published/{month}/{fy}.aspx"
CGA_START = (2023, 4)          # April 2023 = first month of FY 2023-24
CGA_RECENT_MONTHS = 3          # an unpublished month this recent means "not released yet"
MEMO_SECONDS = 3600            # reuse downloads across the many series of one run
PARSER_VERSION = 2             # bump when parsing changes, to refresh cached JSON

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]

# Budget at a Glance rows: metric -> [(label regex, which match to use)], tried in order.
GLANCE_METRICS = {
    "fiscal_deficit": [(r"\bfiscal deficit\b(?!.*financ)", "first")],
    "revenue_deficit": [(r"(?<!effective )\brevenue deficit\b", "first")],
    "primary_deficit": [(r"\bprimary deficit\b", "first")],
    "interest_payments": [(r"\binterest payments\b", "first")],
    "total_expenditure": [(r"\btotal expenditure\b", "first")],
    # Budget 2016-17 has plan / non-plan capital account rows and a "Capital Expenditure (12+15)"
    # total; 2017-18 has scheme / non-scheme / total "On Capital Account" rows (the last is the
    # total); later budgets have one "On Capital Account" row. "Effective capital expenditure"
    # (which adds grants for capital assets) is a different measure and is not used.
    "capital_expenditure": [(r"(?<!effective )\bcapital expenditure\b", "first"),
                            (r"\bon capital account\b", "last")],
    "gross_tax_revenue": [(r"\bgross tax revenue\b", "first")],
}
GDP_METRICS = {"fiscal_deficit", "revenue_deficit", "primary_deficit"}

# CGA rows: metric -> regex on the label with spaces removed, lower case.
CGA_METRICS = {
    "revenue_receipts": r"revenuereceipts",
    "tax_revenue_net": r"taxrevenue\(net\)",
    "non_tax_revenue": r"non-?taxrevenue",
    "total_receipts": r"totalreceipts",
    "revenue_expenditure": r"revenueexpenditure",
    "interest_payments": r"ofwhichinterestpayments",
    "capital_expenditure": r"capitalexpenditure",
    "total_expenditure": r"totalexpenditure",
    "fiscal_deficit": r"fiscaldeficit",
    "revenue_deficit": r"revenuedeficit",
    "primary_deficit": r"primarydeficit",
}

_MEMO: dict = {}


class BudgetError(FetchError):
    pass


# ============================== spreadsheet reading ==============================

def _cfb_stream(data: bytes, names=("Workbook", "Book")) -> bytes:
    """Extract the workbook stream from an OLE2 compound file (.xls container)."""
    if data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise BudgetError("not an OLE2 compound file")
    ssz = 1 << struct.unpack_from("<H", data, 30)[0]
    mssz = 1 << struct.unpack_from("<H", data, 32)[0]
    n_fat, dir_start = struct.unpack_from("<II", data, 44)
    cutoff, minifat_start, _n_minifat, difat_start, n_difat = struct.unpack_from("<IIIII", data, 56)
    per = ssz // 4

    def sector(i):
        return data[(i + 1) * ssz:(i + 2) * ssz]

    difat = list(struct.unpack_from("<109I", data, 76))
    s = difat_start
    for _ in range(n_difat):
        vals = struct.unpack(f"<{per}I", sector(s))
        difat += vals[:-1]
        s = vals[-1]
    fat = []
    for i in difat[:n_fat]:
        fat += struct.unpack(f"<{per}I", sector(i))

    def chain(start, table, read):
        out, i, seen = [], start, set()
        while i < 0xFFFFFFFA:
            if i in seen or i >= len(table):
                raise BudgetError("corrupt sector chain in .xls file")
            seen.add(i)
            out.append(read(i))
            i = table[i]
        return b"".join(out)

    dirs = chain(dir_start, fat, sector)
    entries = []
    for off in range(0, len(dirs) - 127, 128):
        e = dirs[off:off + 128]
        nlen = struct.unpack_from("<H", e, 64)[0]
        start, size = struct.unpack_from("<II", e, 116)
        entries.append((e[:max(nlen - 2, 0)].decode("utf-16-le", "replace"), e[66], start, size))
    for name, typ, start, size in entries:
        if typ == 2 and name in names:
            if size >= cutoff:
                return chain(start, fat, sector)[:size]
            mini = chain(entries[0][2], fat, sector)
            minifat_raw = chain(minifat_start, fat, sector)
            minifat = struct.unpack(f"<{len(minifat_raw) // 4}I", minifat_raw)
            return chain(start, minifat, lambda i: mini[i * mssz:(i + 1) * mssz])[:size]
    raise BudgetError("no Workbook stream in .xls file")


def _rk(v: int) -> float:
    num = (v >> 2) - (1 << 30 if v & 0x80000000 else 0) if v & 2 else \
        struct.unpack("<d", struct.pack("<Q", (v & 0xFFFFFFFC) << 32))[0]
    return num / 100 if v & 1 else float(num)


def _parse_sst(chunks: list[bytes]) -> list[str]:
    """Shared string table; strings may continue across CONTINUE records."""
    n_unique = struct.unpack_from("<I", chunks[0], 4)[0]
    out, i, p = [], 0, 8
    while len(out) < n_unique:
        if p >= len(chunks[i]):
            i, p = i + 1, 0
            if i >= len(chunks):
                break
        c = chunks[i]
        cch, flags = struct.unpack_from("<HB", c, p)
        p += 3
        n_run = ext = 0
        if flags & 8:
            n_run = struct.unpack_from("<H", c, p)[0]
            p += 2
        if flags & 4:
            ext = struct.unpack_from("<I", c, p)[0]
            p += 4
        wide, parts, left = flags & 1, [], cch
        while left > 0:
            if p >= len(chunks[i]):        # characters continue: new record starts with a flag byte
                i += 1
                wide, p = chunks[i][0] & 1, 1
            c = chunks[i]
            take = min(left, (len(c) - p) // (2 if wide else 1))
            raw = c[p:p + take * (2 if wide else 1)]
            parts.append(raw.decode("utf-16-le" if wide else "latin-1"))
            p += len(raw)
            left -= take
        skip = 4 * n_run + ext
        while skip > 0:
            if p >= len(chunks[i]):
                i, p = i + 1, 0
            step = min(skip, len(chunks[i]) - p)
            p += step
            skip -= step
        out.append("".join(parts))
    return out


def _xl_string(d: bytes, p: int, len_bytes: int = 2) -> str:
    cch = d[p] if len_bytes == 1 else struct.unpack_from("<H", d, p)[0]
    flags = d[p + len_bytes]
    start = p + len_bytes + 1
    if flags & 1:
        return d[start:start + 2 * cch].decode("utf-16-le", "replace")
    return d[start:start + cch].decode("latin-1")


def read_xls(content: bytes) -> dict[str, list[list]]:
    """Minimal BIFF8 (.xls) reader: sheet name -> rows of cell values (str / float / None)."""
    wb = _cfb_stream(content)

    def records(p):
        while p + 4 <= len(wb):
            rt, ln = struct.unpack_from("<HH", wb, p)
            yield rt, wb[p + 4:p + 4 + ln]
            p += 4 + ln

    sheets, sst, sst_chunks = [], [], None
    for rt, d in records(0):
        if sst_chunks is not None and rt != 0x003C:
            sst, sst_chunks = _parse_sst(sst_chunks), None
        if rt == 0x0085:                                   # BOUNDSHEET8
            if d[5] == 0:                                  # worksheet
                sheets.append((_xl_string(d, 6, 1), struct.unpack_from("<I", d, 0)[0]))
        elif rt == 0x00FC:                                 # SST
            sst_chunks = [d]
        elif rt == 0x003C and sst_chunks is not None:      # CONTINUE
            sst_chunks.append(d)
        elif rt == 0x000A:                                 # EOF of globals
            break
    if sst_chunks is not None:
        sst = _parse_sst(sst_chunks)

    out = {}
    for name, offset in sheets:
        cells, formula_cell = {}, None
        for n, (rt, d) in enumerate(records(offset)):
            if rt == 0x000A and n > 0:
                break
            if rt == 0x00FD:                               # LABELSST
                r, c, _, k = struct.unpack_from("<HHHI", d)
                cells[(r, c)] = sst[k] if k < len(sst) else None
            elif rt == 0x0203:                             # NUMBER
                r, c, _, v = struct.unpack_from("<HHHd", d)
                cells[(r, c)] = v
            elif rt == 0x027E:                             # RK
                r, c, _, v = struct.unpack_from("<HHHI", d)
                cells[(r, c)] = _rk(v)
            elif rt == 0x00BD:                             # MULRK
                r, c0 = struct.unpack_from("<HH", d)
                for j in range((len(d) - 6) // 6):
                    cells[(r, c0 + j)] = _rk(struct.unpack_from("<I", d, 4 + 6 * j + 2)[0])
            elif rt == 0x0204:                             # LABEL
                r, c = struct.unpack_from("<HH", d)
                cells[(r, c)] = _xl_string(d, 6)
            elif rt == 0x0006:                             # FORMULA (cached result)
                r, c = struct.unpack_from("<HH", d)
                if d[12:14] == b"\xff\xff":
                    formula_cell = (r, c) if d[6] == 0 else None
                else:
                    cells[(r, c)] = struct.unpack_from("<d", d, 6)[0]
            elif rt == 0x0207 and formula_cell:            # STRING result of the formula above
                cells[formula_cell] = _xl_string(d, 0)
                formula_cell = None
        n_rows = max((r for r, _ in cells), default=-1) + 1
        n_cols = max((c for _, c in cells), default=-1) + 1
        out[name] = [[cells.get((r, c)) for c in range(n_cols)] for r in range(n_rows)]
    return out


def read_workbook(content: bytes) -> dict[str, list[list]]:
    if content[:2] == b"PK":
        import openpyxl
        wb = openpyxl.load_workbook(BytesIO(content), data_only=True, read_only=True)
        return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
    if content[:4] == b"\xd0\xcf\x11\xe0":
        return read_xls(content)
    raise BudgetError("downloaded file is not an Excel workbook")


# ============================== Budget at a Glance ==============================

_FY = re.compile(r"((?:19|20)\d{2})\s*-\s*(\d{2,4})")
_VAL = re.compile(r"^(-?[\d,]+(?:\.\d+)?)$")
_VAL_PCT = re.compile(r"^(-?[\d,]+(?:\.\d+)?)\s*\(\s*(-?[\d.]+)\s*\)$")
_PCT = re.compile(r"^\(\s*(-?[\d.]+)\s*\)$")


def _cell(v):
    """-> (value, pct_of_gdp, pct_only) parsed from a Budget cell."""
    if isinstance(v, bool) or v is None:
        return None, None, False
    if isinstance(v, (int, float)):
        return float(v), None, False
    s = " ".join(str(v).split())
    if m := _VAL_PCT.match(s):
        return float(m.group(1).replace(",", "")), float(m.group(2)), False
    if m := _VAL.match(s):
        return float(m.group(1).replace(",", "")), None, False
    if m := _PCT.match(s):
        return None, float(m.group(1)), True
    return None, None, False


def _header(rows):
    """-> (header row index, {col: (fy_start, kind)}) or None. kind: actual / BE / RE."""
    for h, row in enumerate(rows):
        cols = [c for c, v in enumerate(row) if isinstance(v, str) and _FY.search(v)]
        if len(cols) < 3:
            continue
        out, bad = {}, []
        for c in cols:
            text = " ".join(str(rows[r][c]) for r in range(h, min(h + 5, len(rows)))
                            if c < len(rows[r]) and rows[r][c] is not None).lower()
            kind = "RE" if "revis" in text else "actual" if "actual" in text else "BE" if "budget" in text else None
            if not kind:
                continue
            m = _FY.search(str(row[c]))
            start, end = int(m.group(1)), int(m.group(2))
            if end % 100 == (start + 1) % 100:
                out[c] = (start, kind)
            else:
                bad.append((c, kind))
        for c, kind in bad:   # typo such as "2016-2016" for the Actuals column of Budget 2017-18
            est = [y for y, k in out.values() if k != "actual"]
            if kind != "actual" or not est:
                raise BudgetError(f"Cannot read fiscal year '{row[c]}' in Budget header")
            out[c] = (min(est) - 1, kind)
        if len(out) >= 3:
            return h, out
    return None


def parse_glance_rows(rows) -> dict:
    """One sheet -> {metric: {(fy_start, kind): (value, pct_gdp)}}."""
    found = _header(rows)
    if not found:
        return {}
    h, cols = found
    first_col = min(cols)
    matches: dict[str, list[dict]] = {}
    prev = None
    for row in rows[h + 1:]:
        row = list(row) + [None] * (first_col + 1)
        label = " ".join(" ".join(str(v).split()) for v in row[:first_col]
                         if isinstance(v, str) and v.strip()).lower()
        parsed = {c: _cell(row[c] if c < len(row) else None) for c in cols}
        if not any(v is not None or p is not None for v, p, _ in parsed.values()) and not label:
            continue
        values = {c: (v, p) for c, (v, p, _) in parsed.items() if v is not None}
        if values and label:
            prev = {cols[c]: [v, p] for c, (v, p) in values.items()}
            for metric, patterns in GLANCE_METRICS.items():
                for n, (rx, _) in enumerate(patterns):
                    if re.search(rx, label):
                        matches.setdefault((metric, n), []).append(prev)
            continue
        # A row of % of GDP figures under the previous row: "(4.8)" text, or numbers shown in
        # brackets by the cell format (stored negative); the sign follows the crore value.
        if prev is not None and not label:
            for c, (v, p, pct_only) in parsed.items():
                key = cols[c]
                if key not in prev:
                    continue
                if pct_only:
                    prev[key][1] = p
                elif v is not None:
                    prev[key][1] = math.copysign(abs(v), prev[key][0])
            prev = None
            continue
        prev = None
    out = {}
    for metric, patterns in GLANCE_METRICS.items():
        for n, (_, which) in enumerate(patterns):
            rows_found = matches.get((metric, n))
            if rows_found:
                pick = rows_found[-1] if which == "last" else rows_found[0]
                out[metric] = {k: (v[0], v[1]) for k, v in pick.items()}
                break
    return out


def parse_glance(content: bytes) -> dict:
    """Whole workbook -> {metric: {"<fy_start>|<kind>": [value, pct_gdp]}} (JSON friendly).

    Sheets are read in order; the first sheet that has a metric wins.
    """
    out = {}
    for rows in read_workbook(content).values():
        for metric, vals in parse_glance_rows(rows).items():
            out.setdefault(metric, {f"{y}|{k}": [v, p] for (y, k), (v, p) in vals.items()})
    if "fiscal_deficit" not in out:
        raise BudgetError("Budget at a Glance: fiscal deficit row not found")
    return out


def combine_glance(parsed_files: list[dict], metric: str, kind: str, gdp: bool) -> dict:
    """Pick one value per fiscal year across budgets: {fy_start: value}.

    kind "actual": Actuals from the newest budget that has them.
    kind "estimate": newest RE, else newest BE.
    """
    ordered = sorted(parsed_files, key=lambda f: max(int(k.split("|")[0]) for k in f["fiscal_deficit"]),
                     reverse=True)
    wanted = ("actual",) if kind == "actual" else ("RE", "BE")
    out = {}
    for want in wanted:
        for f in ordered:
            for key, (value, pct) in f.get(metric, {}).items():
                fy, k = key.split("|")
                v = pct if gdp else value
                if k == want and int(fy) not in out and v is not None:
                    out[int(fy)] = v
    return out


# ============================== CGA monthly accounts ==============================

def _text(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _num(s: str):
    s = re.sub(r"[\s,%()]", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def parse_cga(html: str) -> dict | None:
    """Monthly accounts page -> {"basis", "fy", "period", "month", "rows": {metric: {...}}}.

    Returns None when the page has no accounts table (month not published yet).
    """
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    for table in re.findall(r"<table.*?</table>", body, flags=re.S | re.I):
        if "fiscal" not in table.lower() or "deficit" not in table.lower():
            continue
        rows = [[_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)]
                for tr in re.findall(r"<tr.*?</tr>", table, flags=re.S | re.I)]
        header = next((r for r in rows if any("estimates" in c.replace(" ", "").lower() for c in r)), None)
        if header is None:
            continue
        flat = [c.replace(" ", "").lower() for c in header]
        est = next(c for c in flat if "estimates" in c)
        basis = "RE" if est.startswith("revised") else "BE" if est.startswith("budget") else None
        fy = re.search(r"(\d{4})-(\d{4})", est)
        actual_head = next((c for c in flat if c.startswith(("actual", "provisional"))), "")
        m = re.search(r"(" + "|".join(MONTHS) + r")(\d{4})", actual_head)
        month = (int(m.group(2)), MONTHS.index(m.group(1)) + 1) if m else \
            (int(fy.group(2)), 3) if fy and actual_head.startswith("provisional") else None
        out = {}
        for r in rows:
            if len(r) < 3:
                continue
            label = r[1].replace(" ", "").lower()
            metric = next((k for k, rx in CGA_METRICS.items() if re.match(rx, label)), None)
            if metric is None or metric in out:
                continue
            # Usual layout: no, label, "(Details)" link or blank, estimate, actual, %, % a year ago.
            cells = r[3:7] if len(r) >= 7 else [c for c in r[2:] if c and c.lower() != "(details)"]
            nums = [_num(c) for c in cells]
            if len(nums) < 2 or nums[1] is None:
                raise BudgetError(f"CGA row '{r[1]}' has no actual figure: {r}")
            out[metric] = {"estimate": nums[0], "actual": nums[1],
                           "pct": nums[2] if len(nums) > 2 else None,
                           "pct_coppy": nums[3] if len(nums) > 3 else None}
        if "fiscal_deficit" not in out:
            continue
        return {"basis": basis, "fy": fy.group(0) if fy else None, "month": month,
                "period": " ".join(header[4].split()) if len(header) > 4 else None, "rows": out}
    return None


def _fy_of(y: int, m: int) -> str:
    start = y if m >= 4 else y - 1
    return f"{start}-{start + 1}"


def _months(start, end):
    y, m = start
    while (y, m) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _cga_download(y: int, m: int, session, save_raw: bool, cached: dict | None) -> dict | None:
    url = CGA_URL.format(month=m, fy=_fy_of(y, m))
    html = get(url, session=session).text
    rec = parse_cga(html)
    if rec is None:
        return None
    if rec["month"] and tuple(rec["month"]) != (y, m):
        raise BudgetError(f"CGA page {url} reports {rec['month']}, expected {(y, m)}")
    rec["month"], rec["url"], rec["parser"] = [y, m], url, PARSER_VERSION
    if save_raw and (cached is None or cached.get("rows") != rec["rows"]):
        d = RAW_DIR / "cga"
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        (d / f"{y}-{m:02d}_{stamp}.html").write_text(html, encoding="utf-8")
        (d / f"{y}-{m:02d}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def _today():
    return datetime.now(timezone.utc).date()


def cga_months(start=CGA_START, session=None, save_raw: bool = True, today=None) -> dict:
    """{(year, month): parsed page} from `start` to the latest published month."""
    today = today or _today()
    memo = _MEMO.setdefault(("cga", save_raw), {"t": time.time(), "pages": {}})
    if time.time() - memo["t"] > MEMO_SECONDS:
        memo.update(t=time.time(), pages={})
    pages = memo["pages"]
    disk = {}
    if save_raw and (RAW_DIR / "cga").exists():
        for p in (RAW_DIR / "cga").glob("*.json"):
            rec = json.loads(p.read_text(encoding="utf-8"))
            if rec.get("parser") == PARSER_VERSION:
                disk[tuple(rec["month"])] = rec
    latest_disk = max(disk) if disk else None
    recent = sorted(_months((2000, 1), (today.year, today.month)))[-CGA_RECENT_MONTHS:]
    out = {}
    for key in _months(tuple(start), (today.year, today.month)):
        if key in pages:
            rec = pages[key]
        elif key in disk and key != latest_disk:
            rec = disk[key]
        else:
            rec = _cga_download(*key, session=session, save_raw=save_raw, cached=disk.get(key))
            if rec is None and key in disk:
                rec = disk[key]          # page temporarily empty: keep what we had
            pages[key] = rec
        if rec is None:
            if key in recent:
                break                    # not released yet; later months will not be either
            continue                     # an older month CGA never published
        out[key] = rec
    return out


# ============================== Budget files: download and cache ==============================

def _head(url, session):
    """(Last-Modified, Content-Length) from a HEAD request, or (None, None)."""
    try:
        r = (session or requests.Session()).head(url, headers={"User-Agent": USER_AGENT}, timeout=60,
                                                 allow_redirects=True)
        if r.status_code == 200:
            return r.headers.get("Last-Modified"), r.headers.get("Content-Length")
    except Exception:  # noqa: BLE001 - HEAD is only an optimisation; fall back to GET
        pass
    return None, None


def _parsed_cache(path: Path, content: bytes) -> dict:
    """Parsed workbook, cached as JSON next to the file (re-parsed when the parser changes)."""
    jpath = path.with_suffix(".json")
    if jpath.exists() and jpath.stat().st_mtime >= path.stat().st_mtime:
        cached = json.loads(jpath.read_text(encoding="utf-8"))
        if cached.get("parser") == PARSER_VERSION:
            return cached["metrics"]
    parsed = parse_glance(content)
    jpath.write_text(json.dumps({"parser": PARSER_VERSION, "metrics": parsed}, indent=1), encoding="utf-8")
    return parsed


def _current_glance(session, save_raw: bool) -> tuple[list[dict], str | None]:
    """Every known version of the current workbook (newest download included) -> parsed files."""
    d = RAW_DIR / "baag"
    state_path = d / "current_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if save_raw and state_path.exists() else {}
    last_mod = size = None
    if state:
        last_mod, size = _head(BAAG_URL, session)
    if not (state and last_mod and last_mod == state.get("last_modified")
            and str(size) == str(state.get("size")) and (d / state["file"]).exists()):
        r = get(BAAG_URL, session=session)
        content = r.content
        last_mod = r.headers.get("Last-Modified") if hasattr(r, "headers") else None
        if not save_raw:
            return [parse_glance(content)], last_mod
        stamp = pd.Timestamp(last_mod).strftime("%Y%m%d") if last_mod else \
            datetime.now(timezone.utc).strftime("%Y%m%d")
        d.mkdir(parents=True, exist_ok=True)
        name = f"budget_at_a_glance_{stamp}.xlsx"
        if not (d / name).exists() or (d / name).read_bytes() != content:
            (d / name).write_bytes(content)
        state = {"last_modified": last_mod, "size": len(content), "file": name}
        state_path.write_text(json.dumps(state), encoding="utf-8")
    files = [_parsed_cache(p, p.read_bytes()) for p in sorted(d.glob("budget_at_a_glance_*.xlsx"))]
    return files, state.get("last_modified")


def _archive_glance(session, save_raw: bool) -> tuple[list[dict], list[str]]:
    files, missing = [], []
    for budget, url in ARCHIVE.items():
        path = RAW_DIR / "baag" / "archive" / f"budget{budget}_bag1{Path(url).suffix}"
        try:
            if save_raw and path.exists():
                files.append(_parsed_cache(path, path.read_bytes()))
                continue
            content = get(url, session=session).content
            if not save_raw:
                files.append(parse_glance(content))
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            files.append(_parsed_cache(path, content))
        except FetchError as e:  # an archive outage should not stop the current figures
            missing.append(f"{budget}: {e}")
    return files, missing


def glance_files(session=None, save_raw: bool = True) -> tuple[list[dict], dict]:
    memo = _MEMO.get(("baag", save_raw))
    if memo and time.time() - memo["t"] < MEMO_SECONDS:
        return memo["files"], memo["info"]
    current, last_mod = _current_glance(session, save_raw)
    archived, missing = _archive_glance(session, save_raw)
    info = {"last_modified": last_mod, "missing_archives": missing}
    _MEMO[("baag", save_raw)] = {"t": time.time(), "files": current + archived, "info": info}
    return current + archived, info


# ============================== fetch ==============================

def _frame(points: dict) -> pd.DataFrame:
    df = pd.DataFrame({"date": list(points), "value": [float(v) for v in points.values()]})
    if df.empty:
        return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "value": pd.Series(dtype=float)})
    return df.sort_values("date").reset_index(drop=True)


def fetch(source_series: str, since=None, session=None, save_raw: bool = True):
    parts = source_series.split(":")
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if parts[0] == "baag" and len(parts) == 3 and parts[2] in ("actual", "estimate"):
        metric, kind = parts[1], parts[2]
        gdp = metric.endswith("_gdp")
        base = metric[:-4] if gdp else metric
        if base not in GLANCE_METRICS or (gdp and base not in GDP_METRICS):
            raise BudgetError(f"Unknown Budget metric '{metric}' in '{source_series}'")
        files, info = glance_files(session, save_raw)
        points = combine_glance(files, base, kind, gdp)
        if not points:
            raise BudgetError(f"No {kind} values for '{metric}' in Budget at a Glance")
        df = _frame({pd.Timestamp(fy, 4, 1): v for fy, v in points.items()})
        last = info.get("last_modified")
        meta = {"last_updated": pd.Timestamp(last).date().isoformat() if last else None,
                "fetched_at": fetched_at, "missing_archives": info.get("missing_archives")}
        return df, meta

    if parts[0] == "cga" and len(parts) == 2:
        m = re.fullmatch(r"(\w+?)(?:_(pct_be|pct_target))?", parts[1])
        metric, pct = m.group(1), m.group(2)
        if metric not in CGA_METRICS:
            raise BudgetError(f"Unknown CGA metric '{parts[1]}' in '{source_series}'")
        start = CGA_START
        if since is not None:
            s = pd.Timestamp(since)
            start = max(CGA_START, (s.year, s.month))
        pages = cga_months(start, session=session, save_raw=save_raw)
        points = {}
        for (y, mo), rec in pages.items():
            row = rec["rows"].get(metric)
            if row is None:
                continue
            if pct == "pct_be" and rec.get("basis") != "BE":
                continue
            v = row["pct"] if pct else row["actual"]
            if v is not None:
                points[pd.Timestamp(y, mo, 1)] = v
        if not points and since is None:
            raise BudgetError(f"No CGA values for '{parts[1]}'")
        latest = pages[max(pages)] if pages else None
        meta = {"last_updated": None, "fetched_at": fetched_at,
                "latest_period": latest.get("period") if latest else None}
        return _frame(points), meta

    raise BudgetError(f"source_series must be 'baag:<metric>:actual|estimate' or 'cga:<metric>', "
                      f"got '{source_series}'")
