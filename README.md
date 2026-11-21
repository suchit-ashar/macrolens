# MacroLens

A macro dashboard that tracks official data for India, the US and other leading
economies, and turns it into plain-language regime views, global linkages and
historical scenarios. Educational only; not investment advice.

## Status
Phase 1 in progress: all 10 MVP indicators have fetchers and run daily via GitHub Actions.
- US: FRED (needs `FRED_API_KEY`).
- India: RBI repo rate (home page), MoSPI CPI 2024 base (live + back series), FBIL USD/INR
  reference rate and 10-year G-sec par yield. None of these need keys.

- Every run ends with quality checks (gaps, unusual jumps, stale or malformed series).
- Dashboard: Streamlit app over a DuckDB cache of the Parquet files.

## Everyday commands
```bash
python -m ingest.run_all                 # fetch everything + quality report
python -m ingest.run_all inr_usd in_10y  # fetch selected indicators
python -m storage.db                     # rebuild data/macrolens.duckdb and print latest values
streamlit run app/app.py                 # open the dashboard at http://localhost:8501
```

## Setup
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then add your API keys
pytest                    # all tests should pass
```

## Project layout
| Folder | Purpose |
| --- | --- |
| `config/` | `indicators.yaml`: every series, its source, unit and frequency |
| `ingest/` | One fetcher per source (FRED, RBI, MoSPI, ...) |
| `transform/` | Unit/frequency normalisation, quality checks |
| `analytics/` | Regime scores, Taylor rule, event studies |
| `storage/` | DuckDB database access |
| `app/` | Streamlit dashboard |
| `data/raw/` | Untouched downloads (audit trail, not committed) |
| `data/clean/` | Cleaned Parquet files, every vintage (committed by the daily job) |
| `data/logs/` | `quality.json` from the last run (not committed) |
| `tests/` | pytest tests |

## Principles
- Every chart shows source, link and release date.
- Raw data is never modified; derived series are labelled.
- Revisions are stored as vintages, not overwritten.
- Series breaks (e.g. India's 2026 CPI/GDP/IIP base changes) are never spliced.

## Disclaimer
For education only. Not investment advice or a research recommendation.
