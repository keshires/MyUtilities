# MyUtilities

Shared repository for support and day-to-day operational utilities.

## Projects

| Folder | Purpose |
|--------|---------|
| [**Day2Day_Utillites**](Day2Day_Utillites/) | Python scripts for recurring daily tasks — Postgres KPIs, EDFX/RiskCalc APIs, stale-entity exports, OpenSearch queries, batch loads, and related tooling. See [Day2Day_Utillites/Docs/](Day2Day_Utillites/Docs/) for run guides. |
| [**DocuProj**](DocuProj/) | Documentation project assets. |

## Day2Day_Utillites — quick start

```powershell
cd Day2Day_Utillites
copy .env.example .env
# Edit .env with your credentials
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

Open `Day2Day_Utillites` as the workspace folder in VS Code or Cursor so `${workspaceFolder}` debug configs resolve correctly.
