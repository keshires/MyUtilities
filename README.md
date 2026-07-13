# MyUtilities

Shared repository for support and day-to-day operational utilities.

## Projects

| Folder | Purpose |
|--------|---------|
| [**Day2Day_Utillites**](Day2Day_Utillites/) | Python scripts for recurring daily tasks — Postgres KPIs, EDFX/RiskCalc APIs, stale-entity exports, OpenSearch queries, batch loads, and related tooling. See [Day2Day_Utillites/Docs/](Day2Day_Utillites/Docs/) for run guides. |
| [**DocuProj**](DocuProj/) | Static analyzer for **cross-repo flows** across the EDFX fleet — traces who calls an endpoint and where it gets its data (services → database), with a swimlane dashboard and a Claude Code troubleshooting skill. See [DocuProj/README.md](DocuProj/README.md). |

## Day2Day_Utillites — quick start

```powershell
cd Day2Day_Utillites
copy .env.example .env
# Edit .env with your credentials
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

Open `Day2Day_Utillites` as the workspace folder in VS Code or Cursor so `${workspaceFolder}` debug configs resolve correctly.

### Utilities catalog & dashboard

The production scripts are cataloged in `Day2Day_Utillites/utilities.yaml`, exposed as
four Claude Code skills (`.claude/skills/`), and browsable in a read-only dashboard:

```powershell
cd Day2Day_Utillites
.\.venv\Scripts\python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021
# http://127.0.0.1:8021/app/
```

See [Day2Day_Utillites/Docs/utilities-catalog.md](Day2Day_Utillites/Docs/utilities-catalog.md).