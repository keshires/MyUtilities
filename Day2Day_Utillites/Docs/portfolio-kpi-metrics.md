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
| `hourly` | Messages **received** per hour and **processed** per hour; all statuses |
| `hourly_by_status` | Same, grouped by `status` |
| `status` | Row counts by `status` in the window |
| `slow` | Completed jobs slower than **global P95** processing time |
| `slow_by_source` | Same, but “slow” is above **P95 per** source |
| `all` | Runs every report above |

Optional `--source` applies only to `slow` and `slow_by_source`.

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
