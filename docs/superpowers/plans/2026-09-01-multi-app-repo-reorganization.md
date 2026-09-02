# Multi-App Repo Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize `MyUtilities` from a flat EDFX-only layout into a clean three-app structure (`edfx/`, `credit-edge/`, `riskcalc/`) with a standalone `docuproj/` and a `shared/` layer, so any team member can navigate, use, and extend the repo without prior context.

**Architecture:** App-first top-level folders, each self-contained with its own `scripts/`, `runbooks/`, `.env.example`, and `requirements.txt`. A `shared/` folder holds `project_paths.py` (used by EDFX and RiskCalc) and `REPOS.md` (fleet registry for DocuProj). `project_paths.py` is updated to detect the calling script's app root via `inspect`, so all 18 consuming scripts only need a `sys.path.insert` addition — no other logic changes.

**Tech Stack:** Python 3.x, git (for history-preserving moves), pytest

**Spec:** [docs/superpowers/specs/2026-09-01-multi-app-repo-reorganization-design.md](../specs/2026-09-01-multi-app-repo-reorganization-design.md)

## Global Constraints

- All file moves use `git mv` to preserve git history
- No changes to script logic beyond: adding `sys.path.insert` block, fixing `.env` load path, and the `project_paths.py` rewrite
- No changes to DocuProj internals beyond: folder rename and REPOS.md path references in comments/docs
- `.claude/skills/` stays at repo root — no changes
- All `git mv` commands run from `c:/Github/MyUtilities/` (repo root)
- Windows paths: use forward slashes in git commands (Git Bash)

---

## Task 1: Scaffold Folder Structure and Update .gitignore

**Files:**
- Create: `edfx/scripts/`, `edfx/runbooks/`, `edfx/sql/`, `edfx/input/`, `edfx/output/`, `edfx/logs/`, `edfx/tests/`, `edfx/archive/`, `edfx/docs/`
- Create: `credit-edge/scripts/`, `credit-edge/runbooks/`, `credit-edge/sql/`, `credit-edge/input/`, `credit-edge/output/`, `credit-edge/logs/`, `credit-edge/tests/`, `credit-edge/archive/`
- Create: `riskcalc/scripts/`, `riskcalc/runbooks/`, `riskcalc/sql/`, `riskcalc/input/`, `riskcalc/output/`, `riskcalc/logs/`, `riskcalc/tests/`, `riskcalc/archive/`
- Create: `shared/`
- Modify: `.gitignore`

**Interfaces:**
- Produces: folder skeleton all subsequent tasks drop files into

- [ ] **Step 1: Create all app folders with .gitkeep placeholders**

Run from repo root (`c:/Github/MyUtilities/`):

```bash
# EDFX
mkdir -p edfx/scripts edfx/runbooks edfx/sql edfx/input edfx/output edfx/logs edfx/tests edfx/archive edfx/docs
# Credit Edge
mkdir -p credit-edge/scripts credit-edge/runbooks credit-edge/sql credit-edge/input credit-edge/output credit-edge/logs credit-edge/tests credit-edge/archive
# RiskCalc
mkdir -p riskcalc/scripts riskcalc/runbooks riskcalc/sql riskcalc/input riskcalc/output riskcalc/logs riskcalc/tests riskcalc/archive
# Shared
mkdir -p shared
# .gitkeep so empty dirs are tracked
touch edfx/scripts/.gitkeep edfx/runbooks/.gitkeep edfx/sql/.gitkeep edfx/tests/.gitkeep edfx/archive/.gitkeep edfx/docs/.gitkeep
touch credit-edge/scripts/.gitkeep credit-edge/runbooks/.gitkeep credit-edge/sql/.gitkeep credit-edge/tests/.gitkeep credit-edge/archive/.gitkeep
touch riskcalc/scripts/.gitkeep riskcalc/runbooks/.gitkeep riskcalc/sql/.gitkeep riskcalc/tests/.gitkeep riskcalc/archive/.gitkeep
touch shared/.gitkeep
```

- [ ] **Step 2: Update root .gitignore**

Open `.gitignore` at repo root and append these lines at the bottom:

```
# Per-app runtime directories (gitignored at each level)
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

Also remove (or comment out) the old `Day2Day_Utillites`-specific entries that will no longer apply once that folder is removed:
```
# Remove these lines (they'll be orphaned after migration):
# BulkUplaodFiles/corporate_input_run_output/
```

- [ ] **Step 3: Verify structure**

```bash
find edfx credit-edge riskcalc shared -maxdepth 1 -type d | sort
```

Expected: all 25 directories listed.

- [ ] **Step 4: Commit scaffold**

```bash
git add edfx/ credit-edge/ riskcalc/ shared/ .gitignore
git commit -m "chore: scaffold multi-app folder structure (edfx, credit-edge, riskcalc, shared)"
```

---

## Task 2: Move EDFX Scripts and Supporting Infrastructure

**Files:**
- Move: 15 EDFX scripts → `edfx/scripts/`
- Move: `Day2Day_Utillites/tests/` → `edfx/tests/`
- Move: `Day2Day_Utillites/dashboard/` → `edfx/dashboard/`
- Move: `Day2Day_Utillites/utilities.yaml` → `edfx/utilities.yaml`
- Move: `Day2Day_Utillites/BulkUplaodFiles/` → `edfx/input/`
- Move: `Day2Day_Utillites/requirements.txt` + `requirements-dev.txt` → `edfx/`
- Move: `Day2Day_Utillites/.env.example` + per-env examples → `edfx/`
- Move: `Day2Day_Utillites/.vscode/` → `edfx/.vscode/`

**Interfaces:**
- Consumes: folder skeleton from Task 1
- Produces: all EDFX scripts in `edfx/scripts/`, tests in `edfx/tests/`, dashboard in `edfx/dashboard/`

- [ ] **Step 1: git mv EDFX scripts**

```bash
git mv Day2Day_Utillites/EDFX_ProcessStatus.py edfx/scripts/
git mv Day2Day_Utillites/DynamoDB_BatchUpdate_CreatedBy.py edfx/scripts/
git mv Day2Day_Utillites/export_stale_entities_from_excel.py edfx/scripts/
git mv Day2Day_Utillites/financials_delete_custom_entity.py edfx/scripts/
git mv Day2Day_Utillites/build_opensearch_entity_query_from_csv.py edfx/scripts/
git mv Day2Day_Utillites/monitor_entity_refresh_status.py edfx/scripts/
git mv Day2Day_Utillites/pd_precheck.py edfx/scripts/
git mv Day2Day_Utillites/portfolio_kpi_metrics_postgres.py edfx/scripts/
git mv Day2Day_Utillites/refresh_stale_non_public_entities.py edfx/scripts/
git mv Day2Day_Utillites/reprocess_stuck_financials.py edfx/scripts/
git mv Day2Day_Utillites/run_portfolio_kpis_postgres.py edfx/scripts/
git mv Day2Day_Utillites/test_single_entity_refresh.py edfx/scripts/
git mv Day2Day_Utillites/validate_pd_precheck.py edfx/scripts/
git mv Day2Day_Utillites/validate_stale_entities.py edfx/scripts/
git mv Day2Day_Utillites/validate_stale_pd_source.py edfx/scripts/
```

- [ ] **Step 2: git mv tests, dashboard, utilities.yaml, BulkUplaodFiles**

```bash
# Tests directory (move contents, not folder, since edfx/tests/ already exists)
git mv Day2Day_Utillites/tests/test_customized_modes.py edfx/tests/
git mv Day2Day_Utillites/tests/test_env_loading.py edfx/tests/
git mv Day2Day_Utillites/tests/test_pd_precheck.py edfx/tests/
git mv Day2Day_Utillites/tests/test_pd_precheck_api_resolver.py edfx/tests/
git mv Day2Day_Utillites/tests/test_pd_precheck_fincompleted.py edfx/tests/
git mv Day2Day_Utillites/tests/test_pd_precheck_ids_file.py edfx/tests/
git mv Day2Day_Utillites/tests/test_pd_precheck_pds.py edfx/tests/
git mv Day2Day_Utillites/tests/test_pd_precheck_resolver.py edfx/tests/
git mv Day2Day_Utillites/tests/test_pd_precheck_status.py edfx/tests/
git mv Day2Day_Utillites/tests/test_pivot_rows.py edfx/tests/
git mv Day2Day_Utillites/tests/test_refresh_precheck.py edfx/tests/
git mv Day2Day_Utillites/tests/test_report_registry.py edfx/tests/
git mv Day2Day_Utillites/tests/test_report_routing.py edfx/tests/
git mv Day2Day_Utillites/tests/test_sql_file.py edfx/tests/
git mv Day2Day_Utillites/tests/test_sql_sections.py edfx/tests/
git mv Day2Day_Utillites/tests/test_validate_pd_precheck.py edfx/tests/

# Dashboard (move folder directly — it doesn't exist yet at destination)
git mv Day2Day_Utillites/dashboard edfx/dashboard

# Catalog and dependencies
git mv Day2Day_Utillites/utilities.yaml edfx/utilities.yaml
git mv Day2Day_Utillites/requirements.txt edfx/requirements.txt
git mv Day2Day_Utillites/requirements-dev.txt edfx/requirements-dev.txt

# Env examples
git mv Day2Day_Utillites/.env.example edfx/.env.example
git mv "Day2Day_Utillites/.env.ci.example" "edfx/.env.ci.example"
git mv "Day2Day_Utillites/.env.qa.example" "edfx/.env.qa.example"
git mv "Day2Day_Utillites/.env.stg.example" "edfx/.env.stg.example"

# VS Code debug configs
git mv Day2Day_Utillites/.vscode edfx/.vscode

# Input data (BulkUplaodFiles → input, preserving subfolder)
git mv Day2Day_Utillites/BulkUplaodFiles edfx/input/BulkUplaodFiles
```

- [ ] **Step 3: Update .vscode/launch.json program paths**

Open `edfx/.vscode/launch.json`. Every `"program"` entry currently points to `"${workspaceFolder}/script_name.py"`. Update each to `"${workspaceFolder}/scripts/script_name.py"`.

Example — before:
```json
"program": "${workspaceFolder}/financials_delete_custom_entity.py"
```
After:
```json
"program": "${workspaceFolder}/scripts/financials_delete_custom_entity.py"
```

Apply this change for every `"program"` entry in the file. The `"cwd"`, `"python"`, and `"envFile"` entries are correct as-is since they all resolve against `${workspaceFolder}` = `edfx/`.

- [ ] **Step 4: Clean up edfx/.env.example — remove RiskCalc sections**

The moved `.env.example` contains RiskCalc-specific vars. Open `edfx/.env.example` and delete these entire sections (they're captured in `riskcalc/.env.example` created in Task 10):

```
# --- LGD batch load test (LDGLoadTest.py)  ... through ... LGD_STATUS_REQUEST_COUNT=500
# --- RiskCalc SOAP — SecurityService.py    ... through ... RISKCALC_AUTH_BODY_PASSWORD=
# --- RiskCalc SOAP — Sample_RCTest.py      ... through ... RISKCALC_LICENSE_PRODUCT_IDS=5
# --- RiskCalc REST — SampleTest.py         ... through ... RISKCALC_REST_PASSWORD=
# --- LC_Process.py example (optional)      ... through ... LC_BATCH_ROOT_FOLDER=...
```

- [ ] **Step 5: Clean up edfx/requirements.txt — remove RiskCalc-only deps**

Open `edfx/requirements.txt` and remove these lines (only needed by RiskCalc):
```
# Async HTTP (for SampleTest.py)
aiohttp>=3.8.0
nest_asyncio>=1.5.0
```

- [ ] **Step 6: Update script paths in edfx/utilities.yaml**

Every `script:` entry in `utilities.yaml` currently lists just the filename (e.g., `script: export_stale_entities_from_excel.py`). After the move scripts live in `scripts/` so the dashboard display would show the wrong path. Update every `script:` entry to include the subfolder prefix:

```yaml
# Before:
script: export_stale_entities_from_excel.py

# After:
script: scripts/export_stale_entities_from_excel.py
```

Apply this change to every `script:` entry in the file. Do not change any other fields — `args.default`, `output_glob`, and `logs_glob` are all relative to `PROJECT_ROOT` (= `edfx/`) and are already correct.

- [ ] **Step 7: Verify counts**

```bash
ls edfx/scripts/ | wc -l   # expect 15
ls edfx/tests/ | grep "^test_" | wc -l  # expect 16
ls edfx/dashboard/  # expect: __init__.py app manifest.py runs.py serve.py
```

- [ ] **Step 7: Commit EDFX move**

```bash
git add -A
git commit -m "chore(edfx): move scripts, tests, dashboard, and supporting files to edfx/"
```

---

## Task 3: Move EDFX Docs, Runbooks, SQL, and Archive

**Files:**
- Move: `Day2Day_Utillites/Docs/*.md` runbooks → `edfx/runbooks/`
- Move: `Day2Day_Utillites/Docs/*.sql` → `edfx/sql/`
- Move: `Day2Day_Utillites/Docs/` remaining files → `edfx/docs/`
- Move: `Day2Day_Utillites/archive/` EDFX files → `edfx/archive/`

**Interfaces:**
- Consumes: folder skeleton from Task 1

- [ ] **Step 1: git mv EDFX runbooks**

```bash
git mv "Day2Day_Utillites/Docs/monthly-stale-refresh-runbook.md" edfx/runbooks/
git mv "Day2Day_Utillites/Docs/run-portfolio-kpis-postgres.md" edfx/runbooks/
git mv "Day2Day_Utillites/Docs/portfolio-kpi-metrics.md" edfx/runbooks/
git mv "Day2Day_Utillites/Docs/july-2026-file-processing-report.md" edfx/runbooks/
```

- [ ] **Step 2: git mv EDFX SQL**

```bash
git mv "Day2Day_Utillites/Docs/portfolio-kpi-indexes.sql" edfx/sql/
git mv "Day2Day_Utillites/Docs/portfolio-kpi-metrics.sql" edfx/sql/
```

- [ ] **Step 3: git mv remaining EDFX docs**

```bash
git mv "Day2Day_Utillites/Docs/portfolio-kpi-reports-implementation-summary.md" edfx/docs/
git mv "Day2Day_Utillites/Docs/AI-Team-Demo-One-Slide.pptx" edfx/docs/
git mv "Day2Day_Utillites/Docs/july-2026-file-processing-report.csv" edfx/docs/
```

Note: `Day2Day_Utillites/Docs/superpowers/` — skip this; it's Claude Code skill documentation that lives with the skills, not with EDFX content.

- [ ] **Step 4: git mv EDFX archive files**

```bash
git mv Day2Day_Utillites/archive/PeerMetricFile.py edfx/archive/
git mv Day2Day_Utillites/archive/pyspakrPeedata.py edfx/archive/
git mv Day2Day_Utillites/archive/pysparkpoc.py edfx/archive/
git mv Day2Day_Utillites/archive/README.md edfx/archive/README.md
```

After moving, open `edfx/archive/README.md` and remove any mention of the RiskCalc files (`LDGLoadTest.py`, `Sample_RCTest.py`, `Sample2Test.py`, `SampleTest.py`) — they've moved to `riskcalc/archive/`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(edfx): move runbooks, SQL, docs, and archive to edfx/"
```

---

## Task 4: Move RiskCalc Scripts and Archive

**Files:**
- Move: `Day2Day_Utillites/SecurityService.py` → `riskcalc/scripts/`
- Move: `Day2Day_Utillites/LC_Process.py` → `riskcalc/scripts/`
- Move: 4 RC archive files → `riskcalc/archive/`

**Interfaces:**
- Consumes: folder skeleton from Task 1

- [ ] **Step 1: git mv RiskCalc scripts**

```bash
git mv Day2Day_Utillites/SecurityService.py riskcalc/scripts/
git mv Day2Day_Utillites/LC_Process.py riskcalc/scripts/
```

- [ ] **Step 2: git mv RiskCalc archive**

```bash
git mv Day2Day_Utillites/archive/LDGLoadTest.py riskcalc/archive/
git mv Day2Day_Utillites/archive/Sample_RCTest.py riskcalc/archive/
git mv Day2Day_Utillites/archive/Sample2Test.py riskcalc/archive/
git mv Day2Day_Utillites/archive/SampleTest.py riskcalc/archive/
```

- [ ] **Step 3: Verify**

```bash
ls riskcalc/scripts/   # expect: LC_Process.py  SecurityService.py
ls riskcalc/archive/   # expect: LDGLoadTest.py Sample2Test.py Sample_RCTest.py SampleTest.py
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(riskcalc): move scripts and archive files to riskcalc/"
```

---

## Task 5: Move Credit Edge Files

**Files:**
- Move: `docs/runbooks/slow-sp-ce2-report-builder-pit.md` → `credit-edge/runbooks/`
- Move: `Day2Day_Utillites/sql/diagnose_slow_sp_blocking.sql` → `credit-edge/sql/`

**Interfaces:**
- Consumes: folder skeleton from Task 1

- [ ] **Step 1: git mv Credit Edge files**

```bash
git mv docs/runbooks/slow-sp-ce2-report-builder-pit.md credit-edge/runbooks/
git mv Day2Day_Utillites/sql/diagnose_slow_sp_blocking.sql credit-edge/sql/
```

- [ ] **Step 2: Verify**

```bash
ls credit-edge/runbooks/   # expect: slow-sp-ce2-report-builder-pit.md
ls credit-edge/sql/        # expect: diagnose_slow_sp_blocking.sql
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore(credit-edge): move runbook and SQL to credit-edge/"
```

---

## Task 6: Move Shared Files and Rename DocuProj

**Files:**
- Move: `Day2Day_Utillites/project_paths.py` → `shared/project_paths.py`
- Move: `DocuProj/REPOS.md` → `shared/REPOS.md`
- Rename: `DocuProj/` → `docuproj/`
- Modify: `docuproj/README.md`, `docuproj/bootstrap.py`, `docuproj/flow.py`, `docuproj/.claude/skills/troubleshooting-edfx-flows/SKILL.md` — update REPOS.md path mentions

**Interfaces:**
- Produces: `shared/project_paths.py` ready for the rewrite in Task 7; `shared/REPOS.md` at its permanent location

- [ ] **Step 1: Move project_paths.py to shared/**

```bash
git mv Day2Day_Utillites/project_paths.py shared/project_paths.py
```

- [ ] **Step 2: Move REPOS.md to shared/**

```bash
git mv DocuProj/REPOS.md shared/REPOS.md
```

- [ ] **Step 3: Rename DocuProj → docuproj**

On Windows, git is case-insensitive — rename via an intermediate name:

```bash
git mv DocuProj docuproj_tmp
git mv docuproj_tmp docuproj
```

- [ ] **Step 4: Update REPOS.md path references in docuproj**

In `docuproj/README.md`, find the line:
```
REPOS.md       the 21-repo EDFX fleet, languages, default branches
```
Update it to:
```
../shared/REPOS.md    the 21-repo EDFX fleet, languages, default branches
```

In `docuproj/bootstrap.py`, find the comment referencing REPOS.md (line ~12, ~24) and update to `../shared/REPOS.md`:
```python
# edfx-api is `master`, the rest `main` (see ../shared/REPOS.md).
```
and:
```python
# `language` is informational here; flow.py auto-detects it. Add rows from ../shared/REPOS.md as needed.
```

In `docuproj/flow.py`, find:
```python
print(f"No repos cloned in {WS}. See the troubleshooting-edfx-flows skill / REPOS.md.")
```
Update to:
```python
print(f"No repos cloned in {WS}. See the troubleshooting-edfx-flows skill / ../shared/REPOS.md.")
```

In `docuproj/.claude/skills/troubleshooting-edfx-flows/SKILL.md`, find the three references to `REPOS.md` and update to `../shared/REPOS.md`. (Three occurrences on lines ~15, ~32, ~112, ~115.)

- [ ] **Step 5: Verify**

```bash
ls shared/                    # expect: REPOS.md  project_paths.py  .gitkeep
ls docuproj/                  # expect: README.md  bootstrap.py  flow.py  engine/  etc.
git status --short            # all changes should be renames (R) not deletes (D)
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: move project_paths+REPOS.md to shared/, rename DocuProj→docuproj"
```

---

## Task 7: Rewrite project_paths.py for Caller-Aware PROJECT_ROOT

**Files:**
- Modify: `shared/project_paths.py`
- Test: `edfx/tests/test_project_paths.py` (new)

**Interfaces:**
- Produces: `PROJECT_ROOT: Path`, `logs_dir(*parts) -> Path`, `output_dir(*parts) -> Path`, `input_dir(*parts) -> Path`, `resolve_project_relative(path_str: str) -> str`, `resolve_cli_artifact(path: Path, *subfolders) -> Path`

**Why the rewrite:** Currently `PROJECT_ROOT = Path(__file__).resolve().parent`. After moving to `shared/`, `__file__` points to `shared/project_paths.py` — meaning `PROJECT_ROOT` would be `shared/`, not `edfx/` or `riskcalc/`. The fix uses `inspect.stack()` to find the first non-internal caller: scripts live at `<app>/<subfolder>/script.py`, so `caller.parent.parent == <app>/`.

- [ ] **Step 1: Write the failing test**

Create `edfx/tests/test_project_paths.py`:

```python
from pathlib import Path
import sys

# Will be importable after conftest.py is added in Task 9; for now verify the module directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
import project_paths


def test_project_root_resolves_to_app_folder():
    # This test file lives at edfx/tests/test_project_paths.py
    # parent.parent should be edfx/
    expected = Path(__file__).resolve().parent.parent
    assert project_paths.PROJECT_ROOT == expected


def test_logs_dir_under_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(project_paths, "PROJECT_ROOT", tmp_path)
    result = project_paths.logs_dir("run1")
    assert result == tmp_path / "logs" / "run1"
    assert result.exists()


def test_output_dir_under_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(project_paths, "PROJECT_ROOT", tmp_path)
    result = project_paths.output_dir("exports")
    assert result == tmp_path / "output" / "exports"
    assert result.exists()


def test_resolve_project_relative_absolute_passthrough(tmp_path, monkeypatch):
    monkeypatch.setattr(project_paths, "PROJECT_ROOT", tmp_path)
    abs_path = str(tmp_path / "some" / "file.csv")
    assert project_paths.resolve_project_relative(abs_path) == abs_path


def test_resolve_project_relative_joins_root(tmp_path, monkeypatch):
    monkeypatch.setattr(project_paths, "PROJECT_ROOT", tmp_path)
    assert project_paths.resolve_project_relative("data/file.csv") == str(tmp_path / "data" / "file.csv")


def test_resolve_cli_artifact_relative_goes_under_output(tmp_path, monkeypatch):
    monkeypatch.setattr(project_paths, "PROJECT_ROOT", tmp_path)
    result = project_paths.resolve_cli_artifact(Path("report.csv"), "exports")
    assert result == tmp_path / "output" / "exports" / "report.csv"
```

- [ ] **Step 2: Run test to verify it fails (PROJECT_ROOT points to shared/ currently)**

```bash
cd edfx && ../.venv/Scripts/pytest tests/test_project_paths.py -v 2>&1 | head -30
```

Expected: `FAILED test_project_root_resolves_to_app_folder` — `shared/` ≠ `edfx/`.

(The other tests will pass since they monkeypatch PROJECT_ROOT.)

- [ ] **Step 3: Rewrite shared/project_paths.py**

Replace the entire contents of `shared/project_paths.py` with:

```python
"""Shared path utilities — caller-aware project root for edfx/, credit-edge/, and riskcalc/.

PROJECT_ROOT resolves to the app folder (<app>/) by walking the call stack to find
the first non-internal caller. All consuming scripts live at <app>/<subfolder>/,
so caller.parent.parent == <app>/.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path


def _find_app_root() -> Path:
    for frame_info in inspect.stack():
        p = Path(frame_info.filename).resolve()
        if p.name == "project_paths.py":
            continue
        if str(p).startswith(sys.prefix):
            continue
        return p.parent.parent
    return Path.cwd()


PROJECT_ROOT = _find_app_root()


def logs_dir(*parts: str) -> Path:
    """``<app>/logs/<parts...>/`` — runtime logs."""
    d = PROJECT_ROOT / "logs"
    for p in parts:
        d = d / p
    d.mkdir(parents=True, exist_ok=True)
    return d


def output_dir(*parts: str) -> Path:
    """``<app>/output/<parts...>/`` — CSV/JSON/Excel artifacts."""
    d = PROJECT_ROOT / "output"
    for p in parts:
        d = d / p
    d.mkdir(parents=True, exist_ok=True)
    return d


def input_dir(*parts: str) -> Path:
    """``<app>/input/<parts...>/`` — input files a utility reads."""
    d = PROJECT_ROOT / "input"
    for p in parts:
        d = d / p
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_project_relative(path_str: str) -> str:
    """For .env path values: if not absolute, treat as relative to PROJECT_ROOT."""
    s = (path_str or "").strip()
    if not s:
        return s
    p = Path(s).expanduser()
    if p.is_absolute():
        return str(p)
    return str(PROJECT_ROOT / p)


def resolve_cli_artifact(path: Path, *output_subfolders: str) -> Path:
    """CLI output path: absolute unchanged; relative → output/<subfolders>/."""
    path = path.expanduser()
    if path.is_absolute():
        return path
    return output_dir(*output_subfolders) / path
```

- [ ] **Step 4: Run test again to verify it passes**

```bash
cd edfx && ../.venv/Scripts/pytest tests/test_project_paths.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add shared/project_paths.py edfx/tests/test_project_paths.py
git commit -m "feat(shared): rewrite project_paths with caller-aware PROJECT_ROOT via inspect"
```

---

## Task 8: Fix sys.path Inserts and .env Load Paths in All Scripts

**Files:**
- Modify: all 18 scripts/dashboard files that import `project_paths` — add `sys.path.insert` block
- Modify: all scripts that call `load_dotenv(Path(__file__).resolve().parent / ".env"` — fix to `.parent.parent`

**Interfaces:**
- Consumes: `shared/project_paths.py` from Task 7

**Why two changes are needed:**
1. `sys.path.insert` — Python needs to find `project_paths.py` in `shared/`; previously it was in the same directory as the scripts.
2. `.env` path — `.env` now lives at the app root (`edfx/.env`, `riskcalc/.env`), one level above the script. Scripts currently load from `Path(__file__).parent / ".env"` = `edfx/scripts/.env` (wrong). Must be `Path(__file__).parent.parent / ".env"` = `edfx/.env` (correct).

**Files requiring sys.path.insert** (all import `project_paths`):
- `edfx/scripts/` — 14 scripts: `build_opensearch_entity_query_from_csv.py`, `DynamoDB_BatchUpdate_CreatedBy.py`, `EDFX_ProcessStatus.py`, `export_stale_entities_from_excel.py`, `financials_delete_custom_entity.py`, `monitor_entity_refresh_status.py`, `portfolio_kpi_metrics_postgres.py`, `refresh_stale_non_public_entities.py`, `reprocess_stuck_financials.py`, `run_portfolio_kpis_postgres.py`, `test_single_entity_refresh.py`, `validate_pd_precheck.py`, `validate_stale_entities.py`, `validate_stale_pd_source.py`
- `edfx/dashboard/manifest.py`, `edfx/dashboard/runs.py`
- `riskcalc/scripts/LC_Process.py`
- `riskcalc/archive/LDGLoadTest.py`

**Files requiring .env path fix** (contain `load_dotenv(... / ".env")`):
Grep to find them all before editing:
```bash
grep -rn 'load_dotenv.*\.parent / ".env"' edfx/scripts/ riskcalc/scripts/
```

- [ ] **Step 1: Add sys.path.insert block to every project_paths importer**

For each of the 18 files listed above, open the file and add this block **immediately before the first line that imports `project_paths`**:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
```

Example — before (in `edfx/scripts/EDFX_ProcessStatus.py`):
```python
from project_paths import output_dir, resolve_project_relative
```
After:
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
from project_paths import output_dir, resolve_project_relative
```

Do this for all 18 files. The three-level parent (`parent.parent.parent`) works for all of them:
- `edfx/scripts/` → `.parent.parent.parent` = `MyUtilities/` + `/shared` ✓
- `edfx/dashboard/` → same pattern ✓
- `riskcalc/scripts/` → same pattern ✓
- `riskcalc/archive/` → same pattern ✓

- [ ] **Step 2: Fix .env load paths**

Run this grep to find exactly which scripts need the path fix:
```bash
grep -rln 'load_dotenv.*parent / ".env"' edfx/scripts/ riskcalc/scripts/
```

For every file returned, change:
```python
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
```
to:
```python
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
```

Note: `SecurityService.py` has `load_dotenv(Path(__file__).resolve().parent / ".env", override=False)` at module level (not inside a function). Apply the same fix: `.parent` → `.parent.parent`.

- [ ] **Step 3: Quick import sanity check**

```bash
cd edfx && ../.venv/Scripts/python -c "import sys; sys.path.insert(0, '../shared'); import project_paths; print(project_paths.PROJECT_ROOT)"
```

Expected: prints a path ending in `edfx`.

```bash
cd riskcalc && ../edfx/.venv/Scripts/python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent / 'shared'))
import scripts.LC_Process as lc
print('OK')
" 2>&1 | head -5
```

Expected: no ImportError.

- [ ] **Step 4: Commit**

```bash
git add edfx/scripts/ edfx/dashboard/ riskcalc/scripts/ riskcalc/archive/
git commit -m "fix: add sys.path.insert for shared/ and fix .env load paths after move"
```

---

## Task 9: Add conftest.py for pytest and Fix Dashboard sys.path

**Files:**
- Create: `edfx/tests/conftest.py`

**Interfaces:**
- Consumes: `edfx/scripts/` from Task 2, `shared/` from Task 6
- Produces: pytest can discover and import all EDFX scripts from `edfx/tests/`

**Why needed:** Currently tests run from `Day2Day_Utillites/` where scripts are co-located. pytest automatically adds the `tests/` parent to `sys.path`, which used to be `Day2Day_Utillites/` (where scripts lived). Now tests are in `edfx/tests/` and scripts are in `edfx/scripts/` — a different directory. Without a `conftest.py`, `import pd_precheck` fails with `ModuleNotFoundError`.

- [ ] **Step 1: Write the failing test (verify the import fails without conftest)**

```bash
cd edfx && ../.venv/Scripts/pytest tests/test_pd_precheck.py -v 2>&1 | head -15
```

Expected: `ModuleNotFoundError: No module named 'pd_precheck'`

- [ ] **Step 2: Create edfx/tests/conftest.py**

```python
import sys
from pathlib import Path

_edfx_root = Path(__file__).resolve().parent.parent   # edfx/
sys.path.insert(0, str(_edfx_root / "scripts"))
sys.path.insert(0, str(_edfx_root.parent / "shared"))
```

- [ ] **Step 3: Run full EDFX test suite to verify**

```bash
cd edfx && ../.venv/Scripts/pytest tests/ -v --tb=short 2>&1
```

Expected: all tests PASS (same count as before the migration).

If any tests fail with `ModuleNotFoundError` for a module that isn't a script (e.g., a transitive import from a script), add that module's parent directory to `sys.path` in `conftest.py`.

- [ ] **Step 4: Commit**

```bash
git add edfx/tests/conftest.py edfx/tests/test_project_paths.py
git commit -m "fix(edfx): add conftest.py so pytest finds scripts/ and shared/"
```

---

## Task 10: Create New README, .env.example, and requirements Files

**Files:**
- Create: `edfx/README.md`
- Create: `riskcalc/README.md`, `riskcalc/requirements.txt`, `riskcalc/.env.example`
- Create: `credit-edge/README.md`, `credit-edge/requirements.txt`, `credit-edge/.env.example`
- Create: `shared/README.md`

**Interfaces:**
- None — these are documentation/config files

- [ ] **Step 1: Create edfx/README.md**

```markdown
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
```

- [ ] **Step 2: Create riskcalc/README.md**

```markdown
# RiskCalc Utilities

Scripts for RiskCalc support operations — SecurityService SOAP calls and LC file processing.

## Setup

```powershell
cd riskcalc
copy .env.example .env          # fill in your credentials
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/SecurityService.py` | Authenticate via RiskCalc SOAP SecurityService and retrieve user info |
| `scripts/LC_Process.py` | Process LC batch files from a UNC file share |

## Archive

`archive/` contains older test scripts kept for reference — not actively used.

## Input / Output / Logs

Scripts read/write under `input/`, `output/`, `logs/`. These are gitignored.
```

- [ ] **Step 3: Create riskcalc/requirements.txt**

```
aiohttp>=3.8.0
nest_asyncio>=1.5.0
python-dotenv>=1.0.0
requests>=2.28.0
```

- [ ] **Step 4: Create riskcalc/.env.example**

```bash
# RiskCalc Utilities — copy to ".env" and fill in real values.
# Never commit ".env" — it is gitignored.

# --- RiskCalc SOAP — SecurityService.py (AuthenticateAndGetUserInfo)
RISKCALC_SECURITY_SOAP_URL=https://api-security.riskcalc.moodysanalytics.com/services/security/internal/Security.svc
RISKCALC_WSSE_USERNAME=
RISKCALC_WSSE_PASSWORD=
RISKCALC_SOAP_NONCE=
RISKCALC_SOAP_CREATED=
RISKCALC_AUTH_BODY_USERNAME=
RISKCALC_AUTH_BODY_PASSWORD=

# --- RiskCalc SOAP — Sample_RCTest.py (GetUserSignedLicensingDocumentXml)
RISKCALC_LICENSE_DOCUMENT_USERNAME=
# Comma-separated integers, e.g. 5
RISKCALC_LICENSE_PRODUCT_IDS=5

# --- RiskCalc REST — SampleTest.py
RISKCALC_REST_URL=https://qa-api.riskcalc.moodysanalytics.net/services/internal/RiskCalcRestService.svc
RISKCALC_REST_SESSION_COOKIE=
RISKCALC_REST_PASSWORD=

# --- LC_Process.py
# LC_BATCH_ROOT_FOLDER=\\fileserver\share\LC-BatchDataFiles
```

- [ ] **Step 5: Create credit-edge/README.md**

```markdown
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
```

- [ ] **Step 6: Create credit-edge/requirements.txt**

```
# Add Python dependencies here as Credit Edge scripts are added.
# Example:
# requests>=2.28.0
# python-dotenv>=1.0.0
```

- [ ] **Step 7: Create credit-edge/.env.example**

```bash
# Credit Edge Utilities — copy to ".env" and fill in real values.
# Never commit ".env" — it is gitignored.
#
# Add environment variables here as Credit Edge scripts are added.
# Example:
# CE_API_URL=https://api.creditedge.moodysanalytics.com
# CE_API_KEY=
```

- [ ] **Step 8: Create shared/README.md**

```markdown
# shared/

Utilities and configuration shared across the EDFX, Credit Edge, and RiskCalc app folders.

## Contents

| File | Purpose | Used by |
|------|---------|---------|
| `project_paths.py` | Caller-aware path resolver: `PROJECT_ROOT`, `logs_dir()`, `output_dir()`, `input_dir()`, `resolve_project_relative()`, `resolve_cli_artifact()` | EDFX (14 scripts + dashboard), RiskCalc (LC_Process.py) |
| `REPOS.md` | EDFX fleet repo registry — 21 repos, languages, default branches | DocuProj (bootstrap.py, flow.py), developers adding repos |

## How to use project_paths from a script

Scripts live at `<app>/<subfolder>/script.py`. Add this block before the `project_paths` import:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
from project_paths import logs_dir, output_dir  # import what you need
```

## How to add a new shared utility

1. Drop the file in `shared/`
2. Add it to the table above
3. Import it in consuming scripts using the same `sys.path.insert` pattern
```

- [ ] **Step 9: Commit all new files**

```bash
git add edfx/README.md riskcalc/README.md riskcalc/requirements.txt riskcalc/.env.example
git add credit-edge/README.md credit-edge/requirements.txt credit-edge/.env.example
git add shared/README.md
git commit -m "docs: add README, .env.example, and requirements.txt for each app + shared"
```

---

## Task 11: Write docs/architecture.md and docs/contributing.md

**Files:**
- Create: `docs/architecture.md`
- Create: `docs/contributing.md`

- [ ] **Step 1: Create docs/architecture.md**

```markdown
# Repository Architecture

`MyUtilities` is a shared support repo for EDFX, Credit Edge, and RiskCalc.
It provides operational scripts, runbooks, and analysis tools that any team member
can pick up and run.

## Folder Map

```
MyUtilities/
├── edfx/           EDFX scripts, runbooks, dashboard, tests
├── credit-edge/    Credit Edge scripts and runbooks
├── riskcalc/       RiskCalc scripts and runbooks
├── docuproj/       Cross-repo flow analyzer — standalone tool for EDFX fleet
├── shared/         Utilities shared across apps (project_paths.py, REPOS.md)
└── docs/           Repo-level docs (this file, contributing guide)
```

## Per-App Layout (consistent across all three apps)

```
<app>/
├── scripts/        Python utilities — one file per operation
├── runbooks/       Markdown step-by-step ops guides
├── sql/            SQL queries used by scripts or runbooks
├── tests/          pytest test files
├── archive/        Retired scripts — kept for reference, not actively run
├── docs/           Supporting docs, reports, slide decks
├── input/          Script input files (gitignored — create locally)
├── output/         Script output files (gitignored — create locally)
├── logs/           Run logs (gitignored — create locally)
├── .env.example    All env vars the app needs — copy to .env and fill in
├── requirements.txt Python dependencies for this app only
└── README.md       Setup + script catalog for this app
```

## Design Principles

- **App-first navigation** — start in your app folder; everything you need is there
- **Consistent anatomy** — same structure in every app; knowledge transfers instantly
- **Self-contained apps** — separate .env, requirements.txt, and venv per app; no shared secrets
- **One shared layer** — code used by 2+ apps lives in `shared/`, nowhere else
- **Runbooks alongside scripts** — operational procedures live next to the code they document

## DocuProj

`docuproj/` is a standalone project — a static analyzer that traces request flows
across the EDFX fleet of repos (endpoint → service → database). It is not part of
any single app. It reads `shared/REPOS.md` for the list of repos to analyze.
See `docuproj/README.md` for setup and usage.

## Claude Code Skills

Five Claude Code skills in `.claude/skills/` provide guided workflows for common
EDFX operations. They stay at the repo root so Claude Code discovers them regardless
of which app subfolder you are in. New skills for Credit Edge or RiskCalc follow the
same pattern, prefixed `credit-edge-*` or `riskcalc-*`.
```

- [ ] **Step 2: Create docs/contributing.md**

```markdown
# Contributing to MyUtilities

How to add new scripts, runbooks, SQL, or shared utilities to this repo.

## Adding a New Script

1. Drop the `.py` file in `<app>/scripts/` (e.g., `edfx/scripts/my_new_script.py`)

2. If the script uses `project_paths` (for input/output/logs paths), add this block
   at the top, before the `project_paths` import:
   ```python
   import sys
   from pathlib import Path
   sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
   ```

3. If the script reads a `.env` file, use:
   ```python
   load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
   ```
   (`.parent.parent` because `.env` is at the app root, one level above `scripts/`)

4. Add any new environment variables to `<app>/.env.example` with a description comment.

5. Add any new Python dependencies to `<app>/requirements.txt`.

6. Add an entry to `<app>/utilities.yaml` (EDFX only) — this feeds the dashboard and
   Claude Code skills:
   ```yaml
   - name: my_new_script
     description: "One-line description"
     script: scripts/my_new_script.py
     env_vars: [VAR_ONE, VAR_TWO]
   ```

7. Write a runbook in `<app>/runbooks/` if this is an operational procedure
   someone will follow step-by-step.

8. Add tests in `<app>/tests/test_my_new_script.py`.

## Adding a Runbook Only (No Script)

1. Drop the `.md` file in `<app>/runbooks/`

2. Follow this structure:
   ```markdown
   # Runbook: <Title>

   **App:** EDFX | Credit Edge | RiskCalc
   **Env vars required:** LIST_THEM_HERE

   ## Prerequisites
   - ...

   ## Steps
   1. ...
   2. ...

   ## Troubleshooting
   ...
   ```

## Adding a SQL File

1. Drop the `.sql` file in `<app>/sql/`
2. Reference it from the relevant runbook with a relative path

## Adding a Shared Utility

1. Only add to `shared/` if the utility is used by **two or more apps**
2. Drop the file in `shared/`
3. Update `shared/README.md` with the new file's purpose and consumers
4. In each consuming script, add the `sys.path.insert` block (see above)

## Archiving an Old Script

1. `git mv <app>/scripts/old_script.py <app>/archive/`
2. Add a one-line comment at the top of the file explaining why it was archived

## Branch and PR Conventions

- Branch name: `<app>/<short-description>` (e.g., `edfx/add-entity-audit-script`)
- PR title: `feat(<app>): <description>` or `fix(<app>): <description>`
- One PR per logical change — don't bundle unrelated scripts
```

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md docs/contributing.md
git commit -m "docs: add architecture.md and contributing.md to docs/"
```

---

## Task 12: Clean Up Empty Old Folders and Final Verification

**Files:**
- Delete: `Day2Day_Utillites/` (should be empty after all moves)
- Delete: `docs/runbooks/` (should be empty after CE runbook moved)
- Remove: `.gitkeep` placeholders now covered by real files

- [ ] **Step 1: Verify Day2Day_Utillites is empty (or nearly so)**

```bash
find Day2Day_Utillites -not -path '*/.venv/*' -not -path '*/__pycache__/*' -not -path '*/.pytest_cache/*' -type f
```

Expected: empty (all tracked files have been git mv'd). If any tracked files appear, investigate — they may have been missed in earlier tasks.

- [ ] **Step 2: Remove Day2Day_Utillites**

The `.venv/`, `__pycache__/`, `.pytest_cache/` are untracked and gitignored — safe to delete with the folder:

```bash
git rm -r Day2Day_Utillites/Docs/superpowers   # if still present (not migrated)
rm -rf Day2Day_Utillites   # removes gitignored runtime dirs (venv, pycache)
git add -A
```

- [ ] **Step 3: Remove old docs/runbooks folder**

```bash
# Should already be empty after Task 5; remove if git still tracks the directory
git rm -r --ignore-unmatch docs/runbooks/
```

- [ ] **Step 4: Remove .gitkeep placeholders where real files now exist**

```bash
# Remove .gitkeep from dirs that now have real content
find edfx credit-edge riskcalc shared -name ".gitkeep" | while read f; do
  dir=$(dirname "$f")
  count=$(ls "$dir" | grep -v ".gitkeep" | wc -l)
  if [ "$count" -gt "0" ]; then
    git rm "$f"
  fi
done
```

- [ ] **Step 5: Run full EDFX test suite one final time**

```bash
cd edfx && ../.venv/Scripts/pytest tests/ -v
```

Expected: all tests pass. Zero failures.

- [ ] **Step 6: Verify final repo structure matches spec**

```bash
find . -maxdepth 2 -not -path './.git/*' -not -path './.claude/worktrees/*' -not -path './*/\.venv/*' -not -path './.superpowers/*' -type d | sort
```

Expected top-level directories: `edfx/`, `credit-edge/`, `riskcalc/`, `docuproj/`, `shared/`, `docs/`, `.claude/`, `.git/`

- [ ] **Step 7: Verify no orphaned imports**

```bash
grep -rn "from project_paths import\|import project_paths" edfx/ riskcalc/ --include="*.py" | grep -v "sys.path.insert" | head -5
```

Every result should have a matching `sys.path.insert` 1-3 lines above it. If any don't, add the block.

- [ ] **Step 8: Final commit and tag**

```bash
git add -A
git commit -m "chore: remove Day2Day_Utillites and old docs/runbooks after full migration"
```

---

## Post-Migration Checklist

- [ ] Open `edfx/` as workspace root in VS Code/Cursor and verify F5 debug launch works on one script
- [ ] Run `python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021` from `edfx/` and verify the dashboard loads
- [ ] Share repo link with team and verify they can clone, set up one app, and run a script end-to-end
- [ ] Update any internal wiki/Confluence pages that reference the old `Day2Day_Utillites/` paths
