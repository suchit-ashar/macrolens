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
