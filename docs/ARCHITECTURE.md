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
| FRED | `ingest/fred.py` | FRED series id | API key required (free) |
| FBIL | `ingest/fbil.py` | `refrates:<pair>`, `gsec_par:<tenor>`, `<tbill\|cd\|termmibor>:<tenor>`, `ovnmibor`, `mror`, `sorr` | Public JSON API at fbil.org.in/wasdm. Public data lags about a week. G-sec par yields come from one xlsx per valuation day ("Par Yield" sheet, semi-annual), downloaded incrementally from 2025-01-01 and cached in `data/raw/fbil/gsec/`; money-market rates from 2018 |
| MoSPI | `ingest/mospi.py` | `<cpi\|nas\|plfs>/<endpoint>?<filters>[&_value=..&_top=..]` | api.mospi.gov.in/api, no token: 10-20 rows per page, so queries are filtered to one series and paged. NAS quarters are dated to the start of the fiscal-year quarter |
| RBI | `ingest/rbi.py` | `homepage:<label>` | Rate in force from the home page "Policy Rates" box. Repo/SDF/MSF/Bank Rate are dated from the matching MPC statement in RBI's recent press-release list (or the stored repo change); otherwise dated on the day observed (`meta.date_basis`) |
| IMF | `ingest/imf.py` | `WEO:<ISO3>.<INDICATOR>.A[:proj]` | IMF SDMX 3.0 API (api.imf.org), no key; latest World Economic Outlook. History/estimates (before the current year) and projections (current year on) are separate ids. imf.org's datamapper refuses scripts and is not used |
| World Bank | `ingest/worldbank.py` | `<indicator>:<ISO3>` | api.worldbank.org/v2, no key; annual |
| RBI releases (`fetcher: RBIRelease`) | `ingest/rbi_releases.py` | `mmo:<field>`, `wss:<field>`, `bop:<field>` | Parsed from rbi.org.in press releases: daily Money Market Operations (WACR, TREPS, net LAF liquidity, SDF/MSF, durable liquidity), Weekly Statistical Supplement (forex reserves, M3, bank credit, deposits), monthly BoP. Archive months read via ASP.NET POST; each release parsed once and cached in `data/raw/rbi/` |
| Commerce | `ingest/trade.py` | `pib:<field>` | Ministry of Commerce monthly trade release on PIB (www.pib.gov.in only; the bare domain drops form posts). Newest release wins for a month; balances computed as exports − imports |
| Union Budget, CGA | `ingest/budget.py` | `baag:<metric>:actual\|estimate`, `cga:<metric>` | Budget at a Glance xlsx (current + archived budgets, incl. old .xls read with the stdlib), Actuals and RE/BE kept separate; CGA monthly accounts HTML, cumulative April-to-month |

A registry entry may set `fetcher:` to route to a fetcher other than its `source` (used so RBI
press-release series still show "RBI" as their source). The GitHub workflow caches `data/raw`
between runs so only new releases are downloaded.

## Quality checks (`transform/checks.py`)
Run on the latest vintage of every stored series at the end of `run_all`; results are
printed and written to `data/logs/quality.json`, and shown in the dashboard.

| Check | Rule | Severity |
| --- | --- | --- |
| structure | missing values, future dates, negatives in index/price units, empty series | error |
| gaps | gap between observations longer than normal for the frequency, ending in the last 2 years | warn |
| jumps | moves in the last year with robust z-score > 8 against the last 3 years (one summary line per series; % changes for price levels, absolute changes for rates and flows) | warn |
| stale | latest observation older than the frequency limit (daily 14d, monthly 95d, quarterly 250d, annual 1100d) | warn; error past 2x |

Any error makes `run_all` exit 1, so the workflow opens an issue. Registry options:
`known_gaps: [<date ending the gap>]` for releases a source never published,
`expect_updates: false` for closed historical series, `projection: true` for forecasts
(future dates allowed, no staleness check), `stale_after_days: N` to override the limit.

## Storage (`storage/db.py`)
Parquet in `data/clean/` is the source of truth. `data/macrolens.duckdb` is a disposable
cache, rebuilt automatically when any Parquet file is newer. Tables: `observations` (all
vintages), `indicators` (registry). Views: `latest` (one row per date), `summary` (latest
and previous value per indicator).

## Dashboard (`app/app.py`)
Tabs, in the order users consult them: Overview, Policy rates, Currency, Bonds, Liquidity,
Inflation, Growth, External, Fiscal, Jobs, Commodities, Data quality, Data & sources (CSV
download, including vintages). Each chart shows source links and latest dates. Derived values
(YoY %, deflator, GDP shares, spreads, real repo rate) are labelled "derived". Event series are
drawn as steps extended to today. Charts silently skip series that are missing, so a failed
fetch never breaks the page.

## Decisions log
- 2026-11: India sources need no API keys: MoSPI CPI is readable without a token (paged),
  FBIL and RBI are public pages and APIs.
- 2026-11: `in_10y` is FBIL's 10-year par yield (a curve point), not a specific benchmark bond.
- 2026-11: CPI 2024 base: live series (`in_cpi_2024base`, 2025 onwards) and MoSPI's official
  back series (`in_cpi_2024base_back`, 2013-2024) are kept as separate ids, never spliced.
- 2026-11: Everything is fetched automatically; no manual data entry. The only exception was
  a one-time import of repo-rate history (2008 to Dec 2025) from RBI Handbook Table 40
  (`ingest/rbi_history.py`), because rbidocs.rbi.org.in shows scripts a bot-check page. That
  history is stored in the committed Parquet file; new changes come from the daily job.
- 2026-11: Repo rate 5.25% -> 5.50% on 2026-10-07 (MPC Oct 5-7, 2026), after the Handbook
  edition; dated from the RBI Governor's Statement of that day.
- 2026-11: US CPI has no October 2025 value (BLS did not publish it during the federal
  shutdown); recorded as a known gap.
- 2026-11: Audience is investors, businesses and FDI decision-makers (not a course project):
  coverage India first, then US, euro area and China; Japan dropped for now.
- 2026-11: Fiscal cross-country data moved from FRED's IMF copy (frozen at April 2025) to the
  IMF SDMX API (latest WEO). Union Budget figures come from the Budget at a Glance workbook
  and CGA monthly accounts (no official fiscal API exists; data.gov.in fiscal sets are stale).
- 2026-11: Not used because not current: FRED China monthly CPI (ends 2025), FRED euro area
  unemployment (ends 2023), World Bank India central government debt (ends 2018).
- 2026-11: Known holes, by source: Union Budget Actuals for FY 2022-23 (Budget 2024-25 files
  404 on indiabudget.gov.in); monthly BoP Oct 2025-Mar 2026 (monthly releases began Apr 2026);
  PLFS March 2026 (absent from the MoSPI API). Recorded as known gaps, never filled by estimation.
- 2026-11: Python + DuckDB/Parquet + Streamlit for MVP; Next.js later.
- 2026-11: GitHub Actions for scheduled ingestion.
