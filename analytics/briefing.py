"""Split a daily briefing (Markdown written by the briefing routine) into sections for the dashboard layout.

The routine's prompt fixes the section headings ("## Executive Summary", "## What to Watch Today", ...),
so the page can place them as cards. Anything unexpected still renders: unknown sections are kept in
file order, and a file with no recognisable headings falls back to plain Markdown.
"""
import re
from dataclasses import dataclass, field

_H2 = re.compile(r"^##\s+(.+?)\s*#*\s*$")
_RULE = re.compile(r"\n[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*\n")


def norm(heading: str) -> str:
    return heading.lower().replace("’", "'").replace("&", "and").strip()


@dataclass
class Briefing:
    cutoff: str = ""  # text between the title and the first section (the data cut-off line)
    sections: list[tuple[str, str]] = field(default_factory=list)  # (heading, body) in file order
    notes: str = ""  # source notes after a closing rule (---) at the end of the file

    def take(self, *prefixes: str) -> tuple[str, str] | None:
        """Remove and return the first section whose heading starts with one of the prefixes (case-insensitive)."""
        for i, (heading, body) in enumerate(self.sections):
            if any(norm(heading).startswith(norm(p)) for p in prefixes):
                return self.sections.pop(i)
        return None


def split_briefing(text: str) -> Briefing:
    pre: list[str] = []
    secs: list[list] = []
    in_code = False
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
        m = None if in_code else _H2.match(line)
        if m:
            secs.append([m.group(1).strip(), []])
        elif secs:
            secs[-1][1].append(line)
        else:
            pre.append(line)
    cutoff = "\n".join(l for l in pre if not re.match(r"^#\s", l)).strip()
    b = Briefing(cutoff=cutoff, sections=[(h, "\n".join(body).strip()) for h, body in secs])
    if b.sections:
        heading, body = b.sections[-1]
        rules = list(_RULE.finditer("\n" + body + "\n"))
        if rules:
            cut = rules[-1]
            before, after = ("\n" + body + "\n")[:cut.start()].strip(), ("\n" + body + "\n")[cut.end():].strip()
            if after:
                b.sections[-1] = (heading, before)
                b.notes = after
    return b


_BULLET = re.compile(r"^\s*[-*+]\s+(.+?)\s*$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.+?)\s*$")
_LABELLED = re.compile(r"^\*\*(.+?)\*\*\s*[:—–-]?\s*[:—–-]?\s*(.*)$")


def bullets(body: str) -> list[str]:
    """Text of every '- item' line, in order."""
    return [m.group(1) for line in body.splitlines() if (m := _BULLET.match(line))]


def lead_bullets(body: str) -> tuple[list[str], str]:
    """Bullet lines at the very start of a section, and the rest of the section."""
    lines, out, i = body.splitlines(), [], 0
    while i < len(lines) and (not lines[i].strip() and not out or _BULLET.match(lines[i])):
        if lines[i].strip():
            out.append(_BULLET.match(lines[i]).group(1))
        i += 1
    return out, "\n".join(lines[i:]).strip()


def labelled(body: str, numbered: bool = False) -> list[tuple[str, str]]:
    """'1. **Label** — text' (numbered) or '- **Label:** text' lines as (label, text)."""
    pat, rows = (_NUMBERED if numbered else _BULLET), []
    for line in body.splitlines():
        m = pat.match(line)
        if not m:
            continue
        lm = _LABELLED.match(m.group(1))
        label, text = (lm.group(1).rstrip(":").strip(), lm.group(2).strip()) if lm else ("", m.group(1))
        rows.append((label, text))
    return rows


def lead_table(body: str) -> tuple[list[list[str]], str, str]:
    """The Markdown table at the start of a section: (data rows, the note line right under it, the rest)."""
    lines = body.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    start = i
    while i < len(lines) and lines[i].strip().startswith("|"):
        i += 1
    block = lines[start:i]
    if len(block) < 3 or not re.match(r"^\|?\s*:?-{2,}", block[1].strip()):
        return [], "", body.strip()
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in block[2:]]
    while i < len(lines) and not lines[i].strip():
        i += 1
    note = ""  # a plain line straight after the table, e.g. "Close date: Friday, 20 November 2026. ..."
    if i < len(lines) and not lines[i].lstrip().startswith(("#", "|", "-", "*")):
        note, i = lines[i].strip(), i + 1
    return rows, note, "\n".join(lines[i:]).strip()


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def dashboard_price(body: str, name: str, lo: float, hi: float) -> dict | None:
    """A US$ price from the Analyst Dashboard table row whose first cell is `name`, e.g.
    '| Brent | $92.29/bbl (23 Nov) | -0.30% | Down | ... |' -> {"value": 92.29, "change": -0.3, "day": 23, "month": 11}.
    Returns None when the row is missing, says N/A, or the number is outside [lo, hi]."""
    for line in body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0].lower().strip("* ") != name.lower():
            continue
        m = re.search(r"\$\s?([0-9]{1,4}(?:,[0-9]{3})*(?:\.[0-9]+)?)", cells[1])
        if not m:
            return None
        value = float(m.group(1).replace(",", ""))
        if not lo <= value <= hi:
            return None
        out = {"value": value, "change": None, "day": None, "month": None}
        if len(cells) > 2 and (c := re.search(r"([+\-−]\s?[0-9]+(?:\.[0-9]+)?)\s?%", cells[2])):
            out["change"] = float(c.group(1).replace("−", "-").replace(" ", ""))
        if (d := re.search(r"\((\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\)", cells[1])) and d.group(2).lower() in _MONTHS:
            out["day"], out["month"] = int(d.group(1)), _MONTHS[d.group(2).lower()]
        return out
    return None


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def take_market_rows(body: str, market: str) -> tuple[dict[str, tuple[str, str]], str]:
    """From a scorecard table with Sector / Market / ... / In the news? / Why columns, pull out the rows
    for one market. Returns ({sector name (lower case): (in the news, why)}, the section without those rows).
    If the table has no Market column the section is returned unchanged."""
    lines = body.splitlines()
    news: dict[str, tuple[str, str]] = {}
    keep: list[str] = []
    cols: list[str] | None = None
    for line in lines:
        if line.strip().startswith("|"):
            cells = _cells(line)
            low = [c.lower() for c in cells]
            if "sector" in low and "market" in low:
                cols = low
                keep.append(line)
                continue
            if cols and not re.match(r"^:?-{2,}", cells[0]) and len(cells) >= len(cols) - 1:
                row = dict(zip(cols, cells))
                if row.get("market", "").lower() == market.lower():
                    news_col = next((c for c in cols if c.startswith("in the news")), None)
                    why_col = next((c for c in cols if c.startswith("why")), None)
                    news[row.get("sector", "").lower()] = (row.get(news_col, "") if news_col else "",
                                                          row.get(why_col, "") if why_col else "")
                    continue
        else:
            cols = None if line.strip() else cols
        keep.append(line)
    # drop a table left with only its header and separator
    out, i = [], 0
    while i < len(keep):
        if (i + 1 < len(keep) and keep[i].strip().startswith("|") and re.match(r"^\|?\s*:?-{2,}", keep[i + 1].strip())
                and (i + 2 >= len(keep) or not keep[i + 2].strip().startswith("|"))):
            i += 2
            continue
        out.append(keep[i])
        i += 1
    return news, "\n".join(out).strip()


def md_inline(text: str) -> str:
    """Escape text for HTML, keeping **bold**, *italic* and [links](https://...) from the Markdown."""
    from html import escape
    s = escape(text, quote=True)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)


_ICONS = [
    (("linkage", "↔", "connection"), "link"), (("macro",), "globe"), (("equit",), "gdp"), (("credit",), "credit"),
    (("commodit", "fx"), "drop"), (("indian market", "india"), "bank"), (("company", "develop"), "doc"),
    (("scorecard",), "gdp"), (("dashboard",), "yield"), (("watch", "event"), "calendar"), (("things",), "target"),
    (("risk",), "alert"), (("opportunit", "positive"), "bulb"), (("question",), "help"), (("narrative",), "story"),
    (("summary",), "doc"),
]


def icon_for(heading: str) -> str:
    n = norm(heading)
    for keys, icon in _ICONS:
        if any(k in n for k in keys):
            return icon
    return "doc"
