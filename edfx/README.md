# EDFX Utilities

Day-to-day operational scripts for EDFX support — Postgres KPIs, stale-entity refresh,
OpenSearch queries, Financials API, and DynamoDB batch ops.

## Setup

```powershell
cd edfx
copy .env.example .env          # fill in your credentials
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

Open the `edfx/` folder as the workspace root in VS Code/Cursor so `${workspaceFolder}`
debug configs in `.vscode/launch.json` resolve correctly.

## Script Catalog

| Script | Purpose |
|--------|---------|
| `scripts/EDFX_ProcessStatus.py` | Check EDFX process/job statuses and generate an error report |
| `scripts/DynamoDB_BatchUpdate_CreatedBy.py` | Batch-update the CreatedBy field across DynamoDB records |
| `scripts/export_stale_entities_from_excel.py` | Export stale entities from Excel input to CSV for refresh |
| `scripts/financials_delete_custom_entity.py` | Delete custom entities via the Financials API |
| `scripts/build_opensearch_entity_query_from_csv.py` | Build OpenSearch _search queries from a CSV of company identifiers |
| `scripts/monitor_entity_refresh_status.py` | Monitor entity refresh status and resubmit downstream failures |
| `scripts/pd_precheck.py` | Pre-check PD values before a refresh cycle |
| `scripts/portfolio_kpi_metrics_postgres.py` | Pull portfolio KPI metrics from Postgres |
| `scripts/refresh_stale_non_public_entities.py` | Submit stale private/custom entities for refresh via Tessera |
| `scripts/reprocess_stuck_financials.py` | Reprocess stuck financials jobs |
| `scripts/run_portfolio_kpis_postgres.py` | Run the calculate_portfolio_kpis stored procedure |
| `scripts/test_single_entity_refresh.py` | Test a single entity refresh end-to-end |
| `scripts/validate_pd_precheck.py` | Validate PD pre-check results |
| `scripts/validate_stale_entities.py` | Validate stale entity export results |
| `scripts/validate_stale_pd_source.py` | Validate PD source data for stale entities |

## Runbooks

See `runbooks/` for step-by-step operational guides:
- `monthly-stale-refresh-runbook.md` — monthly stale entity refresh procedure
- `run-portfolio-kpis-postgres.md` — running portfolio KPI calculations
- `portfolio-kpi-metrics.md` — KPI metrics reference

## Dashboard

Browse all utilities in a read-only dashboard:

```powershell
.\.venv\Scripts\python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021
# Open: http://127.0.0.1:8021/app/
```

## Input / Output / Logs

Each utility reads/writes under `input/<utility>/`, `output/<utility>/`, `logs/<utility>/`.
These folders are gitignored — create them locally as needed.
