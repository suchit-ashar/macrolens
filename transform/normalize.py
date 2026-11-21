"""Convert any fetcher output into the standard long format (see docs/ARCHITECTURE.md)."""
import pandas as pd

COLUMNS = ["date", "indicator_id", "country", "value", "unit", "frequency",
           "source", "source_url", "release_date", "fetched_at"]


def to_long(df: pd.DataFrame, entry: dict, release_date=None, fetched_at=None) -> pd.DataFrame:
    out = pd.DataFrame({"date": pd.to_datetime(df["date"]), "value": df["value"].astype(float)})
    out["indicator_id"] = entry["id"]
    out["country"] = entry["country"]
    out["unit"] = entry["unit"]
    out["frequency"] = entry["frequency"]
    out["source"] = entry["source"]
    out["source_url"] = entry["source_url"]
    out["release_date"] = release_date
    out["fetched_at"] = fetched_at
    return out[COLUMNS].sort_values("date").reset_index(drop=True)


def latest_vintage(df: pd.DataFrame) -> pd.DataFrame:
    """One row per date: the most recently fetched value. Use this before charting/analytics."""
    if df.empty:
        return df
    return (df.sort_values(["date", "fetched_at"], na_position="first")
              .drop_duplicates("date", keep="last").reset_index(drop=True))


def merge_vintages(existing: pd.DataFrame | None, new: pd.DataFrame, event: bool = False,
                   tol: float = 1e-9) -> pd.DataFrame:
    """Append new observations without overwriting history (ARCHITECTURE.md rule 3).

    - default: a row is added for a date that is new, or whose value differs from the
      latest stored vintage for that date (a revision).
    - event=True (e.g. policy rates observed daily): a row is added only when the value
      differs from the most recent stored value.
    """
    if existing is None or existing.empty:
        return new.sort_values("date").reset_index(drop=True)
    current = latest_vintage(existing)
    if event:
        last = current.iloc[-1]["value"]
        add = []
        for _, row in new.sort_values("date").iterrows():
            if row["date"] > current.iloc[-1]["date"] and abs(row["value"] - last) > tol:
                add.append(row)
                last = row["value"]
        added = pd.DataFrame(add, columns=new.columns)
    else:
        joined = new.merge(current[["date", "value"]], on="date", how="left", suffixes=("", "_old"))
        changed = joined["value_old"].isna() | ((joined["value"] - joined["value_old"]).abs() > tol)
        added = new[changed.to_numpy()]
    if added.empty:
        return existing.reset_index(drop=True)
    out = pd.concat([existing, added], ignore_index=True)
    return out.sort_values(["date", "fetched_at"], na_position="first").reset_index(drop=True)


def yoy_pct(df: pd.DataFrame, periods: int = 12) -> pd.DataFrame:
    """Year-on-year % change for a monthly index (periods=12) or quarterly (periods=4)."""
    out = df.copy().sort_values("date")
    out["value"] = out["value"].pct_change(periods) * 100
    return out.dropna(subset=["value"])
