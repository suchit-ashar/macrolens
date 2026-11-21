"""Data quality checks on stored series: structure, gaps, jumps and staleness.

Each check returns Issue records. Severity:
  error  something is structurally wrong, or a series is badly out of date; ingestion fails
  warn   worth a look (a holiday-length gap, an unusual move, a release running late)
"""
from dataclasses import asdict, dataclass
from datetime import date

import pandas as pd

from transform.normalize import latest_vintage

# Largest normal gap between consecutive observations, in calendar days.
MAX_GAP = {"daily": 7, "weekly": 10, "monthly": 32, "quarterly": 95, "annual": 370}
# Days since the latest observation before the series counts as stale. Monthly series are
# dated on the 1st and published 2-6 weeks after the month ends, hence the generous limit.
STALE_AFTER = {"daily": 14, "weekly": 21, "monthly": 80, "quarterly": 200, "annual": 500}
GAP_WINDOW_DAYS = 730
JUMP_Z = 8.0         # robust z-score of a period-on-period change
JUMP_WINDOW = 30      # only the most recent N changes are checked for jumps
NON_NEGATIVE_UNITS = {"index", "inr_per_usd", "usd_per_barrel"}


@dataclass
class Issue:
    indicator_id: str
    check: str
    severity: str
    message: str


def check_structure(df: pd.DataFrame, entry: dict, today: date) -> list[Issue]:
    iid, out = entry["id"], []
    if df.empty:
        return [Issue(iid, "structure", "error", "no observations stored")]
    if df["value"].isna().any():
        out.append(Issue(iid, "structure", "error", f"{int(df['value'].isna().sum())} missing values"))
    if df["date"].max().date() > today:
        out.append(Issue(iid, "structure", "error", f"observation dated in the future ({df['date'].max().date()})"))
    if entry["unit"] in NON_NEGATIVE_UNITS and (df["value"] < 0).any():
        out.append(Issue(iid, "structure", "error", "negative values in a non-negative unit"))
    return out


def check_gaps(df: pd.DataFrame, entry: dict, today: date) -> list[Issue]:
    """Gaps ending in the last GAP_WINDOW_DAYS. Older gaps are history, not news.

    Gaps documented in the registry (`known_gaps`: dates of the observation that ends the
    gap) are skipped, e.g. a release the source never published.
    """
    limit = MAX_GAP.get(entry["frequency"])
    if limit is None or len(df) < 2:
        return []
    dates = df["date"].sort_values().reset_index(drop=True)
    gaps = dates.diff().dt.days
    known = {pd.Timestamp(d) for d in entry.get("known_gaps", [])}
    recent = dates >= pd.Timestamp(today) - pd.Timedelta(days=GAP_WINDOW_DAYS)
    big = gaps[(gaps > limit) & recent & ~dates.isin(known)]
    if big.empty:
        return []
    worst = big.idxmax()
    prev = dates[dates < dates[worst]].max()
    return [Issue(entry["id"], "gaps", "warn",
                  f"{len(big)} gap(s) over {limit} days; largest {int(big.max())} days "
                  f"({prev.date()} to {dates[worst].date()})")]


def check_jumps(df: pd.DataFrame, entry: dict) -> list[Issue]:
    if entry["frequency"] == "event" or len(df) < JUMP_WINDOW + 10:
        return []
    s = df.sort_values("date").set_index("date")["value"]
    change = s.pct_change() if entry["unit"] in NON_NEGATIVE_UNITS else s.diff()
    change = change.dropna()
    mad = (change - change.median()).abs().median() * 1.4826
    if not mad:
        return []
    z = (change - change.median()) / mad
    recent = z.tail(JUMP_WINDOW)
    flagged = recent[recent.abs() > JUMP_Z]
    return [Issue(entry["id"], "jumps", "warn",
                  f"unusual move on {d.date()}: {change[d]:+.4g}{' (fraction)' if entry['unit'] in NON_NEGATIVE_UNITS else ''}, "
                  f"robust z = {z[d]:.1f}") for d in flagged.index]


def check_stale(df: pd.DataFrame, entry: dict, today: date) -> list[Issue]:
    limit = STALE_AFTER.get(entry["frequency"])
    if limit is None or entry.get("expect_updates") is False or df.empty:
        return []
    age = (pd.Timestamp(today) - df["date"].max()).days
    if age <= limit:
        return []
    severity = "error" if age > 2 * limit else "warn"
    return [Issue(entry["id"], "stale", severity,
                  f"latest observation {df['date'].max().date()} is {age} days old (limit {limit})")]


def run_checks(df: pd.DataFrame, entry: dict, today: date | None = None) -> list[Issue]:
    """All checks for one indicator, on its latest vintage."""
    today = today or date.today()
    current = latest_vintage(df) if not df.empty else df
    issues = check_structure(current, entry, today)
    if any(i.severity == "error" for i in issues) and current.empty:
        return issues
    return issues + check_gaps(current, entry, today) + check_jumps(current, entry) + check_stale(current, entry, today)


def to_records(issues: list[Issue]) -> list[dict]:
    return [asdict(i) for i in issues]
