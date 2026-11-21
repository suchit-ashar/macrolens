"""Rule-based signals for dashboard cards (the traffic lights) and the summary line.

Every signal compares an official number with an official target or with its own recent
history. Nothing here forecasts or recommends. Levels:
  good     green   within target / improving
  watch    amber   drifting from target / deteriorating somewhat
  bad      red     outside target / deteriorating sharply
  neutral  grey    descriptive only (e.g. policy direction)
"""
from dataclasses import dataclass

import pandas as pd


@dataclass
class Signal:
    level: str
    text: str


NONE = Signal("neutral", "")


def _last(df: pd.DataFrame):
    return None if df is None or df.empty else df.sort_values("date").iloc[-1]


def value_ago(df: pd.DataFrame, days: int):
    """Value on or before (latest date - days); None if history is too short."""
    if df is None or df.empty:
        return None
    df = df.sort_values("date")
    cutoff = df["date"].iloc[-1] - pd.Timedelta(days=days)
    past = df[df["date"] <= cutoff]
    return None if past.empty else float(past["value"].iloc[-1])


def policy_stance(df: pd.DataFrame, bank: str = "RBI") -> Signal:
    """Direction of the most recent change in an event/daily policy-rate series."""
    if df is None or len(df) < 2:
        return NONE
    df = df.sort_values("date")
    changes = df[df["value"].diff().fillna(0) != 0]
    if changes.empty:
        return Signal("neutral", f"{bank} on hold")
    last = changes.iloc[-1]
    prev = df[df["date"] < last["date"]]["value"].iloc[-1]
    bp = (last["value"] - prev) * 100
    word = "tightening" if bp > 0 else "easing"
    return Signal("neutral", f"{bank} {word}: {bp:+.0f} bp on {last['date']:%d %b %Y}")


def inflation_band(value: float, low: float, high: float, target: float) -> Signal:
    """India-style band: target with a tolerance band (RBI: 4% within 2-6%)."""
    if value is None:
        return NONE
    if value > high:
        return Signal("bad", f"above the {low:g}–{high:g}% band")
    if value < low:
        return Signal("watch", f"below the {low:g}–{high:g}% band")
    if abs(value - target) <= 1:
        return Signal("good", f"near the {target:g}% target")
    return Signal("watch", f"inside the band, {'above' if value > target else 'below'} the {target:g}% target")


def inflation_target(value: float, target: float = 2.0) -> Signal:
    """Point target (Fed, ECB, BoJ: 2%)."""
    if value is None:
        return NONE
    gap = value - target
    if abs(gap) <= 0.5:
        return Signal("good", f"near the {target:g}% target")
    if abs(gap) <= 1.5:
        return Signal("watch", f"{'above' if gap > 0 else 'below'} the {target:g}% target")
    return Signal("bad", f"well {'above' if gap > 0 else 'below'} the {target:g}% target")


def growth(value: float, strong: float, weak: float) -> Signal:
    if value is None:
        return NONE
    if value >= strong:
        return Signal("good", "strong growth")
    if value >= weak:
        return Signal("watch", "moderate growth")
    return Signal("bad", "weak growth" if value >= 0 else "contraction")


def local_currency(df: pd.DataFrame, name: str = "rupee", days: int = 7) -> Signal:
    """For a 'local currency per US$' series: a higher number means a weaker local currency."""
    last, ago = _last(df), value_ago(df, days)
    if last is None or ago is None or not ago:
        return NONE
    pct = (last["value"] / ago - 1) * 100
    period = "this week" if days <= 7 else f"over {days} days"
    if abs(pct) < 0.25:
        return Signal("good", f"{name} steady {period}")
    if pct < 0:
        return Signal("good", f"{name} firmer {period} ({-pct:.1f}%)")
    return Signal("bad" if pct > 2 else "watch", f"{name} weaker {period} ({pct:.1f}%)")


def liquidity(value: float) -> Signal:
    """RBI net LAF position: negative = RBI absorbing = system in surplus."""
    if value is None:
        return NONE
    amount = f"₹{abs(value) / 1e5:,.2f} lakh cr" if abs(value) >= 1e5 else f"₹{abs(value):,.0f} cr"
    if value < 0:
        return Signal("good", f"liquidity in surplus ({amount} absorbed)")
    return Signal("watch", f"liquidity in deficit ({amount} injected)")


def reserves(df: pd.DataFrame, days: int = 28) -> Signal:
    last, ago = _last(df), value_ago(df, days)
    if last is None or ago is None or not ago:
        return NONE
    pct = (last["value"] / ago - 1) * 100
    if pct >= 0:
        return Signal("good", f"up {pct:.1f}% over 4 weeks")
    return Signal("bad" if pct < -3 else "watch", f"down {-pct:.1f}% over 4 weeks")


def trend_lower_is_better(df: pd.DataFrame, days: int, label: str, tol: float = 0.2) -> Signal:
    """For rates like unemployment: compare with `days` ago."""
    last, ago = _last(df), value_ago(df, days)
    if last is None or ago is None:
        return NONE
    d = last["value"] - ago
    if d <= -tol:
        return Signal("good", f"{label} falling")
    if d >= tol:
        return Signal("watch", f"{label} rising")
    return Signal("good", f"{label} stable")


def yield_move(df: pd.DataFrame, days: int = 30) -> Signal:
    last, ago = _last(df), value_ago(df, days)
    if last is None or ago is None:
        return NONE
    bp = (last["value"] - ago) * 100
    if abs(bp) < 15:
        return Signal("good", f"steady over a month ({bp:+.0f} bp)")
    return Signal("watch", f"{'up' if bp > 0 else 'down'} {abs(bp):.0f} bp over a month")


def at_most(value: float, limit: float, label: str) -> Signal:
    """e.g. fiscal deficit vs FRBM path, debt vs anchor (lower is better)."""
    if value is None:
        return NONE
    if value <= limit:
        return Signal("good", f"within {label}")
    return Signal("watch" if value <= limit * 1.25 else "bad", f"above {label}")


def balance(value: float, warn: float, bad: float, label: str = "deficit") -> Signal:
    """Balances where a deficit (negative) beyond thresholds is a concern, e.g. current account % GDP."""
    if value is None:
        return NONE
    if value >= -warn:
        return Signal("good", "small or surplus" if value >= 0 else f"{label} contained")
    return Signal("bad" if value < -bad else "watch", f"{label} widening")
