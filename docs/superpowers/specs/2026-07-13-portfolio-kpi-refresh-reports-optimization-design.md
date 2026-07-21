# Portfolio KPI refresh reports — optimization + new reports + multi-env

Date: 2026-07-13
Status: Approved (design), pending spec review

## Problem

`public.portfolio_kpi_update_log` has grown large enough that the operator's
regular queries against it are slow. Each report re-scans the windowed slice of
the (range-partitioned) table and re-parses `entity_refresh_message` JSONB to
extract `source`. The operator also needs three new report shapes and the
ability to run all reports against non-prod environments (CI / QA / STG).

We extend the existing runner [`portfolio_kpi_metrics_postgres.py`](../../../Day2Day_Utillites/portfolio_kpi_metrics_postgres.py)
and its SQL file [`portfolio-kpi-metrics.sql`](../../../Day2Day_Utillites/Docs/portfolio-kpi-metrics.sql)
rather than adding a new script. The tool stays **read-only**.

### Table (relevant bits)

```
public.portfolio_kpi_update_log  -- PARTITION BY RANGE (message_created_at)
  message_created_at   timestamp   -- partition key; btree index
  portfolio_id         int4
  triggering_entity_external_ids  text[]
  status               varchar(50) -- btree index
  duration_seconds     numeric(10,3)
  entity_refresh_message  jsonb     -- GIN index (containment only)
  message_received_at, processing_started_at, processing_completed_at  timestamp
```

### Why it is slow (DB-architect analysis)

1. **`entity_refresh_message->>'source'` is the main cost.** The only JSONB
   index is GIN, which accelerates containment (`@>`) — not `->>` key
   extraction. Every row is parsed and the `source` key pulled out, per query,
   for both `WHERE` and `GROUP BY`.
2. **The table is re-scanned once per report.** Running the full set is ~12
   independent windowed partition scans, each repeating the JSONB extraction
   and (for entity reports) the `unnest`.
3. **`COUNT(DISTINCT …)` + `unnest LATERAL`** compound the per-row JSONB cost.
4. The window filter (`message_created_at >= … < …`) is the *good* part — it
   enables partition pruning and uses the `message_created_at` btree. It is
   preserved exactly.

## Goals

- Make the whole regular report set fast on current data volume.
- Add three requested reports (entities per day/source/status; portfolios per
  day/source/status; two 2D pivots).
- Run any report against CI / QA / STG via `--env`, with safe env-file handling.
- Preserve read-only behavior and the existing DBeaver workflow.

## Non-goals

- No writes to the database.
- No automatic creation of persistent (prod) indexes — shipped as an optional
  manual migration only.
- No new standalone script; we extend the existing runner.

## Approach — "extract once, aggregate many"

The runner builds **two session TEMP tables once per run** (after the session
params are set, before any report), then every report reads from them. Because
the runner uses a single connection for the whole run and issues statements in
autocommit, TEMP tables (default `ON COMMIT PRESERVE ROWS`) persist for the
lifetime of that run.

### `tmp_kpi_window`
The `message_created_at`-windowed slice (partition-pruned). Materializes, once:

- `id`, `message_created_at`, `message_id`, `portfolio_id`
- `status`            — `COALESCE(status, '(null)')`
- `source`            — `COALESCE(entity_refresh_message->>'source', '(null)')` as **plain text**
- `"group"`           — `entity_refresh_message->>'group'`
- `day`               — `date_trunc('day', message_created_at)::date`
- `message_received_at`, `processing_started_at`, `processing_completed_at`
- `duration_seconds`
- `process_seconds_computed` — `EXTRACT(EPOCH FROM (processing_completed_at - processing_started_at))` rounded(3), NULL when either endpoint is NULL
- `queue_wait_seconds`       — `EXTRACT(EPOCH FROM (processing_started_at - message_received_at))` rounded(3)
- `triggering_entity_external_ids` — `text[]`
- `entity_refresh_message`   — raw `jsonb` (needed by slow-detail reports)

Filter at build time:
```
WHERE message_created_at >= :start AND message_created_at < :end
  AND ( :source_filter IS NULL OR entity_refresh_message->>'source' = :source_filter )
```
Indexes after load: `(source)`, `(day)`, `(status)`; then `ANALYZE`.

### `tmp_kpi_entity`
`tmp_kpi_window` with `triggering_entity_external_ids` pre-`unnest`ed — one row
per entity trigger:

```
day, portfolio_id, source, status, entity_id
```
Built from `tmp_kpi_window` with
`CROSS JOIN LATERAL unnest(triggering_entity_external_ids) AS entity_id`
where `triggering_entity_external_ids IS NOT NULL AND cardinality(...) > 0`.
Indexes: `(source)`, `(day)`, `(entity_id)`, `(portfolio_id)`; then `ANALYZE`.

### Net effect
The full report run goes from ~12 windowed partition scans (each re-parsing
JSONB) to **1 scan + 1 unnest**, with all JSONB extraction done exactly once.

### Optional prod index (separate, not baked in)
Ship `Day2Day_Utillites/Docs/portfolio-kpi-indexes.sql` documenting an optional
expression index for ad-hoc DBeaver queries that hit the base table directly:
```sql
-- Run in a maintenance window; CONCURRENTLY avoids a long table lock.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_portfolio_kpi_log_source
  ON public.portfolio_kpi_update_log ((entity_refresh_message->>'source'));
```
For a partitioned parent, `CREATE INDEX` on the parent cascades to partitions
(cannot combine with `CONCURRENTLY` on the parent) — the file documents both the
per-partition CONCURRENTLY approach and the parent cascade, with the trade-off.

## Reports

All reports SELECT from the temp tables. Report bodies live in the SQL file
tagged `-- REPORT: <name>`; a new `-- SETUP: build_temp` block holds the
`CREATE TEMP TABLE` statements the runner executes once per run.

**Naming rule:** existing `-- REPORT:` marker names in the SQL file are
**preserved** (DBeaver users reference them by muscle memory). The Python CLI
maps friendly `--report` values to markers via the existing `REPORT_ALIASES`
dict. New reports add new markers and new aliases.

Existing markers (rewritten to read temp tables, **same marker names, same
output columns**), with their CLI alias:

| SQL marker | CLI `--report` |
|------------|----------------|
| `hourly_totals` | `hourly` |
| `hourly_by_status` | `hourly_by_status` |
| `status_summary` | `status` |
| `slow_global` | `slow` |
| `slow_by_source` | `slow_by_source` |
| `daily_totals_source` | `daily` |
| `portfolio_updates_by_source` | `portfolio_updates_by_source` |
| `portfolio_update_totals` | `portfolio_update_totals` |
| `source_update_totals` | `source_update_totals` |
| `triggering_entity_counts` | `entity_source_totals` |
| `triggering_entity_counts_by_day` | `entities_by_day` |

New (new markers + aliases):

| SQL marker / CLI alias | Grain | Columns |
|------------------------|-------|---------|
| `entities_by_day_source_status` (#1) | `tmp_kpi_entity` grouped by day, source, status | `day, source, status, entity_trigger_count, distinct_entities, portfolios_affected` |
| `portfolios_by_day_source_status` (#2) | `tmp_kpi_window` grouped by day, source, status | `day, source, status, message_count, distinct_portfolios` |
| `entity_by_source` (#3a) | pivot of `tmp_kpi_entity` by entity_id × source | `entity_id, <one column per source>, total` |
| `portfolio_entity_source` (#3b) | pivot of `tmp_kpi_entity` by (portfolio_id, entity_id) × source | `portfolio_id, entity_id, <one column per source>, total` |

### Pivots
Built **in Python** (dynamic source columns; no `tablefunc` dependency). The
SQL returns long form (`… , source, refresh_count`); a generic
`pivot_rows(rows, index_cols, pivot_col, value_col)` helper produces wide dict
rows with source columns sorted alphabetically plus a `total` column, ordered by
`total DESC`. New `--top N` flag caps rows printed to stdout (CSV export always
gets all rows). `--top` applies only to pivot reports.

### `--report all`
Runs the aggregate reports only (excludes the two large pivots and the slow
detail reports): `daily, hourly, hourly_by_status, status,
entity_source_totals, entities_by_day, entities_by_day_source_status,
portfolios_by_day_source_status`.

## Semantic decisions (confirmed with operator)

- **`--source` scopes the whole run.** The filter is applied when building
  `tmp_kpi_window`, so `status` and `hourly_by_status` also become
  source-filtered when `--source` is passed (previously they ignored it).
  Consistent-is-better.
- **"per Day"** = `date_trunc('day', message_created_at)::date` (the partition
  key), matching the operator's `daily_totals_source`.
- Timestamps are `timestamp` (no tz); treated as UTC, matching existing code.
- Rows created in-window whose `message_received_at` / `processing_completed_at`
  fall outside the window keep the original hourly semantics: `tmp_kpi_window`
  is `message_created_at`-windowed, and hourly reports add their own
  `received/completed in-window` predicates on the temp table.

## Multi-environment (`--env`)

- New `--env NAME` argument (documented choices: `ci`, `qa`, `stg`, `prod`; any
  name accepted). Default from `KPI_ENV` env var, else base `.env` only.
- **Load order** (first non-empty wins because `python-dotenv` is called with
  `override=False`): existing OS env vars → `.env.<env>` → `.env`. So OS env
  always wins; env-specific file beats base; base fills gaps.
- Argument parsing happens before env loading is finalized: `main()` parses
  args, then calls `_load_dotenv(env)`, then `PostgresSettings.from_env()`.
- If `--env X` is given but `.env.X` does not exist, print a warning and
  continue (base `.env` / OS env may still satisfy required vars).

### Env-file templates & gitignore
- Commit `Day2Day_Utillites/.env.ci.example`, `.env.qa.example`,
  `.env.stg.example` — each containing only the read-only Postgres group
  (`TESSERA_POSTGRES_*`) and optional `PORTFOLIO_*`, with a header noting the
  target environment. **No secrets.**
- Operator copies each to `.env.ci` / `.env.qa` / `.env.stg` and fills values.
- Update `Day2Day_Utillites/.gitignore`:
  ```
  .env
  .env.*
  !.env.example
  !*.example
  ```
  so filled-in per-env files are never tracked while `*.example` templates are.

## CLI surface (final)

```
python portfolio_kpi_metrics_postgres.py \
  --start "2026-06-05 00:00:00" --end "2026-06-30 23:59:00" \
  --report entities_by_day_source_status \
  [--env qa] [--source "Custom Financials"] [--top 50] [--export-csv name.csv]
```

`--report` choices grow to include the new report names above. `--env`,
`--top` are new. `--start`, `--end`, `--source`, `--export-csv` unchanged.

## Error handling

- Reuse existing `parse_timestamp`, `--end > --start` guard, and
  `PostgresSettings.from_env()` missing-var `SystemExit`.
- Missing `.env.<env>` → warning, not fatal.
- Pivot with zero rows → print "(no rows)" (existing `print_table` behavior);
  CSV export writes an empty file (existing behavior).
- Temp-table SETUP runs inside the same connection as reports; if SETUP fails,
  the run aborts with the DB error (no partial reports).

## Testing

- **SQL smoke (manual, read-only):** run each report for a small window against
  a non-prod env via `--env`; confirm columns and non-negative counts.
- **Pivot unit test:** `pivot_rows` with a hand-built long-form fixture →
  asserts dynamic columns, `total`, ordering, and `--top` truncation. No DB.
- **Env-loading unit test:** `_load_dotenv` precedence (OS > `.env.<env>` >
  `.env`) using temp files and monkeypatched `os.environ`. No DB.
- **Parity check:** for one window, `entities_by_day_source` (temp-table
  version) totals match the operator's original base-table query.

## Files touched

- `Day2Day_Utillites/portfolio_kpi_metrics_postgres.py` — `--env`, `_load_dotenv`,
  SETUP execution, temp-table-based report loading, `pivot_rows`, `--top`.
- `Day2Day_Utillites/Docs/portfolio-kpi-metrics.sql` — `-- SETUP: build_temp`,
  rewritten reports reading temp tables, four new report blocks.
- `Day2Day_Utillites/Docs/portfolio-kpi-indexes.sql` — new, optional prod index.
- `Day2Day_Utillites/Docs/portfolio-kpi-metrics.md` — new reports, `--env`,
  `--top`, temp-table note, DBeaver "run SETUP once per session" step.
- `Day2Day_Utillites/.env.ci.example`, `.env.qa.example`, `.env.stg.example` — new.
- `Day2Day_Utillites/.gitignore` — ignore `.env.*` except `*.example`.
- `Day2Day_Utillites/utilities.yaml` — update the `portfolio-kpi-metrics-postgres`
  entry (new args/reports).
- Tests under `Day2Day_Utillites/` per existing test layout.
