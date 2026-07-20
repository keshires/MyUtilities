# Portfolio KPI update log metrics

Queries and a runner for `public.portfolio_kpi_update_log` (queue audit / throughput / slow processing).

Uses Tessera Postgres: `TESSERA_POSTGRES_HOST`, `TESSERA_POSTGRES_DB`, `TESSERA_POSTGRES_USER`, `TESSERA_POSTGRES_PASSWORD` (see `.env.example`).

Install: `python -m pip install -r requirements.txt`

## Option A — Python runner

From the `Day2Day_Utillites` project folder:

| Command |
|---------|
| `python portfolio_kpi_metrics_postgres.py --help` |
| `python portfolio_kpi_metrics_postgres.py --start "2026-05-20 00:00:00" --end "2026-05-21 00:00:00" --report hourly` |
| `python portfolio_kpi_metrics_postgres.py --start "2026-05-20 00:00:00" --end "2026-05-21 00:00:00" --report hourly_by_status` |
| `python portfolio_kpi_metrics_postgres.py --start "2026-05-20 00:00:00" --end "2026-05-21 00:00:00" --report status` |
| `python portfolio_kpi_metrics_postgres.py --start "2026-05-20 00:00:00" --end "2026-05-21 00:00:00" --report slow` |
| `python portfolio_kpi_metrics_postgres.py --start "2026-05-20 15:00:00" --end "2026-05-20 18:00:00" --report slow --source "Custom Financials"` |
| `python portfolio_kpi_metrics_postgres.py --start "2026-05-20 00:00:00" --end "2026-05-21 00:00:00" --report slow_by_source` |
| `python portfolio_kpi_metrics_postgres.py --start "2026-05-20 00:00:00" --end "2026-05-21 00:00:00" --report all` |
| `python portfolio_kpi_metrics_postgres.py --start "2026-05-20 00:00:00" --end "2026-05-21 00:00:00" --report hourly --export-csv hourly.csv` |

Copy only the text inside the table cell into the terminal.

### Reports

| `--report` | What it measures |
|------------|------------------|
| `daily` | Message counts per day, per source |
| `hourly` | Received vs processed per hour, per source |
| `hourly_by_status` | Received vs processed per hour, per status |
| `status` | Row counts by status |
| `source_update_totals` | Total updates + distinct portfolios per source |
| `portfolio_updates_by_source` | Update count per portfolio, per source |
| `portfolio_update_totals` | Total update count per portfolio |
| `entity_counts` | Per-entity trigger counts, per source |
| `entity_source_totals` | Entity trigger totals per source |
| `entities_by_day` | Entity triggers per day, per source |
| `entities_by_day_source_status` | Entity triggers per day / source / status (#1) |
| `portfolios_by_day_source_status` | Portfolio refreshes per day / source / status (#2) |
| `entity_by_source` | 2D pivot: entity × source (#3a) |
| `portfolio_entity_source` | 2D pivot: (portfolio, entity) × source (#3b) |
| `slow` | Completed jobs slower than global P95 |
| `slow_by_source` | Slow relative to per-source P95 |
| `all` | Runs the aggregate reports (not slow detail / pivots) |

Flags: `--source NAME` scopes the whole run; `--top N` caps stdout rows for the
two pivot reports; `--env {ci,qa,stg,prod}` loads `.env.<env>` ahead of base `.env`;
`--export-csv PATH` writes one CSV per report (relative → `output/portfolio_kpi_metrics/`).

### Performance

The runner builds two session TEMP tables once per run (`tmp_kpi_window`,
`tmp_kpi_entity`) with `source` extracted to a plain column and the entity array
pre-`unnest`ed, then every report reads from them — one base-table scan instead
of one per report. For ad-hoc base-table queries in DBeaver, see the optional
`portfolio-kpi-indexes.sql`.

## Option B — DBeaver (`portfolio-kpi-metrics.sql`)

Open [`portfolio-kpi-metrics.sql`](portfolio-kpi-metrics.sql).

### Step 1 — Set datetimes once (PARAMS block)

At the top of the file, edit **only** these three values:

```sql
SELECT
  set_config('portfolio_kpi.window_start', '2026-05-20 00:00:00', false),
  set_config('portfolio_kpi.window_end',   '2026-05-21 00:00:00', false),
  set_config('portfolio_kpi.source_filter', '', false);
```

| Setting | Meaning |
|---------|---------|
| `window_start` | Inclusive lower bound |
| `window_end` | Exclusive upper bound |
| `source_filter` | Optional for slow reports — `''` = all, or `'Custom Financials'` |

Select the **PARAMS** block and **Execute** (Ctrl+Enter) **once per DBeaver session** (or after you change the window).

Optional: uncomment the `SELECT current_setting(...)` block right below PARAMS to verify active values.

### Step 1b — Build the working set (SETUP, once per session)

After PARAMS, select the `-- SETUP: build_temp` block and Execute it once.
It creates `tmp_kpi_window` and `tmp_kpi_entity`. Every REPORT reads from these,
so re-run SETUP whenever you change the PARAMS window/source.

### Step 2 — Run any report

Each report reads session params via a `params` CTE — **no timestamps inside the query body**.

1. Select one report block (from `-- REPORT: ...` through its ending `;`).
2. **Execute SQL statement** (Ctrl+Enter).

You can run different reports without editing dates again, as long as you executed PARAMS for that session.

### Report names

| `-- REPORT:` tag | Python `--report` |
|------------------|-------------------|
| `hourly_totals` | `hourly` |
| `hourly_by_status` | `hourly_by_status` |
| `status_summary` | `status` |
| `slow_global` | `slow` |
| `slow_by_source` | `slow_by_source` |

## Definitions

- **Received per hour**: count where `message_received_at` falls in that hour (any `status`).
- **Processed per hour**: count where `processing_completed_at` falls in that hour.
- **Slow**: processing duration above P95 baseline in the same analysis window.

Pending rows (no `processing_completed_at`) appear in **received** / `status` counts but not in **processed** or **slow** reports.
