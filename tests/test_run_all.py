from datetime import date

import pandas as pd

from ingest.run_all import update_indicator

ENTRY = {"id": "inr_usd", "country": "IN", "unit": "inr_per_usd", "frequency": "daily",
         "source": "FAKE", "source_series": "x", "source_url": "https://www.fbil.org.in/"}


def test_update_passes_since_and_keeps_history(tmp_path):
    calls = []

    def fake(series, since):
        calls.append(since)
        if since is None:
            return pd.DataFrame({"date": pd.to_datetime(["2026-11-12"]), "value": [94.05]}), \
                {"fetched_at": "2026-11-20T01:00:00"}
        return pd.DataFrame({"date": pd.to_datetime(["2026-11-13"]), "value": [94.20]}), \
            {"fetched_at": "2026-11-21T01:00:00"}

    update_indicator(ENTRY, clean_dir=tmp_path, fetchers={"FAKE": fake})
    out = update_indicator(ENTRY, clean_dir=tmp_path, fetchers={"FAKE": fake})
    assert calls == [None, date(2026, 11, 12)]
    assert list(out["value"]) == [94.05, 94.20]
    assert pd.read_parquet(tmp_path / "inr_usd.parquet").shape[0] == 2
