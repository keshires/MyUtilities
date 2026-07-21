# Standardize input/output/logs into per-utility folders — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every in-scope Day2Day utility a per-utility folder under `input/`, `output/`, and `logs/`, migrate existing artifacts into that shape, and sync the catalog/skills/docs.

**Architecture:** Extend `project_paths` with `input_dir(*parts)` and a backward-compatible `logs_dir(*parts)`; update each script's path call sites to pass its per-utility folder name; add run logs to the two destructive tools; update `utilities.yaml` globs + skills + docs + `.gitignore`; migrate existing files.

**Tech Stack:** Python 3.12, `project_paths` helper, PowerShell (Windows). No test framework (verification is `python -c` / `--help` / `grep` / `ls`).

## Global Constraints

- Per-utility folder names are EXACTLY (script → folder):
  `refresh_stale_non_public_entities.py`→`refresh_stale_entities`;
  `validate_stale_entities.py`→`validate_stale_entities`;
  `export_stale_entities_from_excel.py`→`export_stale_entities`;
  `test_single_entity_refresh.py`→`verify_single_entity_refresh`;
  `reprocess_stuck_financials.py`→`reprocess_stuck_financials`;
  `validate_stale_pd_source.py`→`validate_stale_pd_source`;
  `run_portfolio_kpis_postgres.py`→`run_portfolio_kpis`;
  `portfolio_kpi_metrics_postgres.py`→`portfolio_kpi_metrics`;
  `EDFX_ProcessStatus.py`→`edfx_process_status`;
  `build_opensearch_entity_query_from_csv.py`→`build_opensearch_query`;
  `financials_delete_custom_entity.py`→`delete_custom_entity`;
  `DynamoDB_BatchUpdate_CreatedBy.py`→`dynamodb_batch_update`.
- `logs_dir(*parts)` MUST stay backward compatible: `logs_dir()` with no args returns flat `<repo>/logs`.
- Scope is ONLY those 12 scripts + `project_paths.py` + `utilities.yaml` + the 4 `.claude/skills/*/SKILL.md` + `README.md` + `Day2Day_Utillites/Docs/utilities-catalog.md` + `Day2Day_Utillites/.gitignore` + the migration. Do NOT touch archived scripts.
- **Concurrent-edit hazard:** `refresh_stale_non_public_entities.py`, `reprocess_stuck_financials.py`, `validate_stale_pd_source.py` carry the user's uncommitted working-tree edits. Edit them by matching the exact code string (NOT by line number, which may have shifted). Stage ONLY the specific file(s) each task changes — never `git add -A`/`.`.
- Work from `Day2Day_Utillites/`; venv python is `.\.venv\Scripts\python`. Branch: `Day2Day_StaleEntitiesRefresh` (do not switch).
- Env overrides `EDFX_OUTPUT_FOLDER` and `KPI_LOG_FILE` still take precedence over defaults — do not remove them.

---

### Task 1: `project_paths.py` — `input_dir` + variadic `logs_dir`

**Files:**
- Modify: `Day2Day_Utillites/project_paths.py`

**Interfaces:**
- Produces: `input_dir(*parts: str) -> Path` (→ `<repo>/input/<parts>/`, created); `logs_dir(*parts: str) -> Path` (→ `<repo>/logs/<parts>/`, created; no args → flat `<repo>/logs`). `output_dir` unchanged. These are consumed by every later task.

- [ ] **Step 1: Replace `logs_dir` with a variadic version**

Find:
```python
def logs_dir() -> Path:
    """``<repo>/logs`` — runtime logs only."""
    d = PROJECT_ROOT / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d
```
Replace with:
```python
def logs_dir(*parts: str) -> Path:
    """``<repo>/logs/<parts...>/`` — runtime logs. No args → flat ``<repo>/logs``."""
    d = PROJECT_ROOT / "logs"
    for p in parts:
        d = d / p
    d.mkdir(parents=True, exist_ok=True)
    return d
```

- [ ] **Step 2: Add `input_dir` immediately after `output_dir`**

After the `output_dir` function, add:
```python
def input_dir(*parts: str) -> Path:
    """``<repo>/input/<parts...>/`` — input files a utility reads."""
    d = PROJECT_ROOT / "input"
    for p in parts:
        d = d / p
    d.mkdir(parents=True, exist_ok=True)
    return d
```

- [ ] **Step 3: Update the module docstring**

Replace the module docstring's first line:
```
"""Day2Day Utilities — central layout: logs under ``logs/``, generated files under ``output/<category>/``.
```
with:
```
"""Day2Day Utilities — central layout: per-utility folders under ``input/<utility>/``, ``output/<utility>/``, and ``logs/<utility>/``.
```

- [ ] **Step 4: Verify the helpers**

Run from `Day2Day_Utillites/`:
```powershell
.\.venv\Scripts\python -c "import project_paths as p; from pathlib import Path
assert p.logs_dir('x').as_posix().endswith('logs/x'); assert p.output_dir('x').as_posix().endswith('output/x'); assert p.input_dir('x').as_posix().endswith('input/x'); assert p.logs_dir().as_posix().endswith('/logs'); print('project_paths OK')"
```
Expected: `project_paths OK`.

- [ ] **Step 5: Commit**

```powershell
git add Day2Day_Utillites/project_paths.py
git commit -m "feat(paths): add input_dir + variadic logs_dir (backward compatible)"
```

---

### Task 2: Stale-family scripts — per-utility output/logs/input

**Files (edit each by matching the exact string shown; 3 are concurrently edited — see Global Constraints):**
- Modify: `Day2Day_Utillites/refresh_stale_non_public_entities.py`
- Modify: `Day2Day_Utillites/validate_stale_entities.py`
- Modify: `Day2Day_Utillites/export_stale_entities_from_excel.py`
- Modify: `Day2Day_Utillites/test_single_entity_refresh.py`
- Modify: `Day2Day_Utillites/reprocess_stuck_financials.py`
- Modify: `Day2Day_Utillites/validate_stale_pd_source.py`

**Interfaces:**
- Consumes: `logs_dir`, `output_dir`, `input_dir` from Task 1.

- [ ] **Step 1: `refresh_stale_non_public_entities.py` — log folder**

Change the log dir call (near the run-log construction):
```python
        logs_dir()
```
→
```python
        logs_dir("refresh_stale_entities")
```
(There is exactly one `logs_dir()` call. The `.summary.json` sidecar derives from the log path, so it follows automatically.)

- [ ] **Step 2: `validate_stale_entities.py` — log + output folders**

- `logs_dir()` → `logs_dir("validate_stale_entities")`
- `output_dir("stale_entities")` → `output_dir("validate_stale_entities")`
- `resolve_cli_artifact(args.output, "stale_entities")` → `resolve_cli_artifact(args.output, "validate_stale_entities")`

- [ ] **Step 3: `export_stale_entities_from_excel.py` — output + input default**

- Add `input_dir` to the import: `from project_paths import output_dir, resolve_cli_artifact` → `from project_paths import input_dir, output_dir, resolve_cli_artifact`
- `output_dir("stale_entities")` → `output_dir("export_stale_entities")`
- `resolve_cli_artifact(args.output, "stale_entities")` → `resolve_cli_artifact(args.output, "export_stale_entities")`
- Change the `--input` default. Find:
```python
        default=root
        / "inputfiles"
        / "StaleEntityRefresh"
        / "Entit_Refresh_Queue_Data_May8th.xlsx",
```
Replace with:
```python
        default=input_dir("export_stale_entities")
        / "Entit_Refresh_Queue_Data_May8th.xlsx",
```
(`root` may now be unused; if a linter flags it, leave it — other code may use it. Do not remove unrelated lines.)

- [ ] **Step 4: `test_single_entity_refresh.py` — log folder + move JSON to output**

- Add an import near the top (after `import refresh_stale_non_public_entities as rf`):
```python
from project_paths import output_dir
```
- Change the log path:
```python
    log_path = rf.logs_dir() / f"test_single_entity_refresh_{run_started.strftime('%Y%m%d_%H%M%S')}.log"
```
→
```python
    log_path = rf.logs_dir("verify_single_entity_refresh") / f"test_single_entity_refresh_{run_started.strftime('%Y%m%d_%H%M%S')}.log"
```
- Move the snapshot/result JSON from the log dir to `output/verify_single_entity_refresh/`. Find:
```python
    snap_path = log_path.with_suffix(".snapshot.json")
```
→
```python
    snap_path = output_dir("verify_single_entity_refresh") / (log_path.stem + ".snapshot.json")
```
and find:
```python
    result_path = log_path.with_suffix(".result.json")
```
→
```python
    result_path = output_dir("verify_single_entity_refresh") / (log_path.stem + ".result.json")
```

- [ ] **Step 5: `reprocess_stuck_financials.py` — log + output folders**

- `rf.logs_dir()` (log path, ~line 292) → `rf.logs_dir("reprocess_stuck_financials")`
- `output_dir("stale_entities")` → `output_dir("reprocess_stuck_financials")`
- `resolve_cli_artifact(args.output, "stale_entities")` → `resolve_cli_artifact(args.output, "reprocess_stuck_financials")`
- checkpoint path: `rf.logs_dir() / f"reprocess_stuck_financials_{mode.name}_checkpoint.txt"` → `rf.logs_dir("reprocess_stuck_financials") / f"reprocess_stuck_financials_{mode.name}_checkpoint.txt"`

- [ ] **Step 6: `validate_stale_pd_source.py` — log + output folders**

- `rf.logs_dir()` (log path) → `rf.logs_dir("validate_stale_pd_source")`
- `output_dir("stale_entities")` → `output_dir("validate_stale_pd_source")`
- `resolve_cli_artifact(args.output, "stale_entities")` → `resolve_cli_artifact(args.output, "validate_stale_pd_source")`

- [ ] **Step 7: Verify all six import and expose the new folders**

Run from `Day2Day_Utillites/`:
```powershell
.\.venv\Scripts\python -c "import refresh_stale_non_public_entities, validate_stale_entities, export_stale_entities_from_excel, test_single_entity_refresh, reprocess_stuck_financials, validate_stale_pd_source; print('stale imports OK')"
```
Expected: `stale imports OK` (no ImportError; import runs parse-level code only).
Then confirm the new folder strings are present and the old shared category is gone from these files:
```powershell
Select-String -Path validate_stale_entities.py,export_stale_entities_from_excel.py,reprocess_stuck_financials.py,validate_stale_pd_source.py -Pattern 'output_dir\("stale_entities"\)'
```
Expected: no matches (all replaced).

- [ ] **Step 8: Commit (stage only these six files)**

```powershell
git add Day2Day_Utillites/refresh_stale_non_public_entities.py Day2Day_Utillites/validate_stale_entities.py Day2Day_Utillites/export_stale_entities_from_excel.py Day2Day_Utillites/test_single_entity_refresh.py Day2Day_Utillites/reprocess_stuck_financials.py Day2Day_Utillites/validate_stale_pd_source.py
git commit -m "refactor(stale): per-utility input/output/logs folders"
```

---

### Task 3: Portfolio / EDFX / OpenSearch scripts

**Files:**
- Modify: `Day2Day_Utillites/run_portfolio_kpis_postgres.py`
- Modify: `Day2Day_Utillites/build_opensearch_entity_query_from_csv.py`
- Verify only (no change): `Day2Day_Utillites/portfolio_kpi_metrics_postgres.py`, `Day2Day_Utillites/EDFX_ProcessStatus.py`

**Interfaces:**
- Consumes: `logs_dir`, `resolve_cli_artifact`, `input_dir` from Task 1.

- [ ] **Step 1: `run_portfolio_kpis_postgres.py` — log + output folders**

- log path: `logs_dir()` (in `default_kpi_log_path`) → `logs_dir("run_portfolio_kpis")`
- `resolve_cli_artifact(export_path, "portfolio")` → `resolve_cli_artifact(export_path, "run_portfolio_kpis")`

- [ ] **Step 2: `build_opensearch_entity_query_from_csv.py` — output folder + input default**

- Add `input_dir` to the import: `from project_paths import resolve_cli_artifact` → `from project_paths import input_dir, resolve_cli_artifact`
- All three `resolve_cli_artifact(..., "opensearch_queries")` → `resolve_cli_artifact(..., "build_opensearch_query")` (3 occurrences: `--output-dir`, `--out`, `--queries-out`).
- Change the default CSV dir. Find:
```python
DEFAULT_BULK_DIR = Path(__file__).resolve().parent / "BulkUplaodFiles"
```
Replace with:
```python
DEFAULT_BULK_DIR = input_dir("build_opensearch_query")
```
(Confirm `input_dir` is imported before this module-level assignment runs — the import line is near the top, so it is. If `DEFAULT_BULK_DIR` is defined above the import, move the assignment below the imports.)

- [ ] **Step 3: Verify the two matching scripts need no change**

`portfolio_kpi_metrics_postgres.py` already uses `resolve_cli_artifact(export_path, "portfolio_kpi_metrics")` and `EDFX_ProcessStatus.py` already uses `output_dir("edfx_process_status")` — both equal their per-utility folder names, so they are already conformant. Confirm no `stale_entities`/`portfolio`/`opensearch_queries` string remains that should have changed:
```powershell
Select-String -Path portfolio_kpi_metrics_postgres.py,EDFX_ProcessStatus.py -Pattern 'output_dir\(|resolve_cli_artifact\('
```
Expected: only `portfolio_kpi_metrics` and `edfx_process_status` appear as the subfolder args (no change required).

- [ ] **Step 4: Verify imports + new folder strings**

```powershell
.\.venv\Scripts\python -c "import run_portfolio_kpis_postgres, build_opensearch_entity_query_from_csv, portfolio_kpi_metrics_postgres, EDFX_ProcessStatus; print('pkg imports OK')"
Select-String -Path build_opensearch_entity_query_from_csv.py -Pattern 'opensearch_queries'
```
Expected: `pkg imports OK`; the `Select-String` returns no matches (all replaced with `build_opensearch_query`).

- [ ] **Step 5: Commit**

```powershell
git add Day2Day_Utillites/run_portfolio_kpis_postgres.py Day2Day_Utillites/build_opensearch_entity_query_from_csv.py
git commit -m "refactor(portfolio,opensearch): per-utility output/logs/input folders"
```

---

### Task 4: Add run logs to the two destructive tools

**Files:**
- Modify: `Day2Day_Utillites/financials_delete_custom_entity.py`
- Modify: `Day2Day_Utillites/DynamoDB_BatchUpdate_CreatedBy.py`

**Interfaces:**
- Consumes: `logs_dir` from Task 1.

- [ ] **Step 1: `financials_delete_custom_entity.py` — add a run log**

- Add imports near the existing imports (top of file):
```python
import logging
from datetime import datetime, timezone
from project_paths import logs_dir
```
- At the very start of `main()` (after args are parsed, before the first delete), add:
```python
    _ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _log_path = logs_dir("delete_custom_entity") / f"delete_custom_entity_{_ts}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(_log_path, encoding="utf-8"), logging.StreamHandler()],
    )
    logging.info("delete_custom_entity run start; entity ids=%s", entity_ids)
```
(Use the variable that already holds the resolved list of entity ids in `main`; if it is named differently, log that variable. Log the HTTP status/result for each deletion by adding `logging.info("deleted %s -> %s", eid, resp.status_code)` alongside the existing per-entity print, without removing the print.)

- [ ] **Step 2: `DynamoDB_BatchUpdate_CreatedBy.py` — add a run log**

- Add imports near the top:
```python
import logging
from datetime import datetime, timezone
from project_paths import logs_dir
```
(This file has no `pathlib` import; `logs_dir` returns a `Path` that `FileHandler` accepts directly.)
- Near the start of execution (after the config constants are read / at the top of the main routine, before the scan), add:
```python
    _ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _log_path = logs_dir("dynamodb_batch_update") / f"dynamodb_batch_update_{_ts}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(_log_path, encoding="utf-8"), logging.StreamHandler()],
    )
    logging.info("dynamodb_batch_update start; DRY_RUN=%s table=%s find=%r set=%r",
                 DRY_RUN, TABLE_NAME, CURRENT_VALUE_TO_FIND, NEW_VALUE_TO_SET)
```
(Use the actual constant names present in the file for table/find/set — confirm them by reading the config block; if a name differs, substitute the real one. Also log the final summary counts with `logging.info(...)` where the script prints its SUMMARY.)

- [ ] **Step 3: Verify both import and create their log folder**

```powershell
.\.venv\Scripts\python -c "import financials_delete_custom_entity, DynamoDB_BatchUpdate_CreatedBy; import project_paths; print('destructive imports OK')"
```
Expected: `destructive imports OK` (import must not trigger a delete/scan — those live under `main`/`__main__`). If importing `DynamoDB_BatchUpdate_CreatedBy` executes side effects at module top level, wrap the new logging setup and the execution body under `if __name__ == "__main__":` / the existing main guard so import stays clean; note this in the report.

- [ ] **Step 4: Commit**

```powershell
git add Day2Day_Utillites/financials_delete_custom_entity.py Day2Day_Utillites/DynamoDB_BatchUpdate_CreatedBy.py
git commit -m "feat(audit): run logs for delete_custom_entity + dynamodb_batch_update"
```

---

### Task 5: Sync manifest, skills, docs, `.gitignore`

**Files:**
- Modify: `Day2Day_Utillites/utilities.yaml`
- Modify: `.claude/skills/stale-entity-refresh/SKILL.md`, `.claude/skills/portfolio-kpi-ops/SKILL.md`, `.claude/skills/edfx-entity-ops/SKILL.md`, `.claude/skills/dynamo-batch-update/SKILL.md`
- Modify: `README.md`, `Day2Day_Utillites/Docs/utilities-catalog.md`
- Modify: `Day2Day_Utillites/.gitignore`

**Interfaces:**
- Consumes: the per-utility folder names (Global Constraints). `runs.py`/`serve.py` are NOT changed — they glob relative to the `logs/`/`output/` roots.

- [ ] **Step 1: Update `utilities.yaml` output/log globs to per-utility folders**

For each utility, set `outputs.logs_glob` / `outputs.output_glob` to include its folder. Apply these exact values:
- `refresh-stale-non-public-entities`: `logs_glob: "refresh_stale_entities/refresh_stale_entities_*"`
- `validate-stale-entities`: `logs_glob: "validate_stale_entities/validate_stale_entities_*"`, `output_glob: "validate_stale_entities/stale_reconcile_*"`
- `export-stale-entities-from-excel`: `output_glob: "export_stale_entities/stale_external_ids_*"`
- `test-single-entity-refresh`: `logs_glob: "verify_single_entity_refresh/test_single_entity_refresh_*"`, `output_glob: "verify_single_entity_refresh/*"`
- `run-portfolio-kpis-postgres`: `logs_glob: "run_portfolio_kpis/run_portfolio_kpis_postgres_*"`, `output_glob: "run_portfolio_kpis/*"`
- `portfolio-kpi-metrics-postgres`: `output_glob: "portfolio_kpi_metrics/*"` (unchanged)
- `edfx-process-status`: `output_glob: "edfx_process_status/*"` (unchanged)
- `build-opensearch-entity-query-from-csv`: `output_glob: "build_opensearch_query/*"`
- `financials-delete-custom-entity`: add `outputs:` with `logs_glob: "delete_custom_entity/delete_custom_entity_*"`
- `dynamodb-batch-update-createdby`: add `outputs:` with `logs_glob: "dynamodb_batch_update/dynamodb_batch_update_*"`

- [ ] **Step 2: Verify the manifest still parses**

```powershell
.\.venv\Scripts\python -c "from dashboard.manifest import load_manifest; m=load_manifest(); print(len(m.utilities),'utilities'); print([u.id for u in m.utilities if u.outputs.logs_glob and 'delete' in u.id or 'dynamo' in u.id])"
```
Expected: `10 utilities` and the two destructive ids listed (they now have logs_glob).

- [ ] **Step 3: Update the 4 skills' output-path references**

In each `SKILL.md`, update the "where outputs land" / output-path lines to the per-utility folders:
- `stale-entity-refresh`: `output/stale_entities/...` → the per-utility folders (`output/export_stale_entities/`, `output/validate_stale_entities/`, `output/verify_single_entity_refresh/`); logs → `logs/refresh_stale_entities/`, `logs/validate_stale_entities/`, `logs/verify_single_entity_refresh/`.
- `portfolio-kpi-ops`: `output/portfolio/` → `output/run_portfolio_kpis/`; `logs/run_portfolio_kpis_postgres_*` → `logs/run_portfolio_kpis/`; `output/portfolio_kpi_metrics/` stays.
- `edfx-entity-ops`: `output/opensearch_queries/` → `output/build_opensearch_query/`; `output/edfx_process_status/` stays; add that `delete_custom_entity` now logs to `logs/delete_custom_entity/`.
- `dynamo-batch-update`: add that runs now log to `logs/dynamodb_batch_update/`.

- [ ] **Step 4: Add the convention note to README + catalog doc**

In `Day2Day_Utillites/Docs/utilities-catalog.md`, add a short section:
```markdown
## File layout convention

Each utility reads and writes under its own per-utility folder:

- Inputs:  `input/<utility>/`
- Outputs: `output/<utility>/`
- Logs / run history: `logs/<utility>/`

The folder name matches the utility (e.g. `refresh_stale_entities`,
`run_portfolio_kpis`, `build_opensearch_query`). See `utilities.yaml` for each
utility's exact globs.
```
In `README.md`, add one line under the Day2Day "Utilities catalog & dashboard" section:
```markdown
Each utility reads/writes under per-utility folders: `input/<utility>/`, `output/<utility>/`, `logs/<utility>/`.
```

- [ ] **Step 5: Update `.gitignore`**

In `Day2Day_Utillites/.gitignore`, add `input/` near the `output/` ignore. Find:
```
# Generated CSV / JSON / Excel exports (see project_paths.py)
output/
```
Add after it:
```

# Local input files a utility reads (per-utility folders)
input/
```
Keep all existing ignores.

- [ ] **Step 6: Commit**

```powershell
git add Day2Day_Utillites/utilities.yaml .claude/skills/stale-entity-refresh/SKILL.md .claude/skills/portfolio-kpi-ops/SKILL.md .claude/skills/edfx-entity-ops/SKILL.md .claude/skills/dynamo-batch-update/SKILL.md README.md Day2Day_Utillites/Docs/utilities-catalog.md Day2Day_Utillites/.gitignore
git commit -m "docs(catalog): per-utility folders in manifest globs, skills, docs, gitignore"
```

---

### Task 6: Migrate existing artifacts

**Files:** filesystem moves only (`git mv` for tracked; plain move for gitignored).

**Interfaces:** none (data migration).

- [ ] **Step 1: Move the tracked OpenSearch input files (`git mv`)**

```powershell
New-Item -ItemType Directory -Force Day2Day_Utillites/input/build_opensearch_query | Out-Null
git mv "Day2Day_Utillites/BulkUplaodFiles/Corporate_Input_File 1.csv"  "Day2Day_Utillites/input/build_opensearch_query/"
git mv "Day2Day_Utillites/BulkUplaodFiles/Corporate_Input_File 1.xlsx" "Day2Day_Utillites/input/build_opensearch_query/"
```
Verify: `git status --short` shows exactly these two as renames.

- [ ] **Step 2: Reorganize existing gitignored logs into per-utility folders**

Run this from `Day2Day_Utillites/` (Bash tool). It moves only recognized utility log/summary files by prefix; unknown files stay put:
```bash
cd "$(git rev-parse --show-toplevel)/Day2Day_Utillites"
declare -A MAP=(
  [refresh_stale_entities_]=refresh_stale_entities
  [validate_stale_entities_]=validate_stale_entities
  [stale_external_ids_]=export_stale_entities
  [test_single_entity_refresh_]=verify_single_entity_refresh
  [reprocess_stuck_financials_]=reprocess_stuck_financials
  [validate_stale_pd_source_]=validate_stale_pd_source
  [run_portfolio_kpis_postgres_]=run_portfolio_kpis
)
for f in logs/*; do
  [ -f "$f" ] || continue
  b=$(basename "$f")
  for pref in "${!MAP[@]}"; do
    case "$b" in "$pref"*) mkdir -p "logs/${MAP[$pref]}"; git mv --force "$f" "logs/${MAP[$pref]}/$b" 2>/dev/null || mv "$f" "logs/${MAP[$pref]}/$b"; break;; esac
  done
done
echo "logs/ top-level remaining:"; ls -1 logs | head
```
Note: the stray files `db_behind_api_42.txt`, `db_behind_api_ids.txt`, `live_custom_run.out` match no prefix and remain in `logs/` root — intended (left untouched per the spec).

- [ ] **Step 3: Reorganize existing gitignored outputs into per-utility folders**

```bash
cd "$(git rev-parse --show-toplevel)/Day2Day_Utillites"
if [ -d output/stale_entities ]; then
  for f in output/stale_entities/*; do
    [ -f "$f" ] || continue
    b=$(basename "$f")
    case "$b" in
      stale_reconcile_*)   dst=validate_stale_entities ;;
      stale_external_ids_*) dst=export_stale_entities ;;
      *.snapshot.json|*.result.json) dst=verify_single_entity_refresh ;;
      stuck_financials_*)  dst=reprocess_stuck_financials ;;
      stale_pd_source_*)   dst=validate_stale_pd_source ;;
      *) dst="" ;;
    esac
    if [ -n "$dst" ]; then mkdir -p "output/$dst"; mv "$f" "output/$dst/$b"; fi
  done
  rmdir output/stale_entities 2>/dev/null || true
fi
echo "output/ subfolders:"; ls -1 output
```

- [ ] **Step 4: Remove the now-empty legacy input dirs**

```bash
cd "$(git rev-parse --show-toplevel)/Day2Day_Utillites"
# Only remove if empty (both were reported empty). rmdir fails (harmlessly) if not.
rmdir inputfiles 2>/dev/null && echo "removed inputfiles/" || echo "inputfiles/ not empty or gone — left as-is"
rmdir outputfiles 2>/dev/null && echo "removed outputfiles/" || echo "outputfiles/ not empty or gone — left as-is"
# BulkUplaodFiles/ still holds gitignored corporate_input_run_output/ — leave it.
```

- [ ] **Step 5: Verify the migration + dashboard still finds relocated files**

```powershell
.\.venv\Scripts\python -c "from dashboard.manifest import load_manifest; from dashboard.runs import list_runs; m=load_manifest(); u=[x for x in m.utilities if x.id=='refresh-stale-non-public-entities'][0]; r=list_runs(u); print('refresh runs found:', len(r)); print(r[0]['name'] if r else '(none)')"
```
Expected: a non-zero count and a name like `refresh_stale_entities/refresh_stale_entities_*.log` (the relocated historical logs are now under the per-utility glob). If 0, that's acceptable only if `logs/` had no `refresh_stale_entities_*` files; report what you saw.
Also confirm the tracked input move:
```powershell
git status --short Day2Day_Utillites/input Day2Day_Utillites/BulkUplaodFiles
```
Expected: the two `Corporate_Input_File 1.*` shown as renames into `input/build_opensearch_query/`.

- [ ] **Step 6: Commit the tracked move (gitignored moves need no commit)**

```powershell
git add Day2Day_Utillites/input Day2Day_Utillites/BulkUplaodFiles
git commit -m "chore(migrate): move opensearch input files into input/build_opensearch_query"
```
(The `logs/` and `output/` reorganizations are gitignored — nothing to commit for them.)

---

## Self-Review

**Spec coverage:**
- `project_paths` `input_dir` + variadic `logs_dir` + docstring → Task 1. ✓
- Per-utility folder mapping applied to all 12 scripts → Tasks 2 (6 stale), 3 (portfolio/edfx/opensearch, incl. the 2 already-conformant), 4 (2 destructive). ✓
- `test_single_entity_refresh` JSON moved logs→output → Task 2 Step 4. ✓
- Input defaults → `input/<utility>/` (export, opensearch) → Task 2 Step 3, Task 3 Step 2. ✓
- Add run logs to the 2 destructive tools → Task 4. ✓
- Manifest globs + skills + README + catalog doc + `.gitignore` → Task 5. ✓
- Migration: tracked `git mv` of BulkUplaod inputs; local reorg of logs/output; remove empty dirs; leave stray files → Task 6. ✓
- Concurrent-edit caution (edit by string, stage per-file) → Global Constraints + Task 2. ✓
- Env overrides preserved (`EDFX_OUTPUT_FOLDER`, `KPI_LOG_FILE`) → Global Constraints; Tasks 1/3 don't remove them. ✓

**Placeholder scan:** No TBD/TODO. Each edit shows the exact old→new string. Two steps ask the implementer to confirm a real constant/variable name in the file before logging it (Task 4) — that is a concrete verification action, not a deferred decision.

**Type/name consistency:** Folder names match the Global Constraints table verbatim across scripts (Tasks 2–4), manifest globs (Task 5 Step 1), skills (Task 5 Step 3), and migration destinations (Task 6). `logs_dir`/`input_dir`/`output_dir` signatures from Task 1 match every call site. `portfolio_kpi_metrics` and `edfx_process_status` correctly noted as no-change (names already equal).