# MacroLens

Your morning market briefing, plus live macro data for India and the world's major economies.

**Live dashboard: https://macromonitor.streamlit.app/** (Streamlit Community Cloud; refreshes
after each daily data commit).

## Status
143 series, all fetched automatically every day at 04:30 IST (GitHub Actions), in the order
users consult them: policy rates, currency, bonds, liquidity, inflation, growth, external,
fiscal, jobs, commodities. Coverage: India first, then US, euro area and China.

Sources: RBI (policy rates, daily liquidity, forex reserves, M3/credit, BoP), FBIL (bond
curve, T-bills, CDs, MIBOR, INR reference rates), MoSPI (CPI, GDP, PLFS), Union Budget and
CGA (deficits, monthly accounts), Ministry of Commerce (trade), FRED (US, ECB, FX), IMF WEO
(debt, deficits, projections) and World Bank. Only FRED needs a (free) key.
No manual data entry; IMF projections and budget estimates are separate, labelled series.

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
