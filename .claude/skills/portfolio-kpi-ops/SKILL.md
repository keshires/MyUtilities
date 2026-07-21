---
name: portfolio-kpi-ops
description: Use when running portfolio KPI recalculations (the calculate_portfolio_kpis stored procedure) or analyzing the portfolio_kpi_update_log — volume by day/hour, per source/status/entity/portfolio breakdowns, 2D pivots, or slow-message analysis (optimized temp-table reports; multi-env via --env).
---

# Portfolio KPI Ops

Tools live in `Day2Day_Utillites/`. Run from that folder with `.\.venv\Scripts\python`
and a populated `.env`. Canonical args/env are in `Day2Day_Utillites/utilities.yaml`.

## Recalculate KPIs
Preview the id list first (no writes):
`python run_portfolio_kpis_postgres.py --tenant-id <TENANT> --list-only`
Then run the stored procedure:
`python run_portfolio_kpis_postgres.py --tenant-id <TENANT>`
Target specific portfolios with `--portfolio-id <ID>` (repeatable) or `--portfolio-ids 1,2,3`;
export the resolved list with `--export-list <file.csv>`.
→ log in `logs/run_portfolio_kpis/`, optional CSV in `output/run_portfolio_kpis/`.

## Analyze the KPI update log (read-only, optimized temp-table reports)
`python portfolio_kpi_metrics_postgres.py --start "2026-05-20 00:00:00" --end "2026-05-21 00:00:00" --report all`
The runner builds two session TEMP tables once per run (`tmp_kpi_window`, `tmp_kpi_entity`), then every
report reads from them (one base-table scan instead of one per report).
Reports: `daily`, `hourly`, `hourly_by_status`, `status`, `source_update_totals`,
`portfolio_updates_by_source`, `portfolio_update_totals`, `entity_counts`, `entity_source_totals`,
`entities_by_day`, `entities_by_day_source_status`, `portfolios_by_day_source_status`,
`entity_by_source` (2D pivot), `portfolio_entity_source` (2D pivot), `slow`, `slow_by_source`, `all`.
`all` runs the aggregate set (not slow detail or the two pivots).
Flags: `--source "Custom Financials"` scopes the whole run; `--top N` caps stdout rows for the two
pivots (CSV keeps all); `--env {ci,qa,stg,prod}` loads `.env.<env>` ahead of base `.env`;
`--export-csv <path>` → `output/portfolio_kpi_metrics/`.

## Safety
`run_portfolio_kpis_postgres.py` executes a stored procedure that recomputes KPIs on
prod — use `--list-only` to preview. The metrics script is read-only.

## Prereqs
`.env` needs the `TESSERA_POSTGRES_*` group (see `utilities.yaml`). For non-prod, copy
`.env.qa.example` → `.env.qa` (or `.env.ci` / `.env.stg`), fill it, and run with `--env qa`.

## Dashboard
```powershell
cd Day2Day_Utillites
.\.venv\Scripts\python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021
# http://127.0.0.1:8021/app/
```
