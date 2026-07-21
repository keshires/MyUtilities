# Day2Day Utilities — Skills + Catalog Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the production tools in `Day2Day_Utillites/` discoverable via 4 Claude Code skills and a read-only FastAPI catalog dashboard, both driven by one hand-authored manifest.

**Architecture:** A hand-authored `utilities.yaml` is the single source of truth. A small FastAPI app (`dashboard/`) reads it and scans `logs/` + `output/` for run history, serving a static SPA at `/app/`. Four `SKILL.md` runbooks under `.claude/skills/` cite the manifest. Seven throwaway POC scripts move to `archive/`.

**Tech Stack:** Python 3.12, FastAPI + uvicorn (already used by DocuProj), pydantic v2, PyYAML, vanilla-JS static page (no build step). Runs in `Day2Day_Utillites/.venv`.

## Global Constraints

- All new dashboard code lives under `Day2Day_Utillites/dashboard/`; run commands execute from `Day2Day_Utillites/` so `import project_paths` resolves.
- Use the existing `project_paths` module for `logs/` and `output/` locations — never hardcode paths.
- The manifest is hand-authored YAML. Do **not** import or introspect the utility scripts at dashboard runtime (importing them triggers DB/network side effects).
- Dashboard is **read-only**: no route executes a utility. No "Run" button.
- No test framework is introduced (repo has none). Verification is manual: `python -c` smoke checks and live HTTP checks via uvicorn + curl.
- Skill files follow the existing `.claude/skills/troubleshooting-edfx-flows/SKILL.md` pattern: YAML frontmatter with `name` + a `description` beginning "Use when …".
- Dashboard port: **8021** (DocuProj uses 8011; avoid collision).
- Windows shell is PowerShell; commands below use forms that work in PowerShell. The venv Python is `.\.venv\Scripts\python`.

---

### Task 1: Archive the POC/test scripts

**Files:**
- Move: `Day2Day_Utillites/{Sample2Test,SampleTest,Sample_RCTest,LDGLoadTest,pysparkpoc,pyspakrPeedata,PeerMetricFile}.py` → `Day2Day_Utillites/archive/`
- Create: `Day2Day_Utillites/archive/README.md`

**Interfaces:**
- Produces: an `archive/` folder; the 9 (+1) cataloged scripts remain importable at the project root.

- [ ] **Step 1: Confirm nothing imports the POC scripts**

Run (from `Day2Day_Utillites/`):
```powershell
Select-String -Path *.py -Pattern "import (Sample2Test|SampleTest|Sample_RCTest|LDGLoadTest|pysparkpoc|pyspakrPeedata|PeerMetricFile)|from (Sample2Test|SampleTest|Sample_RCTest|LDGLoadTest|pysparkpoc|pyspakrPeedata|PeerMetricFile)"
```
Expected: no matches.

- [ ] **Step 2: Move the 7 files with git so history is preserved**

```powershell
New-Item -ItemType Directory -Force Day2Day_Utillites/archive | Out-Null
git mv Day2Day_Utillites/Sample2Test.py    Day2Day_Utillites/archive/
git mv Day2Day_Utillites/SampleTest.py     Day2Day_Utillites/archive/
git mv Day2Day_Utillites/Sample_RCTest.py  Day2Day_Utillites/archive/
git mv Day2Day_Utillites/LDGLoadTest.py    Day2Day_Utillites/archive/
git mv Day2Day_Utillites/pysparkpoc.py     Day2Day_Utillites/archive/
git mv Day2Day_Utillites/pyspakrPeedata.py Day2Day_Utillites/archive/
git mv Day2Day_Utillites/PeerMetricFile.py Day2Day_Utillites/archive/
```

- [ ] **Step 3: Write `archive/README.md`**

```markdown
# Archived scripts

Unmaintained load-tests and Spark experiments kept for reference only. They use
hardcoded credentials/paths and are **not** part of the utilities catalog, the
dashboard, or any skill. Do not rely on them for operational work.

| Script | What it was |
|--------|-------------|
| Sample2Test.py | RiskCalc token endpoint load test (async). |
| SampleTest.py | RiskCalc LC (Loss Calc) XML payload test. |
| Sample_RCTest.py | RiskCalc SOAP security service load test. |
| LDGLoadTest.py | LGD batch upload + status-check load test. |
| pysparkpoc.py | PySpark MD5-hashing proof of concept. |
| pyspakrPeedata.py | PySpark peer-data exploration (unfinished). |
| PeerMetricFile.py | pandas/Spark data-transform exploration (unfinished). |
```

- [ ] **Step 4: Smoke-check the kept scripts still import**

Run (from `Day2Day_Utillites/`):
```powershell
.\.venv\Scripts\python -c "import project_paths, LC_Process; print('infra ok')"
```
Expected: `infra ok` (no ImportError). Note: the operational scripts open DB/API connections only inside `main()`/`__main__`, so import alone is safe; we only smoke-import the side-effect-free modules here.

- [ ] **Step 5: Commit**

```powershell
git add Day2Day_Utillites/archive
git commit -m "chore(day2day): archive load-test/POC scripts out of the catalog"
```

---

### Task 2: Dependencies + the manifest (`utilities.yaml`)

**Files:**
- Modify: `Day2Day_Utillites/requirements.txt`
- Create: `Day2Day_Utillites/utilities.yaml`

**Interfaces:**
- Produces: `utilities.yaml` with a top-level `utilities:` list; each entry has keys `id, name, script, category, purpose, invocation, args[], env_required[], outputs{}, docs[], safety`. Consumed by Task 3's loader.

- [ ] **Step 1: Add dashboard deps to `requirements.txt`**

Append:
```
# Catalog dashboard (dashboard/serve.py)
fastapi>=0.110
uvicorn>=0.30
pydantic>=2.6,<3
PyYAML>=6.0
```

- [ ] **Step 2: Install them**

Run (from `Day2Day_Utillites/`):
```powershell
.\.venv\Scripts\pip install -r requirements.txt
```
Expected: fastapi, uvicorn, pydantic, PyYAML resolved/installed.

- [ ] **Step 3: Write `utilities.yaml`**

Author the file below verbatim. Categories: `stale-entity-refresh`, `portfolio-kpi-ops`, `edfx-entity-ops`, `dynamo-batch-update`. Arg flags/choices/defaults are transcribed from each script's `parse_args`.

```yaml
categories:
  - id: stale-entity-refresh
    name: Stale Entity Refresh
  - id: portfolio-kpi-ops
    name: Portfolio KPI Ops
  - id: edfx-entity-ops
    name: EDFX Entity Ops
  - id: dynamo-batch-update
    name: DynamoDB Batch Update

utilities:
  # ---------------- stale-entity-refresh ----------------
  - id: export-stale-entities-from-excel
    name: Export Stale Entities from Excel
    script: export_stale_entities_from_excel.py
    category: stale-entity-refresh
    purpose: "Read external_id column from Excel, find entities not updated in N days, export distinct stale ids to CSV."
    invocation: cli
    args:
      - flag: --input
        default: "inputfiles/StaleEntityRefresh/Entit_Refresh_Queue_Data_May8th.xlsx"
        help: "Excel file containing an external_id column."
      - flag: --output
        help: "CSV path. Default output/stale_entities/stale_external_ids_<utc>.csv."
      - flag: --stale-days
        type: int
        default: 10
        help: "Include an id only if no entity row was updated within this many days."
    env_required: [TESSERA_POSTGRES_HOST, TESSERA_POSTGRES_PORT, TESSERA_POSTGRES_DB, TESSERA_POSTGRES_USER, TESSERA_POSTGRES_PASSWORD]
    outputs:
      output_glob: "stale_entities/stale_external_ids_*"
    docs: []
    safety: "Read-only against prod Postgres."

  - id: validate-stale-entities
    name: Validate / Reconcile Stale Entities
    script: validate_stale_entities.py
    category: stale-entity-refresh
    purpose: "Re-run the stale query and export every still-stale entity to CSV with entity_data flattened."
    invocation: cli
    args:
      - flag: --entity-type
        choices: [custom, private]
        default: private
        help: "custom (custom_id NOT NULL) or private (custom_id NULL)."
      - flag: --date-filter
        help: "Stale cutoff YYYY-MM-DD. Default first of current month."
      - flag: --all-entities
        type: bool
        help: "Include all matching entities, ignore the stale-date filter."
      - flag: --tenant-id
        help: "Restrict to a single tenant_id."
      - flag: --limit
        type: int
        help: "Cap rows written (testing)."
      - flag: --output
        help: "CSV path. Default output/stale_entities/stale_reconcile_<type>_<utc>.csv."
    env_required: [TESSERA_POSTGRES_HOST, TESSERA_POSTGRES_PORT, TESSERA_POSTGRES_DB, TESSERA_POSTGRES_USER, TESSERA_POSTGRES_PASSWORD]
    outputs:
      logs_glob: "validate_stale_entities_*"
      output_glob: "stale_entities/stale_reconcile_*"
      summary_suffix: ".summary.json"
    docs: ["docs/superpowers/specs/2026-07-02-stale-entity-reconciliation-export-design.md"]
    safety: "Read-only against prod Postgres. Report, not a pass/fail gate."

  - id: refresh-stale-non-public-entities
    name: Refresh Stale Non-Public Entities
    script: refresh_stale_non_public_entities.py
    category: stale-entity-refresh
    purpose: "Refresh stale private/custom entities via the Tessera refreshEntities API in batches with retries and resume."
    invocation: cli
    args:
      - flag: --entity-type
        choices: [custom, private]
        default: private
        help: "custom (non-public-customized) or private (non-public)."
      - flag: --date-filter
        help: "Stale cutoff YYYY-MM-DD. Default first of current month."
      - flag: --stale-date-column
        choices: [updated_date, pd_last_known_date]
        default: updated_date
        help: "Column compared against the stale cutoff."
      - flag: --batch-size
        type: int
        default: 500
        help: "Entities per API payload."
      - flag: --limit
        type: int
        help: "Cap total entities (testing)."
      - flag: --resume-from-batch
        type: int
        default: 1
        help: "Skip batches before this number (1-based) to resume a stopped run."
      - flag: --workers
        type: int
        help: "Parallel API submission workers. 1 = sequential."
      - flag: --financial-max-age-years
        type: int
        help: "Only refresh entities whose financialStmtDate is missing or within N years. 0 disables."
      - flag: --max-retries
        type: int
        default: 4
        help: "Retry attempts with exponential backoff on 429/5xx or network errors. 0 disables."
      - flag: --dry-run
        type: bool
        help: "Query DB and log batches without calling refreshEntities."
      - flag: --tenant-id
        help: "Restrict refresh to a single tenant_id."
      - flag: --all-entities
        type: bool
        help: "Include all matching entities, not only stale ones."
    env_required: [MOODYS_SSO_USERNAME, MOODYS_SSO_PASSWORD, TESSERA_BASE_URL, TESSERA_POSTGRES_HOST, TESSERA_POSTGRES_PORT, TESSERA_POSTGRES_DB, TESSERA_POSTGRES_USER, TESSERA_POSTGRES_PASSWORD]
    outputs:
      logs_glob: "refresh_stale_entities_*"
      summary_suffix: ".summary.json"
    docs: ["docs/superpowers/specs/2026-07-02-selectable-staleness-date-column-design.md"]
    safety: "Writes to prod via Tessera refreshEntities. ALWAYS run --dry-run first."

  - id: test-single-entity-refresh
    name: Verify Single Entity Refresh
    script: test_single_entity_refresh.py
    category: stale-entity-refresh
    purpose: "Refresh the top-N stale entities one at a time and poll until pd_last_known_date advances — used to verify the refresh path end-to-end."
    invocation: cli
    args:
      - flag: --count
        type: int
        default: 10
        help: "Number of top stale entities to test."
      - flag: --entity-type
        choices: [custom, private]
        default: custom
        help: "custom or private."
      - flag: --date-filter
        help: "Stale cutoff YYYY-MM-DD. Default first of month."
      - flag: --financial-max-age-years
        type: int
        help: "Only include entities with financialStmtDate missing or within N years. 0 disables."
      - flag: --max-wait
        type: int
        default: 180
        help: "Seconds to poll for pd_last_known_date to advance."
      - flag: --interval
        type: int
        default: 30
        help: "Poll interval seconds."
      - flag: --recheck-from
        help: "Skip submit; re-compare against a saved before-snapshot JSON."
    env_required: [MOODYS_SSO_USERNAME, MOODYS_SSO_PASSWORD, TESSERA_BASE_URL, TESSERA_POSTGRES_HOST, TESSERA_POSTGRES_PORT, TESSERA_POSTGRES_DB, TESSERA_POSTGRES_USER, TESSERA_POSTGRES_PASSWORD]
    outputs:
      logs_glob: "test_single_entity_refresh_*"
    docs: []
    safety: "Submits real refreshes for a handful of entities. Keep --count small."

  # ---------------- portfolio-kpi-ops ----------------
  - id: run-portfolio-kpis-postgres
    name: Run Portfolio KPIs
    script: run_portfolio_kpis_postgres.py
    category: portfolio-kpi-ops
    purpose: "List portfolio ids and/or run the calculate_portfolio_kpis(id) stored procedure per portfolio."
    invocation: cli
    args:
      - flag: --portfolio-id
        help: "Run only this portfolio id (repeat for multiple). Skips reading the portfolio table."
      - flag: --portfolio-ids
        help: "Comma-separated portfolio ids."
      - flag: --tenant-id
        help: "Only load portfolio rows for this tenant (requires DB read)."
      - flag: --list-only
        type: bool
        help: "Log the id list; do not call calculate_portfolio_kpis."
      - flag: --export-list
        help: "Write portfolio_id column to this CSV (relative → output/portfolio/)."
    env_required: [TESSERA_POSTGRES_HOST, TESSERA_POSTGRES_PORT, TESSERA_POSTGRES_DB, TESSERA_POSTGRES_USER, TESSERA_POSTGRES_PASSWORD]
    outputs:
      logs_glob: "run_portfolio_kpis_postgres_*"
      output_glob: "portfolio/*"
    docs: ["Day2Day_Utillites/Docs/run-portfolio-kpis-postgres.md"]
    safety: "Executes a stored procedure that recomputes KPIs on prod. Use --list-only to preview."

  - id: portfolio-kpi-metrics-postgres
    name: Portfolio KPI Metrics
    script: portfolio_kpi_metrics_postgres.py
    category: portfolio-kpi-ops
    purpose: "Report on the portfolio_kpi_update_log: hourly volume, status breakdowns, slow-message analysis."
    invocation: cli
    args:
      - flag: --start
        required: true
        help: 'Window start inclusive, e.g. "2026-05-20 00:00:00".'
      - flag: --end
        required: true
        help: 'Window end exclusive, e.g. "2026-05-21 00:00:00".'
      - flag: --report
        required: true
        choices: [hourly, hourly_by_status, status, slow, slow_by_source, all]
        help: "Which report to run."
      - flag: --source
        help: 'Filter slow reports to a source (e.g. "Custom Financials").'
      - flag: --export-csv
        help: "Write each report to CSV (relative → output/portfolio_kpi_metrics/)."
    env_required: [TESSERA_POSTGRES_HOST, TESSERA_POSTGRES_PORT, TESSERA_POSTGRES_DB, TESSERA_POSTGRES_USER, TESSERA_POSTGRES_PASSWORD]
    outputs:
      output_glob: "portfolio_kpi_metrics/*"
    docs: ["Day2Day_Utillites/Docs/portfolio-kpi-metrics.md"]
    safety: "Read-only against prod Postgres."

  # ---------------- edfx-entity-ops ----------------
  - id: financials-delete-custom-entity
    name: Delete Custom Entity
    script: financials_delete_custom_entity.py
    category: edfx-entity-ops
    purpose: "DELETE one or many custom entities via the EDFX Financials API."
    invocation: cli
    args:
      - flag: --entity-id
        help: "One UUID or comma-separated list. Falls back to EDFX_DELETE_ENTITY_IDS env."
      - flag: --token
        help: "OAuth bearer token (no 'Bearer ' prefix). Falls back to EDFX_TOKEN env."
      - flag: --base-url
        help: "API host base URL."
      - flag: --cookie
        help: "Optional Cookie header value."
      - flag: --timeout
        type: int
        default: 60
        help: "Request timeout seconds."
    env_required: [EDFX_TOKEN, EDFX_DELETE_ENTITY_IDS, EDFX_COOKIE]
    outputs: {}
    docs: []
    safety: "DESTRUCTIVE: permanently deletes entities on prod. Double-check ids first."

  - id: edfx-process-status
    name: EDFX Process Status
    script: EDFX_ProcessStatus.py
    category: edfx-entity-ops
    purpose: "Authenticate via SSO, load process ids from Postgres, fetch statuses in parallel, write a multi-sheet Excel error report."
    invocation: env-config
    args: []
    env_required: [MOODYS_SSO_USERNAME, MOODYS_SSO_PASSWORD, EDFX_BASE_URL, EDFX_OUTPUT_FOLDER, TESSERA_POSTGRES_HOST, TESSERA_POSTGRES_PORT, TESSERA_POSTGRES_DB, TESSERA_POSTGRES_USER, TESSERA_POSTGRES_PASSWORD]
    outputs:
      output_glob: "edfx_process_status/*"
    docs: []
    safety: "Read-only diagnostics. Configure the run via .env before launching."

  - id: build-opensearch-entity-query-from-csv
    name: Build OpenSearch Entity Query
    script: build_opensearch_entity_query_from_csv.py
    category: edfx-entity-ops
    purpose: "Build OpenSearch _search JSON and queries payload files from a CSV companyIdentifier column, chunked."
    invocation: cli
    args:
      - flag: --csv
        help: "CSV path. Default: newest *.csv under BulkUplaodFiles."
      - flag: --tenant-id
        help: "tenantId.keyword value. Falls back to OPENSEARCH_TENANT_ID env."
      - flag: --size
        type: int
        default: 10
        help: "Search size."
      - flag: --output-dir
        help: "Write full + chunked + payload JSON here (relative → output/opensearch_queries/)."
      - flag: --out
        help: "Write OpenSearch _search JSON only to this path."
      - flag: --queries-out
        help: "Write queries payload only (chunked)."
      - flag: --queries-entities-per-file
        type: int
        default: 100
        help: "Max unique entities per queries JSON file."
      - flag: --distinct-count
        type: bool
        help: "Print distinct id count/row stats; write no files."
      - flag: --opensearch-result-cap
        type: int
        help: "Max size in generated OpenSearch bodies under --output-dir."
    env_required: [OPENSEARCH_TENANT_ID]
    outputs:
      output_glob: "opensearch_queries/*"
    docs: []
    safety: "Local file generation only. No network or DB."

  # ---------------- dynamo-batch-update ----------------
  - id: dynamodb-batch-update-createdby
    name: DynamoDB Batch Update (CreatedBy)
    script: DynamoDB_BatchUpdate_CreatedBy.py
    category: dynamo-batch-update
    purpose: "Scan a DynamoDB table and batch-update a field value, with dry-run safety and parallel writes."
    invocation: env-config
    args: []
    env_required: [AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION]
    outputs: {}
    docs: []
    safety: "DESTRUCTIVE when DRY_RUN=False. Edit the in-script config constants; keep DRY_RUN=True until verified."
```

- [ ] **Step 4: Verify the YAML parses and env names match the scripts**

Run (from `Day2Day_Utillites/`):
```powershell
.\.venv\Scripts\python -c "import yaml; d=yaml.safe_load(open('utilities.yaml',encoding='utf-8')); print(len(d['utilities']),'utilities,',len(d['categories']),'categories')"
```
Expected: `10 utilities, 4 categories`.

Then confirm each `env_required` name actually appears in its script (spot-check; fixes any drift):
```powershell
Select-String -Path refresh_stale_non_public_entities.py -Pattern "TESSERA_BASE_URL|MOODYS_SSO_USERNAME" | Select-Object -First 3
```
Expected: matches found. If any env name in the manifest is absent from its script, correct the manifest to the real name (`os.getenv(...)` / `os.environ[...]`).

- [ ] **Step 5: Commit**

```powershell
git add Day2Day_Utillites/requirements.txt Day2Day_Utillites/utilities.yaml
git commit -m "feat(day2day): add utilities manifest + dashboard deps"
```

---

### Task 3: Manifest loader + validation (`dashboard/manifest.py`)

**Files:**
- Create: `Day2Day_Utillites/dashboard/__init__.py` (empty)
- Create: `Day2Day_Utillites/dashboard/manifest.py`

**Interfaces:**
- Produces:
  - `class Arg(BaseModel)`: `flag: str`, `type: str = "str"`, `choices: list[str] | None`, `default: object | None`, `required: bool = False`, `help: str = ""`.
  - `class Outputs(BaseModel)`: `logs_glob: str | None`, `output_glob: str | None`, `summary_suffix: str | None`.
  - `class Utility(BaseModel)`: `id, name, script, category, purpose, invocation, args: list[Arg], env_required: list[str], outputs: Outputs, docs: list[str], safety: str`.
  - `class Category(BaseModel)`: `id: str`, `name: str`.
  - `class Manifest(BaseModel)`: `categories: list[Category]`, `utilities: list[Utility]`.
  - `load_manifest(path: Path | None = None) -> Manifest` — reads `utilities.yaml` beside the project root; raises `ManifestError` (subclass of `Exception`) with a readable message on parse/validation failure.
  - `MANIFEST_PATH: Path` — `project_paths.PROJECT_ROOT / "utilities.yaml"`.

- [ ] **Step 1: Create the package marker**

Create empty `Day2Day_Utillites/dashboard/__init__.py`.

- [ ] **Step 2: Write `dashboard/manifest.py`**

```python
"""Load and validate the utilities catalog manifest (utilities.yaml)."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

import project_paths

MANIFEST_PATH = project_paths.PROJECT_ROOT / "utilities.yaml"


class ManifestError(Exception):
    """Raised when the manifest is missing or fails validation."""


class Arg(BaseModel):
    flag: str
    type: str = "str"
    choices: list[str] | None = None
    default: object | None = None
    required: bool = False
    help: str = ""


class Outputs(BaseModel):
    logs_glob: str | None = None
    output_glob: str | None = None
    summary_suffix: str | None = None


class Utility(BaseModel):
    id: str
    name: str
    script: str
    category: str
    purpose: str
    invocation: str  # "cli" | "env-config"
    args: list[Arg] = []
    env_required: list[str] = []
    outputs: Outputs = Outputs()
    docs: list[str] = []
    safety: str = ""


class Category(BaseModel):
    id: str
    name: str


class Manifest(BaseModel):
    categories: list[Category]
    utilities: list[Utility]


def load_manifest(path: Path | None = None) -> Manifest:
    p = path or MANIFEST_PATH
    if not p.exists():
        raise ManifestError(f"Manifest not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(f"Manifest YAML parse error: {exc}") from exc
    try:
        model = Manifest.model_validate(raw)
    except ValidationError as exc:
        raise ManifestError(f"Manifest validation error: {exc}") from exc
    known = {c.id for c in model.categories}
    bad = [u.id for u in model.utilities if u.category not in known]
    if bad:
        raise ManifestError(f"Utilities reference unknown categories: {bad}")
    return model
```

- [ ] **Step 3: Verify it loads the real manifest**

Run (from `Day2Day_Utillites/`):
```powershell
.\.venv\Scripts\python -c "from dashboard.manifest import load_manifest; m=load_manifest(); print(len(m.utilities),'utilities'); print(sorted({u.category for u in m.utilities}))"
```
Expected: `10 utilities` and the 4 category ids listed.

- [ ] **Step 4: Verify a bad manifest raises `ManifestError`**

```powershell
.\.venv\Scripts\python -c "from pathlib import Path; from dashboard.manifest import load_manifest, ManifestError; import tempfile,os; f=Path(tempfile.gettempdir())/'bad.yaml'; f.write_text('utilities: 5'); import sys
try:
    load_manifest(f); print('NO ERROR - FAIL')
except ManifestError as e:
    print('ManifestError raised - OK')"
```
Expected: `ManifestError raised - OK`.

- [ ] **Step 5: Commit**

```powershell
git add Day2Day_Utillites/dashboard/__init__.py Day2Day_Utillites/dashboard/manifest.py
git commit -m "feat(dashboard): manifest loader with pydantic validation"
```

---

### Task 4: Run-history scanner (`dashboard/runs.py`)

**Files:**
- Create: `Day2Day_Utillites/dashboard/runs.py`

**Interfaces:**
- Consumes: `Utility` from `dashboard.manifest`; `project_paths.logs_dir()`, `project_paths.output_dir()`.
- Produces:
  - `class RunFile(TypedDict)`: `kind: str` (`"log"` | `"output"`), `name: str`, `mtime: float`, `size: int`, `summary: dict | None`.
  - `list_runs(util: Utility, limit: int = 20) -> list[RunFile]` — newest first, across both globs; parses a `.summary.json` sidecar when `outputs.summary_suffix` is set and the file exists; tolerates missing dirs and bad JSON.
  - `resolve_artifact(kind: str, name: str) -> Path | None` — path-traversal-safe resolution of a single file for download; returns `None` if `name` escapes the base dir or does not exist.

- [ ] **Step 1: Write `dashboard/runs.py`**

```python
"""Scan logs/ and output/ for a utility's recent runs and artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

import project_paths
from dashboard.manifest import Utility


class RunFile(TypedDict):
    kind: str
    name: str
    mtime: float
    size: int
    summary: dict | None


def _base(kind: str) -> Path:
    return project_paths.logs_dir() if kind == "log" else project_paths.output_dir()


def _read_summary(path: Path, suffix: str | None) -> dict | None:
    if not suffix:
        return None
    sidecar = path.with_name(path.name + suffix)
    if not sidecar.exists():
        # Also try replacing the extension (e.g. foo.log -> foo.summary.json).
        sidecar = path.with_suffix("").with_name(path.stem + suffix)
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_runs(util: Utility, limit: int = 20) -> list[RunFile]:
    runs: list[RunFile] = []
    pairs = [("log", util.outputs.logs_glob), ("output", util.outputs.output_glob)]
    for kind, glob in pairs:
        if not glob:
            continue
        base = _base(kind)
        if not base.exists():
            continue
        for p in base.glob(glob):
            if not p.is_file():
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            runs.append(
                RunFile(
                    kind=kind,
                    name=str(p.relative_to(base)).replace("\\", "/"),
                    mtime=st.st_mtime,
                    size=st.st_size,
                    summary=_read_summary(p, util.outputs.summary_suffix),
                )
            )
    runs.sort(key=lambda r: r["mtime"], reverse=True)
    return runs[:limit]


def resolve_artifact(kind: str, name: str) -> Path | None:
    if kind not in ("log", "output"):
        return None
    base = _base(kind).resolve()
    target = (base / name).resolve()
    if base not in target.parents and target != base:
        return None
    if not target.is_file():
        return None
    return target
```

- [ ] **Step 2: Verify against real logs/output**

`stale-entity-refresh` (`validate_stale_entities` / `refresh`) and `portfolio-kpi-ops` already have files under `logs/` and `output/`. Run (from `Day2Day_Utillites/`):
```powershell
.\.venv\Scripts\python -c "from dashboard.manifest import load_manifest; from dashboard.runs import list_runs; m=load_manifest(); u=[u for u in m.utilities if u.id=='run-portfolio-kpis-postgres'][0]; r=list_runs(u); print(len(r),'runs'); print(r[0]['name'] if r else 'none')"
```
Expected: a non-zero count and a `run_portfolio_kpis_postgres_*.log` filename (matching the files under `logs/`).

- [ ] **Step 3: Verify traversal guard rejects escapes**

```powershell
.\.venv\Scripts\python -c "from dashboard.runs import resolve_artifact; print(resolve_artifact('log','../utilities.yaml')); print(resolve_artifact('bogus','x'))"
```
Expected: both print `None`.

- [ ] **Step 4: Commit**

```powershell
git add Day2Day_Utillites/dashboard/runs.py
git commit -m "feat(dashboard): run-history scanner with traversal-safe artifact resolver"
```

---

### Task 5: FastAPI app (`dashboard/serve.py`)

**Files:**
- Create: `Day2Day_Utillites/dashboard/serve.py`

**Interfaces:**
- Consumes: `load_manifest`, `ManifestError` from `dashboard.manifest`; `list_runs`, `resolve_artifact` from `dashboard.runs`.
- Produces: `app: FastAPI` with routes `GET /api/utilities`, `GET /api/utilities/{uid}/runs`, `GET /download/{kind}/{name}`, and static mount at `/app`. Root `GET /` redirects to `/app/`.

- [ ] **Step 1: Write `dashboard/serve.py`**

```python
"""Read-only catalog dashboard for Day2Day utilities. Serves the SPA at /app/."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from dashboard.manifest import ManifestError, load_manifest
from dashboard.runs import list_runs, resolve_artifact

app = FastAPI(title="Day2Day Utilities Catalog")

_DASHBOARD_DIR = Path(__file__).resolve().parent
_APP_DIR = _DASHBOARD_DIR / "app"


@app.get("/")
def _root() -> RedirectResponse:
    return RedirectResponse(url="/app/")


@app.get("/api/utilities")
def get_utilities() -> JSONResponse:
    try:
        m = load_manifest()
    except ManifestError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JSONResponse(m.model_dump())


@app.get("/api/utilities/{uid}/runs")
def get_runs(uid: str) -> JSONResponse:
    try:
        m = load_manifest()
    except ManifestError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    match = [u for u in m.utilities if u.id == uid]
    if not match:
        raise HTTPException(status_code=404, detail=f"Unknown utility: {uid}")
    return JSONResponse({"runs": list_runs(match[0])})


@app.get("/download/{kind}/{name:path}")
def download(kind: str, name: str) -> FileResponse:
    target = resolve_artifact(kind, name)
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(target)


app.mount("/app", StaticFiles(directory=_APP_DIR, html=True), name="dashboard")
```

- [ ] **Step 2: Create a placeholder static dir so the mount loads**

The `StaticFiles` mount requires the directory to exist. Create `Day2Day_Utillites/dashboard/app/index.html` with a one-line placeholder for now (Task 6 replaces it):
```html
<!doctype html><title>Day2Day Utilities</title><p>loading…</p>
```

- [ ] **Step 3: Start the server and verify the API**

Run (from `Day2Day_Utillites/`), in one shell:
```powershell
.\.venv\Scripts\python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021
```
In another shell:
```powershell
curl.exe -s http://127.0.0.1:8021/api/utilities | Select-String -Pattern '"id"' | Measure-Object | Select-Object -ExpandProperty Count
curl.exe -s http://127.0.0.1:8021/api/utilities/run-portfolio-kpis-postgres/runs
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8021/api/utilities/nope/runs
```
Expected: the first returns a count ≥ 10 (utility + category ids); the second returns a JSON `{"runs":[...]}` with entries; the third prints `404`. Stop the server (Ctrl+C).

- [ ] **Step 4: Commit**

```powershell
git add Day2Day_Utillites/dashboard/serve.py Day2Day_Utillites/dashboard/app/index.html
git commit -m "feat(dashboard): FastAPI catalog API + static mount"
```

---

### Task 6: Static SPA (`dashboard/app/index.html`)

**Files:**
- Modify: `Day2Day_Utillites/dashboard/app/index.html` (replace the placeholder)

**Interfaces:**
- Consumes: `GET /api/utilities`, `GET /api/utilities/{id}/runs`, `GET /download/{kind}/{name}`.
- Produces: the operator UI (no exports consumed by later tasks).

- [ ] **Step 1: Replace `index.html` with the full SPA**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Day2Day Utilities Catalog</title>
  <style>
    :root { --bg:#0f1720; --panel:#16212e; --edge:#26374a; --ink:#e6edf3; --muted:#8aa0b4; --accent:#4aa3ff; }
    * { box-sizing: border-box; }
    body { margin:0; font:14px/1.5 system-ui,Segoe UI,Arial; background:var(--bg); color:var(--ink); }
    header { padding:14px 20px; border-bottom:1px solid var(--edge); font-weight:600; }
    .wrap { display:grid; grid-template-columns:360px 1fr; height:calc(100vh - 51px); }
    .list { overflow:auto; border-right:1px solid var(--edge); padding:12px; }
    .detail { overflow:auto; padding:20px; }
    h2.cat { font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin:16px 0 6px; }
    .card { background:var(--panel); border:1px solid var(--edge); border-radius:8px; padding:10px 12px; margin-bottom:8px; cursor:pointer; }
    .card:hover { border-color:var(--accent); }
    .card.active { border-color:var(--accent); box-shadow:0 0 0 1px var(--accent); }
    .card .name { font-weight:600; }
    .card .purpose { color:var(--muted); font-size:12px; }
    .badge { display:inline-block; font-size:11px; padding:1px 7px; border-radius:10px; border:1px solid var(--edge); color:var(--muted); margin-right:4px; }
    .chip { display:inline-block; font-size:11px; padding:1px 7px; border-radius:4px; background:#1e2c3b; margin:2px 4px 2px 0; }
    .field { margin:8px 0; }
    label { display:block; color:var(--muted); font-size:12px; margin-bottom:2px; }
    input[type=text] { width:100%; background:#0c141d; border:1px solid var(--edge); color:var(--ink); padding:6px 8px; border-radius:6px; }
    pre.cmd { background:#0c141d; border:1px solid var(--edge); border-radius:6px; padding:10px; overflow-x:auto; white-space:pre-wrap; }
    button { background:var(--accent); color:#03121f; border:0; padding:6px 12px; border-radius:6px; cursor:pointer; font-weight:600; }
    table { width:100%; border-collapse:collapse; margin-top:8px; }
    th,td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--edge); font-size:12px; }
    a { color:var(--accent); }
    .safety { border-left:3px solid #d98c00; background:#231b0e; padding:8px 10px; border-radius:0 6px 6px 0; margin:10px 0; }
    .empty { color:var(--muted); }
  </style>
</head>
<body>
  <header>Day2Day Utilities — Catalog Dashboard</header>
  <div class="wrap">
    <div class="list" id="list"></div>
    <div class="detail" id="detail"><p class="empty">Select a utility.</p></div>
  </div>
  <script>
    let MANIFEST = null;
    const byId = {};

    async function boot() {
      const res = await fetch('/api/utilities');
      if (!res.ok) { document.getElementById('list').innerHTML =
        '<p class="empty">Manifest error: ' + (await res.text()) + '</p>'; return; }
      MANIFEST = await res.json();
      MANIFEST.utilities.forEach(u => byId[u.id] = u);
      renderList();
    }

    function renderList() {
      const el = document.getElementById('list');
      el.innerHTML = '';
      MANIFEST.categories.forEach(cat => {
        const uts = MANIFEST.utilities.filter(u => u.category === cat.id);
        if (!uts.length) return;
        const h = document.createElement('h2'); h.className = 'cat'; h.textContent = cat.name; el.appendChild(h);
        uts.forEach(u => {
          const c = document.createElement('div'); c.className = 'card'; c.dataset.id = u.id;
          c.innerHTML = '<div class="name">' + esc(u.name) + '</div>' +
            '<div class="purpose">' + esc(u.purpose) + '</div>' +
            '<div style="margin-top:4px"><span class="badge">' + u.invocation + '</span>' +
            u.env_required.slice(0,3).map(e => '<span class="badge">' + esc(e) + '</span>').join('') + '</div>';
          c.onclick = () => select(u.id);
          el.appendChild(c);
        });
      });
    }

    function buildCommand(u) {
      const parts = ['python', u.script];
      u.args.forEach(a => {
        const v = document.getElementById('arg-' + cssId(a.flag));
        if (!v) return;
        if (a.type === 'bool') { if (v.checked) parts.push(a.flag); }
        else if (v.value.trim() !== '') { parts.push(a.flag, quote(v.value.trim())); }
      });
      return parts.join(' ');
    }

    function select(id) {
      const u = byId[id];
      document.querySelectorAll('.card').forEach(c => c.classList.toggle('active', c.dataset.id === id));
      const d = document.getElementById('detail');
      let html = '<h2>' + esc(u.name) + '</h2><p class="empty">' + esc(u.purpose) + '</p>';
      if (u.safety) html += '<div class="safety">⚠ ' + esc(u.safety) + '</div>';

      if (u.args.length) {
        html += '<h3>Arguments</h3>';
        u.args.forEach(a => {
          const id2 = 'arg-' + cssId(a.flag);
          html += '<div class="field"><label>' + esc(a.flag) +
            (a.required ? ' *' : '') + (a.choices ? ' (' + a.choices.join('/') + ')' : '') +
            '</label>';
          if (a.type === 'bool') html += '<input type="checkbox" id="' + id2 + '" oninput="refreshCmd()">';
          else html += '<input type="text" id="' + id2 + '" placeholder="' +
            esc(a.default != null ? String(a.default) : '') + '" oninput="refreshCmd()">';
          html += (a.help ? '<div class="purpose">' + esc(a.help) + '</div>' : '') + '</div>';
        });
      } else {
        html += '<p class="empty">Configured via .env (no CLI arguments).</p>';
      }

      html += '<h3>Command</h3><pre class="cmd" id="cmd"></pre><button onclick="copyCmd()">Copy command</button>';
      html += '<h3>Environment</h3>' + (u.env_required.length
        ? u.env_required.map(e => '<span class="chip">' + esc(e) + '</span>').join('')
        : '<span class="empty">none</span>');
      if (u.docs.length) html += '<h3>Docs</h3><ul>' +
        u.docs.map(dp => '<li>' + esc(dp) + '</li>').join('') + '</ul>';
      html += '<h3>Run history</h3><div id="runs" class="empty">loading…</div>';
      d.innerHTML = html;
      refreshCmd();
      loadRuns(id);
    }

    function refreshCmd() {
      const id = document.querySelector('.card.active')?.dataset.id; if (!id) return;
      document.getElementById('cmd').textContent = buildCommand(byId[id]);
    }
    function copyCmd() { navigator.clipboard.writeText(document.getElementById('cmd').textContent); }

    async function loadRuns(id) {
      const res = await fetch('/api/utilities/' + id + '/runs');
      const box = document.getElementById('runs');
      if (!res.ok) { box.textContent = 'no run data'; return; }
      const runs = (await res.json()).runs;
      if (!runs.length) { box.textContent = 'No runs found yet.'; return; }
      let t = '<table><tr><th>File</th><th>When (UTC)</th><th>Size</th><th>Summary</th></tr>';
      runs.forEach(r => {
        const when = new Date(r.mtime * 1000).toISOString().replace('T',' ').slice(0,19);
        const sum = r.summary ? esc(JSON.stringify(r.summary).slice(0,120)) : '';
        t += '<tr><td><a href="/download/' + r.kind + '/' + encodeURIComponent(r.name) +
          '">' + esc(r.name) + '</a></td><td>' + when + '</td><td>' + r.size +
          '</td><td>' + sum + '</td></tr>';
      });
      box.innerHTML = t + '</table>';
    }

    const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
    const cssId = s => s.replace(/[^a-z0-9]/gi, '');
    const quote = v => /\s/.test(v) ? '"' + v + '"' : v;
    boot();
  </script>
</body>
</html>
```

- [ ] **Step 2: Manual browser verification**

Start the server (from `Day2Day_Utillites/`):
```powershell
.\.venv\Scripts\python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021
```
Open `http://127.0.0.1:8021/app/` and confirm:
- Four category headings, 10 cards total.
- Clicking `Run Portfolio KPIs` shows args; typing in `--tenant-id` and toggling `--list-only` updates the Command box to a valid `python run_portfolio_kpis_postgres.py ...` string.
- The Run history table lists real `run_portfolio_kpis_postgres_*.log` files with working download links.
- Clicking an `env-config` utility (e.g. `EDFX Process Status`) shows "Configured via .env" and no arg inputs.

Stop the server.

- [ ] **Step 3: Commit**

```powershell
git add Day2Day_Utillites/dashboard/app/index.html
git commit -m "feat(dashboard): catalog SPA with arg-form command builder + run history"
```

---

### Task 7: The four skills

**Files:**
- Create: `.claude/skills/stale-entity-refresh/SKILL.md`
- Create: `.claude/skills/portfolio-kpi-ops/SKILL.md`
- Create: `.claude/skills/edfx-entity-ops/SKILL.md`
- Create: `.claude/skills/dynamo-batch-update/SKILL.md`

**Interfaces:**
- Each cites `Day2Day_Utillites/utilities.yaml` as the canonical arg/env reference and the dashboard launch command. No code exports.

- [ ] **Step 1: Write `stale-entity-refresh/SKILL.md`**

```markdown
---
name: stale-entity-refresh
description: Use when refreshing or reconciling stale non-public (private/custom) entities — finding which external ids are stale, exporting them, submitting refreshes via the Tessera refreshEntities API, or verifying a refresh actually advanced pd_last_known_date.
---

# Stale Entity Refresh

Tools live in `Day2Day_Utillites/`. Run everything from that folder with its venv
(`.\.venv\Scripts\python`), with `.env` populated. Canonical args/env for every
command are in `Day2Day_Utillites/utilities.yaml`; browse them in the dashboard
(see bottom).

## The pipeline (find → reconcile → refresh → verify)

1. **Export stale ids from an Excel queue** (read-only):
   `python export_stale_entities_from_excel.py --input <queue.xlsx> --stale-days 10`
   → `output/stale_entities/stale_external_ids_<utc>.csv`.

2. **Reconcile** — dump every still-stale entity with `entity_data` flattened (read-only):
   `python validate_stale_entities.py --entity-type custom`
   → `output/stale_entities/stale_reconcile_<type>_<utc>.csv` + a `.summary.json`.

3. **Refresh** — submit to Tessera. **Always dry-run first**:
   `python refresh_stale_non_public_entities.py --entity-type custom --dry-run`
   then drop `--dry-run` to submit. Key flags: `--stale-date-column {updated_date,pd_last_known_date}`,
   `--batch-size`, `--workers`, `--max-retries`, `--resume-from-batch`, `--limit`, `--tenant-id`.
   → run log + `.summary.json` in `logs/`.

4. **Verify** a handful end-to-end:
   `python test_single_entity_refresh.py --entity-type custom --count 10`
   polls until `pd_last_known_date` advances.

## Safety
- `refresh_*` and `test_single_*` **write to prod** via Tessera. Dry-run, small `--limit`/`--count`, verify, then scale.
- The others are read-only Postgres queries.

## Prereqs
`.env` must have `MOODYS_SSO_USERNAME`, `MOODYS_SSO_PASSWORD`, `TESSERA_BASE_URL`,
and the `TESSERA_POSTGRES_*` group. See `utilities.yaml` for the exact per-script list.

## Dashboard
```powershell
cd Day2Day_Utillites
.\.venv\Scripts\python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021
# http://127.0.0.1:8021/app/ — cards, copy-ready commands, and recent run history.
```
```

- [ ] **Step 2: Write `portfolio-kpi-ops/SKILL.md`**

```markdown
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
→ log in `logs/run_portfolio_kpis_postgres_*`, optional CSV in `output/portfolio/`.

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
```

- [ ] **Step 3: Write `edfx-entity-ops/SKILL.md`**

```markdown
---
name: edfx-entity-ops
description: Use for EDFX entity operations outside the stale-refresh flow — deleting custom entities via the Financials API, checking EDFX process/job statuses and producing an error report, or building OpenSearch _search/query payloads from a CSV of company identifiers.
---

# EDFX Entity Ops

Tools live in `Day2Day_Utillites/`. Run from that folder with `.\.venv\Scripts\python`.
Canonical args/env are in `Day2Day_Utillites/utilities.yaml`.

## Delete custom entities (DESTRUCTIVE)
`python financials_delete_custom_entity.py --entity-id <uuid[,uuid...]> --token <bearer>`
Falls back to `EDFX_DELETE_ENTITY_IDS` / `EDFX_TOKEN` from `.env` when flags are omitted.
Deletes are permanent — confirm the id list before running.

## Check process statuses (read-only, .env-configured)
`python EDFX_ProcessStatus.py`
Configure the run via `.env` (`MOODYS_SSO_*`, `EDFX_BASE_URL`, `EDFX_OUTPUT_FOLDER`,
`TESSERA_POSTGRES_*`). → multi-sheet Excel in `output/edfx_process_status/`.

## Build OpenSearch queries from a CSV (local only)
`python build_opensearch_entity_query_from_csv.py --csv <file.csv> --output-dir queries`
Reads a `companyIdentifier` column; writes full + chunked `_search` JSON and a queries
payload under `output/opensearch_queries/`. Use `--distinct-count` to inspect counts
without writing files. Do not combine `--output-dir` with `--out`/`--queries-out`.

## Prereqs
Per-script env differs (delete → `EDFX_*`; status → `MOODYS_SSO_*` + Postgres; query
builder → `OPENSEARCH_TENANT_ID`). See `utilities.yaml`.

## Dashboard
```powershell
cd Day2Day_Utillites
.\.venv\Scripts\python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021
# http://127.0.0.1:8021/app/
```
```

- [ ] **Step 4: Write `dynamo-batch-update/SKILL.md`**

```markdown
---
name: dynamo-batch-update
description: Use when batch-updating a field across DynamoDB records (e.g. the CreatedBy migration) — scanning a table for records matching a value and writing a new value in parallel, with a dry-run safety gate.
---

# DynamoDB Batch Update

Tool: `Day2Day_Utillites/DynamoDB_BatchUpdate_CreatedBy.py`. Run from that folder with
`.\.venv\Scripts\python`. Canonical env is in `Day2Day_Utillites/utilities.yaml`.

## How to run
This script is **configured by editing in-script constants** (table name, partition/sort
keys, `CURRENT_VALUE_TO_FIND` → `NEW_VALUE_TO_SET`, `ENVIRONMENT`, `DRY_RUN`), not CLI flags.

1. Edit the config block at the top of the script for your table and value mapping.
2. Keep `DRY_RUN = True`; run and review the sample records + counts it prints:
   `python DynamoDB_BatchUpdate_CreatedBy.py`
3. Only after the dry-run output looks correct, set `DRY_RUN = False` and re-run.

## Safety
DESTRUCTIVE when `DRY_RUN = False` — it updates prod DynamoDB rows in parallel. Never
skip the dry-run. Confirm the record count matches expectations before the real run.

## Prereqs
AWS credentials resolvable by boto3 (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_DEFAULT_REGION`, or an AWS CLI profile).

## Dashboard
```powershell
cd Day2Day_Utillites
.\.venv\Scripts\python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021
# http://127.0.0.1:8021/app/
```
```

- [ ] **Step 5: Verify skills are discoverable (frontmatter valid)**

Run (from repo root):
```powershell
Get-ChildItem .claude/skills -Directory | ForEach-Object { $f = Join-Path $_.FullName 'SKILL.md'; if (Test-Path $f) { "$($_.Name): " + ((Get-Content $f -TotalCount 3) -join ' | ') } }
```
Expected: each new skill prints `--- | name: <id> | description: Use when …`.

- [ ] **Step 6: Commit**

```powershell
git add .claude/skills/stale-entity-refresh .claude/skills/portfolio-kpi-ops .claude/skills/edfx-entity-ops .claude/skills/dynamo-batch-update
git commit -m "feat(skills): 4 Day2Day utility runbooks (stale-refresh, kpi, edfx, dynamo)"
```

---

### Task 8: Docs + final verification

**Files:**
- Modify: `README.md`
- Create: `Day2Day_Utillites/Docs/utilities-catalog.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Add a catalog note to `Day2Day_Utillites/Docs/utilities-catalog.md`**

```markdown
# Utilities Catalog & Dashboard

The production utilities in this folder are cataloged in `../utilities.yaml` and
surfaced two ways:

- **Skills** (repo `.claude/skills/`): task runbooks — `stale-entity-refresh`,
  `portfolio-kpi-ops`, `edfx-entity-ops`, `dynamo-batch-update`.
- **Catalog dashboard** — a read-only page listing each utility, a copy-ready command
  builder, required env, and recent run history:

  ```powershell
  cd Day2Day_Utillites
  .\.venv\Scripts\python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021
  # open http://127.0.0.1:8021/app/
  ```

Load-test / Spark POC scripts have been moved to `archive/` (see `archive/README.md`).
```

- [ ] **Step 2: Update the repo `README.md` Day2Day section**

After the Day2Day quick-start block in `README.md`, add:
```markdown
### Utilities catalog & dashboard

The production scripts are cataloged in `Day2Day_Utillites/utilities.yaml`, exposed as
four Claude Code skills (`.claude/skills/`), and browsable in a read-only dashboard:

```powershell
cd Day2Day_Utillites
.\.venv\Scripts\python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021
# http://127.0.0.1:8021/app/
```

See [Day2Day_Utillites/Docs/utilities-catalog.md](Day2Day_Utillites/Docs/utilities-catalog.md).
```

- [ ] **Step 3: Full end-to-end verification**

Run (from `Day2Day_Utillites/`):
```powershell
.\.venv\Scripts\python -c "from dashboard.manifest import load_manifest; m=load_manifest(); assert len(m.utilities)==10; assert {u.category for u in m.utilities}=={'stale-entity-refresh','portfolio-kpi-ops','edfx-entity-ops','dynamo-batch-update'}; print('manifest OK')"
.\.venv\Scripts\python -c "import project_paths, LC_Process; print('imports OK')"
```
Expected: `manifest OK` then `imports OK`.

Then start the server and confirm `http://127.0.0.1:8021/app/` renders all 10 cards under 4 headings with working run-history download links (as in Task 6, Step 2).

- [ ] **Step 4: Commit**

```powershell
git add README.md Day2Day_Utillites/Docs/utilities-catalog.md
git commit -m "docs(day2day): document utilities catalog, skills, and dashboard"
```

---

## Self-Review

**Spec coverage:**
- Manifest (§Component 1) → Task 2. ✓
- Dashboard API + UI + run history + download guard (§Component 2) → Tasks 4, 5, 6. ✓
- 4 skills (§Component 3) → Task 7 (plus a 4th stale-family utility, `test_single_entity_refresh`, discovered during planning and folded into `stale-entity-refresh`). ✓
- Archive + docs (§Component 4) → Tasks 1, 8. ✓
- Error handling: manifest 500 (Task 5 Step 1), run-scan tolerance (Task 4), traversal guard (Tasks 4–5). ✓
- Verification (§Verification) → per-task manual checks + Task 8 Step 3. ✓

**Placeholder scan:** No "TBD/TODO"; every code step has complete content. The one non-literal instruction (Task 2 Step 4: correct any env name that doesn't match its script) is a concrete verification action with an exact command, not a deferred design decision.

**Type consistency:** `load_manifest`/`ManifestError` (Task 3) are imported unchanged in Tasks 4–5. `list_runs`/`resolve_artifact` signatures (Task 4) match their calls in `serve.py` (Task 5). `RunFile` keys (`kind,name,mtime,size,summary`) match the SPA's `loadRuns` usage (Task 6). Port 8021 used consistently. Manifest field names (`invocation`, `env_required`, `outputs.{logs_glob,output_glob,summary_suffix}`, `args[].{flag,type,choices,default,required,help}`) match the pydantic models and the SPA.
