# MyUtilities — Multi-App Repo Reorganization Design

**Date:** 2026-09-01
**Status:** Approved — ready for implementation

## Goal

Reorganize `MyUtilities` from a flat, EDFX-only structure into a clean, app-scoped support repo that any developer on EDFX, Credit Edge, or RiskCalc can navigate, use, and extend — without needing prior knowledge of the codebase.

---

## Top-Level Structure

```
MyUtilities/
│
├── edfx/               ← EDFX scripts, runbooks, utilities
├── credit-edge/        ← Credit Edge scripts, runbooks
├── riskcalc/           ← RiskCalc scripts, runbooks
│
├── docuproj/           ← Cross-repo flow analyzer (standalone project)
│
├── shared/             ← Code shared across all three apps
│   ├── REPOS.md        ← Fleet repo registry (DocuProj reads from here)
│   └── project_paths.py
│
├── docs/
│   ├── architecture.md ← How this repo is organized
│   └── contributing.md ← How to add a new script or runbook
│
└── README.md           ← Repo index — what each folder is, quick-start per app
```

---

## Per-App Folder Anatomy

Every app folder follows the same internal layout. A developer who knows EDFX can immediately navigate RiskCalc.

```
edfx/                        (same pattern for credit-edge/ and riskcalc/)
│
├── scripts/                 ← Python scripts (one file per utility)
├── runbooks/                ← Markdown step-by-step ops guides
├── sql/                     ← SQL files used by scripts or runbooks
├── input/                   ← Script input files (CSVs, Excel) — gitignored
├── output/                  ← Script output files — gitignored
├── logs/                    ← Run logs — gitignored
├── tests/                   ← Test files for scripts
├── archive/                 ← Scripts no longer active but kept for reference
├── docs/                    ← Supporting docs, reports, slide decks
│
├── .env.example             ← All env vars this app needs, with descriptions
├── requirements.txt         ← Python dependencies for this app only
└── README.md                ← What this app's utilities do + setup steps
```

EDFX additionally contains:
```
edfx/
├── dashboard/               ← Utilities catalog dashboard (EDFX-specific)
└── utilities.yaml           ← Machine-readable catalog for the dashboard + skills
```

---

## File Migration Map

### Scripts

| Current Location | Destination | App |
|---|---|---|
| `Day2Day_Utillites/EDFX_ProcessStatus.py` | `edfx/scripts/` | EDFX |
| `Day2Day_Utillites/DynamoDB_BatchUpdate_CreatedBy.py` | `edfx/scripts/` | EDFX |
| `Day2Day_Utillites/export_stale_entities_from_excel.py` | `edfx/scripts/` | EDFX |
| `Day2Day_Utillites/financials_delete_custom_entity.py` | `edfx/scripts/` | EDFX |
| `Day2Day_Utillites/build_opensearch_entity_query_from_csv.py` | `edfx/scripts/` | EDFX |
| `Day2Day_Utillites/monitor_entity_refresh_status.py` | `edfx/scripts/` | EDFX |
| `Day2Day_Utillites/pd_precheck.py` | `edfx/scripts/` | EDFX |
| `Day2Day_Utillites/portfolio_kpi_metrics_postgres.py` | `edfx/scripts/` | EDFX |
| `Day2Day_Utillites/refresh_stale_non_public_entities.py` | `edfx/scripts/` | EDFX |
| `Day2Day_Utillites/reprocess_stuck_financials.py` | `edfx/scripts/` | EDFX |
| `Day2Day_Utillites/run_portfolio_kpis_postgres.py` | `edfx/scripts/` | EDFX |
| `Day2Day_Utillites/test_single_entity_refresh.py` | `edfx/scripts/` | EDFX |
| `Day2Day_Utillites/validate_pd_precheck.py` | `edfx/scripts/` | EDFX |
| `Day2Day_Utillites/validate_stale_entities.py` | `edfx/scripts/` | EDFX |
| `Day2Day_Utillites/validate_stale_pd_source.py` | `edfx/scripts/` | EDFX |
| `Day2Day_Utillites/SecurityService.py` | `riskcalc/scripts/` | RiskCalc |
| `Day2Day_Utillites/LC_Process.py` | `riskcalc/scripts/` | RiskCalc |

### Archive

| Current Location | Destination | App |
|---|---|---|
| `Day2Day_Utillites/archive/LDGLoadTest.py` | `riskcalc/archive/` | RiskCalc |
| `Day2Day_Utillites/archive/Sample_RCTest.py` | `riskcalc/archive/` | RiskCalc |
| `Day2Day_Utillites/archive/Sample2Test.py` | `riskcalc/archive/` | RiskCalc |
| `Day2Day_Utillites/archive/SampleTest.py` | `riskcalc/archive/` | RiskCalc |
| `Day2Day_Utillites/archive/PeerMetricFile.py` | `edfx/archive/` | EDFX |
| `Day2Day_Utillites/archive/pyspakrPeedata.py` | `edfx/archive/` | EDFX |
| `Day2Day_Utillites/archive/pysparkpoc.py` | `edfx/archive/` | EDFX |
| `Day2Day_Utillites/archive/README.md` | `edfx/archive/README.md` | EDFX (update to reflect RC files moved out) |

### Runbooks & Docs

| Current Location | Destination | App |
|---|---|---|
| `Day2Day_Utillites/Docs/monthly-stale-refresh-runbook.md` | `edfx/runbooks/` | EDFX |
| `Day2Day_Utillites/Docs/run-portfolio-kpis-postgres.md` | `edfx/runbooks/` | EDFX |
| `Day2Day_Utillites/Docs/portfolio-kpi-metrics.md` | `edfx/runbooks/` | EDFX |
| `Day2Day_Utillites/Docs/july-2026-file-processing-report.md` | `edfx/runbooks/` | EDFX |
| `Day2Day_Utillites/Docs/portfolio-kpi-reports-implementation-summary.md` | `edfx/docs/` | EDFX |
| `Day2Day_Utillites/Docs/AI-Team-Demo-One-Slide.pptx` | `edfx/docs/` | EDFX |
| `Day2Day_Utillites/Docs/july-2026-file-processing-report.csv` | `edfx/docs/` | EDFX |
| `docs/runbooks/slow-sp-ce2-report-builder-pit.md` | `credit-edge/runbooks/` | Credit Edge |

### SQL

| Current Location | Destination | App |
|---|---|---|
| `Day2Day_Utillites/Docs/portfolio-kpi-indexes.sql` | `edfx/sql/` | EDFX |
| `Day2Day_Utillites/Docs/portfolio-kpi-metrics.sql` | `edfx/sql/` | EDFX |
| `Day2Day_Utillites/sql/diagnose_slow_sp_blocking.sql` | `credit-edge/sql/` | Credit Edge |

### Infrastructure & Shared

| Current Location | Destination | Note |
|---|---|---|
| `Day2Day_Utillites/project_paths.py` | `shared/project_paths.py` | Used by EDFX + RiskCalc |
| `DocuProj/REPOS.md` | `shared/REPOS.md` | DocuProj reads from here |
| `Day2Day_Utillites/requirements.txt` | `edfx/requirements.txt` | EDFX deps |
| `Day2Day_Utillites/utilities.yaml` | `edfx/utilities.yaml` | EDFX catalog |
| `Day2Day_Utillites/dashboard/` | `edfx/dashboard/` | EDFX-only dashboard |
| `Day2Day_Utillites/tests/` | `edfx/tests/` | All EDFX tests |
| `Day2Day_Utillites/BulkUplaodFiles/` | `edfx/input/` | EDFX input data |
| `DocuProj/` (folder) | `docuproj/` | Rename only — no content changes |
| `.claude/skills/` | `.claude/skills/` | Stays at repo root — no change |

### Folders Removed After Migration

- `Day2Day_Utillites/` — fully emptied and deleted
- `docs/runbooks/` — CE runbook moved out, folder deleted

---

## New Files Created

| File | Purpose |
|---|---|
| `edfx/README.md` | EDFX setup, script catalog, quick-start |
| `edfx/.env.example` | EDFX-specific env vars with descriptions |
| `riskcalc/README.md` | RiskCalc setup, script catalog |
| `riskcalc/requirements.txt` | RiskCalc deps: aiohttp, nest_asyncio, python-dotenv, requests |
| `riskcalc/.env.example` | RiskCalc env vars (RISKCALC_SECURITY_SOAP_URL, etc.) |
| `credit-edge/README.md` | Credit Edge setup and script catalog (stub, grows over time) |
| `credit-edge/requirements.txt` | Empty stub with placeholder comment |
| `credit-edge/.env.example` | Empty stub with placeholder comment |
| `shared/README.md` | What lives in shared/ and how to use it |
| `docs/architecture.md` | How this repo is organized — the map for new devs |
| `docs/contributing.md` | How to add a new script or runbook (team guide) |

---

## Shared Infrastructure

### `shared/project_paths.py`

Scripts that import `project_paths` add this at the top of the file — pathlib ensures it resolves correctly regardless of where the script is invoked from:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))
```

No packaging needed.

### `shared/REPOS.md`

DocuProj's internal config that maps repo names to local clone paths. Moved out of `DocuProj/` so it's a repo-level resource — any tool or team member can reference the fleet registry without going into DocuProj internals. DocuProj's bootstrap/config is updated to read from `../shared/REPOS.md`.

---

## Requirements Split

| File | Key Dependencies |
|---|---|
| `edfx/requirements.txt` | requests, pandas, openpyxl, asyncpg, boto3, python-dotenv, fastapi, uvicorn, pydantic, PyYAML |
| `riskcalc/requirements.txt` | aiohttp, nest_asyncio, python-dotenv, requests |
| `credit-edge/requirements.txt` | Empty stub — team fills as scripts are added |

---

## Claude Code Skills & Dashboard

**`.claude/skills/` stays at repo root.** Claude Code discovers skills from the workspace root. The five existing skills remain in place. New skills for Credit Edge and RiskCalc are added to the same folder prefixed `credit-edge-*` or `riskcalc-*`.

**Dashboard stays under `edfx/`.** It reads `edfx/utilities.yaml` and is EDFX-specific. Credit Edge and RiskCalc add their own `utilities.yaml` and dashboard when ready.

---

## Team Conventions (`docs/contributing.md`)

### Adding a new script
1. Drop it in `<app>/scripts/`
2. Add an entry to `<app>/utilities.yaml` (name, description, usage, env vars)
3. Create `input/<script-name>/`, `output/<script-name>/`, `logs/<script-name>/` if the script uses files
4. Write a runbook in `<app>/runbooks/` if it is an ops procedure

### Adding a runbook only (no script)
1. Drop the `.md` file in `<app>/runbooks/`
2. Follow the existing runbook format: header, prerequisites, env vars used, step-by-step instructions

### Adding a shared utility
1. Place it in `shared/`
2. Reference it with `sys.path.insert(0, "../shared")` in the consuming script
3. Update `shared/README.md`

---

## .gitignore Updates

Each app folder's `input/`, `output/`, and `logs/` directories are gitignored. These entries are added to the **root `.gitignore`** (the existing one at `MyUtilities/.gitignore`):

```
edfx/input/
edfx/output/
edfx/logs/
credit-edge/input/
credit-edge/output/
credit-edge/logs/
riskcalc/input/
riskcalc/output/
riskcalc/logs/
```

---

## Out of Scope

- No changes to script logic or imports beyond the `project_paths` path fix
- No changes to DocuProj internals beyond updating the REPOS.md reference path and the folder rename
- No changes to `.claude/skills/` content — existing skills continue to work as-is
- The EDFX dashboard is not redesigned — it moves as-is
