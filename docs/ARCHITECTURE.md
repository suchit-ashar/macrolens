# Architecture and conventions

Read this file before making any change. Keep it updated.

## Data flow
official source -> ingest/<source>.py -> data/raw (unchanged file)
  -> transform/normalize.py -> transform/checks.py -> storage (DuckDB / Parquet)
  -> analytics/ -> app/

## Observation format (long format, every series)
| column | meaning |
| --- | --- |
| date | period the value refers to (ISO, YYYY-MM-DD; month = first day) |
| indicator_id | id from config/indicators.yaml |
| country | ISO-like code: IN, US, EA, JP, GB, CN, GLOBAL |
| value | number in the unit stated in the registry |
| unit | percent, index, inr_per_usd, usd_per_barrel, inr_crore, usd_million ... |
| frequency | daily, weekly, monthly, quarterly, annual |
| source | short source name (FRED, RBI, MoSPI ...) |
| release_date | date the source published this value (if known) |
| fetched_at | UTC timestamp of our download |

## Rules
1. Raw files are saved before any processing and never edited.
2. Every fetcher exposes fetch(...) -> pandas.DataFrame in the format above.
3. Revisions: append a new row (vintage) when a value changes; never overwrite.
4. Base-year breaks: store old and new series under different indicator_ids
   (e.g. in_cpi_2012base, in_cpi_2024base). Never splice.
5. Units: store base units; convert only for display, labelled as derived.
6. India fiscal year = April-March; label annual values with their period.
7. No investment recommendations anywhere in the code or UI text.

## Storage and vintages
- `data/clean/<indicator_id>.parquet` holds every vintage. `ingest.run_all.update_indicator`
  merges each fetch through `transform.normalize.merge_vintages`: new dates and changed
  values are appended, unchanged rows are skipped.
- `frequency: event` series (policy rates) store a row only when the value changes.
- Readers must call `transform.normalize.latest_vintage(df)` to get one row per date.

## Fetchers
Every fetcher is called as `fetch(source_series, since) -> (DataFrame[date, value], meta)`.
`since` is the last stored date; only incremental fetchers use it.

| Source | Module | source_series | Notes |
| --- | --- | --- | --- |
| FRED | `ingest/fred.py` | FRED series id | API key required |
| FBIL | `ingest/fbil.py` | `refrates:<pair>`, `gsec_par:<tenor>` | Public JSON API at fbil.org.in/wasdm. Public data lags about a week. G-sec par yield comes from one xlsx per valuation day ("Par Yield" sheet, semi-annual), downloaded incrementally from 2025-01-01 and cached in `data/raw/fbil/gsec/` |
| MoSPI | `ingest/mospi.py` | `getCPIData?<query>` | api.mospi.gov.in/api/cpi. No token: 10 rows per page, so queries are filtered to one series and paged |
| RBI | `ingest/rbi.py` | `homepage:<label>` | Scrapes the "Policy Rates" box: current value only, dated on the day we see it |

## Quality checks (`transform/checks.py`)
Run on the latest vintage of every stored series at the end of `run_all`; results are
printed and written to `data/logs/quality.json`, and shown in the dashboard.

| Check | Rule | Severity |
| --- | --- | --- |
| structure | missing values, future dates, negatives in index/price units, empty series | error |
| gaps | gap between observations longer than normal for the frequency, ending in the last 2 years | warn |
| jumps | robust z-score > 8 for one of the last 30 changes | warn |
| stale | latest observation older than the frequency limit (daily 14d, monthly 80d ...) | warn; error past 2x |

Any error makes `run_all` exit 1, so the workflow opens an issue. Registry options:
`known_gaps: [<date ending the gap>]` for releases a source never published,
`expect_updates: false` for closed historical series.

## Storage (`storage/db.py`)
Parquet in `data/clean/` is the source of truth. `data/macrolens.duckdb` is a disposable
cache, rebuilt automatically when any Parquet file is newer. Tables: `observations` (all
vintages), `indicators` (registry). Views: `latest` (one row per date), `summary` (latest
and previous value per indicator).

## Dashboard (`app/app.py`)
Tabs: Overview (cards), Charts, India vs US, Data quality, Data & sources (CSV download,
including vintages). Each chart shows source link, latest date, source update date and
fetch date. Derived values (CPI YoY %, India-US spread) are labelled "derived". Event
series are drawn as steps extended to today.

## Decisions log
- 2026-11: India sources need no API keys: MoSPI CPI is readable without a token (paged),
  FBIL and RBI are public pages and APIs.
- 2026-11: `in_10y` is FBIL's 10-year par yield (a curve point), not a specific benchmark bond.
- 2026-11: CPI 2024 base: live series (`in_cpi_2024base`, 2025 onwards) and MoSPI's official
  back series (`in_cpi_2024base_back`, 2013-2024) are kept as separate ids, never spliced.
- 2026-11: Repo rate history before the first daily run is not loaded yet. Source chosen:
  RBI Handbook of Statistics, Table 40 (policy rates with effective dates). rbidocs.rbi.org.in
  serves scripts a bot-check page, so the file is downloaded once by hand and parsed.
- 2026-11: US CPI has no October 2025 value (BLS did not publish it during the federal
  shutdown); recorded as a known gap.
- 2026-11: Python + DuckDB/Parquet + Streamlit for MVP; Next.js later.
- 2026-11: GitHub Actions for scheduled ingestion.
