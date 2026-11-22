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
MAX_GAP = {"daily": 7, "weekly": 10, "fortnightly": 20, "monthly": 32, "quarterly": 95, "annual": 370}
# Days since the latest observation before the series counts as stale. Periods are dated at
# their start and published weeks (monthly), ~2 months (quarterly) or 6-18 months (annual,
# World Bank) after they end, hence the generous limits. Override per series with
# `stale_after_days` in the registry.
STALE_AFTER = {"daily": 14, "weekly": 21, "fortnightly": 45, "monthly": 95, "quarterly": 250, "annual": 1100}
GAP_WINDOW_DAYS = 730
JUMP_Z = 8.0              # robust z-score of a period-on-period change
JUMP_WINDOW_DAYS = 365    # only changes in the last year are reported
JUMP_BASELINE_DAYS = 3 * 365  # what counts as "normal" is judged on the last 3 years
MIN_JUMP_HISTORY = 40     # need this many observations to judge what is "unusual"
# Price levels that cannot be negative; FDI, balances and growth rates can be.
NON_NEGATIVE_UNITS = {"index", "inr_per_usd", "inr", "cny", "jpy", "usd_per_barrel", "usd_per_eur", "eur_million",
                      "jpy_billion", "inr_per_10g"}
# Levels whose moves are judged in % terms; rates, ratios and near-zero flows use absolute changes.
PCT_CHANGE_UNITS = {"index", "inr_per_usd", "inr", "cny", "jpy", "usd_per_barrel", "usd_million", "eur_million",
                    "jpy_billion", "usd_per_eur", "inr_per_10g"}


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
    if df["date"].max().date() > today and not entry.get("projection"):
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


def check_jumps(df: pd.DataFrame, entry: dict, today: date) -> list[Issue]:
    """One summary issue if the last year holds moves far outside the last three years' norm.

    Price levels (indices, exchange rates, oil) use % changes; rates, ratios and flows that
    can sit near zero use absolute changes. The baseline is the last 3 years only, so old
    regimes (e.g. a currency peg) do not make today's normal moves look extreme.
    """
    if (entry["frequency"] in ("event", "annual") or entry.get("projection") or entry.get("skip_jumps")
            or len(df) < MIN_JUMP_HISTORY):
        return []
    s = df.sort_values("date").set_index("date")["value"]
    s = s[s.index >= pd.Timestamp(today) - pd.Timedelta(days=JUMP_BASELINE_DAYS)]
    change = (s.pct_change() if entry["unit"] in PCT_CHANGE_UNITS else s.diff()).dropna()
    if len(change) < MIN_JUMP_HISTORY:
        return []
    mad = (change - change.median()).abs().median() * 1.4826
    if not mad:
        return []
    z = (change - change.median()) / mad
    recent = z[z.index >= pd.Timestamp(today) - pd.Timedelta(days=JUMP_WINDOW_DAYS)]
    flagged = recent[recent.abs() > JUMP_Z]
    if flagged.empty:
        return []
    worst = flagged.abs().idxmax()
    pct = entry["unit"] in PCT_CHANGE_UNITS
    size = f"{change[worst] * 100:+.2f}%" if pct else f"{change[worst]:+.4g}"
    return [Issue(entry["id"], "jumps", "warn",
                  f"{len(flagged)} unusual move(s) in the last year; largest {size} on {worst.date()} "
                  f"(robust z = {z[worst]:.1f})")]


def check_stale(df: pd.DataFrame, entry: dict, today: date) -> list[Issue]:
    limit = entry.get("stale_after_days") or STALE_AFTER.get(entry["frequency"])
    if limit is None or entry.get("expect_updates") is False or entry.get("projection") or df.empty:
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
    return issues + check_gaps(current, entry, today) + check_jumps(current, entry, today) + check_stale(current, entry, today)


def to_records(issues: list[Issue]) -> list[dict]:
    return [asdict(i) for i in issues]
