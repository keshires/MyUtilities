# Credit Edge Utilities

Scripts and runbooks for Credit Edge support operations.

## Setup

```powershell
cd credit-edge
copy .env.example .env          # fill in your credentials (add vars as scripts are added)
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Runbooks

| Runbook | Purpose |
|---------|---------|
| `runbooks/slow-sp-ce2-report-builder-pit.md` | Diagnose and resolve slow stored procedure in CE2 report builder |

## SQL

| File | Purpose |
|------|---------|
| `sql/diagnose_slow_sp_blocking.sql` | Query to identify blocking sessions causing slow SP execution |

## Adding Scripts

See [docs/contributing.md](../docs/contributing.md) for how to add new scripts to this folder.
