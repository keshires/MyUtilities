# Standardize input / output / logs into per-utility folders

**Date:** 2026-07-13
**Status:** Approved

## Goal

Give every Day2Day utility a predictable, self-documenting home for its files:

- Inputs it reads → `Day2Day_Utillites/input/<utility>/`
- Outputs it writes → `Day2Day_Utillites/output/<utility>/`
- Run logs / process history → `Day2Day_Utillites/logs/<utility>/`

`<utility>` is a **cleaned, meaningful per-script folder name** so a team member
browsing `logs/` or `output/` immediately knows which utility produced what.
Existing scattered artifacts are reorganized into this shape so the workspace is
tidy before merge.

## Scope

**Scripts modified (12):** the 10 cataloged utilities plus the two newer stale
tools that share the stale family.

Not touched: archived POC scripts; scripts that genuinely have no file I/O keep
none (except the two destructive tools below, which gain a run log by request).

## Folder-name mapping

| Script | Folder `<utility>` |
|--------|--------------------|
| `refresh_stale_non_public_entities.py` | `refresh_stale_entities` |
| `validate_stale_entities.py` | `validate_stale_entities` |
| `export_stale_entities_from_excel.py` | `export_stale_entities` |
| `test_single_entity_refresh.py` | `verify_single_entity_refresh` |
| `reprocess_stuck_financials.py` | `reprocess_stuck_financials` |
| `validate_stale_pd_source.py` | `validate_stale_pd_source` |
| `run_portfolio_kpis_postgres.py` | `run_portfolio_kpis` |
| `portfolio_kpi_metrics_postgres.py` | `portfolio_kpi_metrics` |
| `EDFX_ProcessStatus.py` | `edfx_process_status` |
| `build_opensearch_entity_query_from_csv.py` | `build_opensearch_query` |
| `financials_delete_custom_entity.py` | `delete_custom_entity` |
| `DynamoDB_BatchUpdate_CreatedBy.py` | `dynamodb_batch_update` |

## Mechanism — `project_paths.py`

- **Add** `input_dir(*parts: str) -> Path` → `<repo>/input/<parts...>/`, creating it
  (mirrors `output_dir`).
- **Extend** `logs_dir(*parts: str) -> Path` → `<repo>/logs/<parts...>/`, creating it.
  **Backward compatible:** `logs_dir()` with no args still returns `<repo>/logs`, so
  any script not being edited keeps working.
- `output_dir(*parts)` is already variadic — unchanged.
- `resolve_cli_artifact(path, *output_subfolders)` unchanged; callers pass the new
  per-utility subfolder name.
- Update the module docstring to describe `input/`, per-utility `output/`, and
  per-utility `logs/`.

## Per-script changes

For each of the 12 scripts, using its `<utility>` name from the table:

1. **Logs.** Every script that writes a run log switches `logs_dir()` →
   `logs_dir("<utility>")`. `.summary.json` / `.snapshot.json` / `.result.json`
   sidecars follow their log's new location.
2. **Outputs.** Every output artifact resolves under `output_dir("<utility>")`
   (or `resolve_cli_artifact(path, "<utility>")`). Existing category names
   (`stale_entities`, `portfolio`, `portfolio_kpi_metrics`, `edfx_process_status`,
   `opensearch_queries`) are replaced by the per-utility name.
   - **Fix:** `test_single_entity_refresh` currently writes `.snapshot.json` /
     `.result.json` into `logs/`; move those to `output/verify_single_entity_refresh/`
     (its log stays under `logs/verify_single_entity_refresh/`).
3. **Inputs.** Default `--input` / `--csv` point to `input/<utility>/`:
   - `export_stale_entities_from_excel`: default input → `input/export_stale_entities/`
     (was `inputfiles/StaleEntityRefresh/Entit_Refresh_Queue_Data_May8th.xlsx`).
   - `build_opensearch_entity_query_from_csv`: default `--csv` = newest `*.csv` under
     `input/build_opensearch_query/` (was `BulkUplaodFiles/`).
   An explicit CLI path always overrides the default.
4. **Add run logs** (new) to the two destructive tools, written via
   `logs_dir("<utility>")` with a timestamped filename, capturing the operation and
   its dry-run/real result:
   - `financials_delete_custom_entity` → `logs/delete_custom_entity/delete_custom_entity_<utc>.log`
   - `DynamoDB_BatchUpdate_CreatedBy` → `logs/dynamodb_batch_update/dynamodb_batch_update_<utc>.log`
   No new logging is added to other currently-silent scripts.

### Concurrent-edit caution

`refresh_stale_non_public_entities.py`, `reprocess_stuck_financials.py`, and
`validate_stale_pd_source.py` carry uncommitted concurrent edits. Their change is a
surgical `logs_dir()` → `logs_dir("<utility>")` (plus input default where relevant).
Implementation reads the live working-tree file and edits in place; if it detects a
conflict it flags rather than clobbers.

## Catalog sync (the dashboard already built)

- **`utilities.yaml`:** rewrite each `outputs.logs_glob` / `outputs.output_glob` from
  category → per-utility folder (e.g. `refresh_stale_entities/refresh_stale_entities_*`,
  `validate_stale_entities/stale_reconcile_*`). Add `outputs.logs_glob` for
  `delete_custom_entity` and `dynamodb_batch_update` now that they log.
  `runs.py` / `serve.py` need **no** code change — they glob relative to the `logs/`
  and `output/` roots, so subfolder-qualified globs work as-is.
- **Skills (4 `SKILL.md`):** update the "where outputs land" / output-path lines to the
  per-utility folders.
- **`README.md` + `Docs/utilities-catalog.md`:** add a short note documenting the
  `input|output|logs/<utility>/` convention.

## Migration of existing artifacts

**Merge-relevant (git-tracked):**
- `git mv "BulkUplaodFiles/Corporate_Input_File 1.csv"` and `.xlsx` →
  `input/build_opensearch_query/` (the only tracked input files that exist).
- `.gitignore`: add `input/`; keep existing ignores (`logs/`, `output/`,
  `inputfiles/`, `outputfiles/`, `BulkUplaodFiles/corporate_input_run_output/`).

**Local workspace tidy (gitignored — not part of the merge, tidies the machine and
keeps dashboard run-history working for historical runs):**
- Move existing `logs/*` into `logs/<utility>/` by filename prefix
  (`refresh_stale_entities_*` → `logs/refresh_stale_entities/`,
  `validate_stale_entities_*` → `logs/validate_stale_entities/`,
  `run_portfolio_kpis_postgres_*` → `logs/run_portfolio_kpis/`,
  `test_single_entity_refresh_*` → `logs/verify_single_entity_refresh/`, etc.),
  carrying each log's `.summary.json` sidecar with it.
- Move existing `output/stale_entities/*` into the correct per-utility output folders
  (`stale_reconcile_*` → `output/validate_stale_entities/`,
  `stale_external_ids_*` → `output/export_stale_entities/`,
  `*.snapshot.json`/`*.result.json` → `output/verify_single_entity_refresh/`).
- Remove the now-empty `inputfiles/` and `outputfiles/` directories.
- **Leave untouched** the stray non-utility files in `logs/`
  (`db_behind_api_*.txt`, `live_custom_run.out`) — not produced by any cataloged
  utility; treated as unrelated scratch.

## Error handling / edge cases

- `input_dir()` / `logs_dir(...)` create the folder on demand (like `output_dir`), so a
  first run with an empty `input/<utility>/` still works; a missing default input file
  produces the script's existing "file not found" behavior, unchanged.
- Env overrides (`EDFX_OUTPUT_FOLDER`, `KPI_LOG_FILE`) still take precedence over the
  new defaults.
- Old artifacts left in flat `logs/` / `output/<category>/` after migration: none
  should remain for cataloged utilities once moved; unrecognized files stay put.

## Verification (no test suite)

- `project_paths`: `python -c` asserting `input_dir("x")`, `logs_dir("x")`,
  `output_dir("x")` return the expected `input/x`, `logs/x`, `output/x` paths and
  create them; and that `logs_dir()` with no args still returns flat `logs/`.
- Each modified script: run with `--help` (or `--dry-run`/`--list-only` where DB-free)
  and confirm the resolved default input/output/log path prints the per-utility folder.
- Dashboard: `load_manifest()` still returns 10 utilities; start the server and confirm
  `runs.py` finds relocated logs/outputs under the new per-utility globs.
- Migration: after moving, `logs/<utility>/` and `output/<utility>/` contain the
  expected files and `inputfiles/`/`outputfiles/` are gone.

## Decisions

- **Per-script meaningful folder names**, not shared category folders — clarity for the
  team over fewer folders.
- **Migrate existing artifacts**, not going-forward-only — the user asked for a tidy
  workspace before merge.
- **Backward-compatible `logs_dir(*parts)`** so non-scope scripts are unaffected.
- **Add logs only to the two destructive tools**; other silent scripts stay silent.
