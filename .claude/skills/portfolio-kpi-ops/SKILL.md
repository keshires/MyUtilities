---
name: portfolio-kpi-ops
description: Use when running portfolio KPI recalculations (the calculate_portfolio_kpis stored procedure) or analyzing the portfolio_kpi_update_log — hourly processing volume, status breakdowns, or slow-message analysis.
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

## Analyze the KPI update log (read-only)
`python portfolio_kpi_metrics_postgres.py --start "2026-05-20 00:00:00" --end "2026-05-21 00:00:00" --report all`
Reports: `hourly`, `hourly_by_status`, `status`, `slow`, `slow_by_source`, `all`.
Filter slow reports with `--source "Custom Financials"`; write CSVs with `--export-csv <path>`
(→ `output/portfolio_kpi_metrics/`).

## Safety
`run_portfolio_kpis_postgres.py` executes a stored procedure that recomputes KPIs on
prod — use `--list-only` to preview. The metrics script is read-only.

## Prereqs
`.env` needs the `TESSERA_POSTGRES_*` group (see `utilities.yaml`).

## Dashboard
```powershell
cd Day2Day_Utillites
.\.venv\Scripts\python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021
# http://127.0.0.1:8021/app/
```
