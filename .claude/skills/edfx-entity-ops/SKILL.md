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
Runs now log to `logs/delete_custom_entity/`.

## Check process statuses (read-only, .env-configured)
`python EDFX_ProcessStatus.py`
Configure the run via `.env` (`MOODYS_SSO_*`, `EDFX_BASE_URL`, `EDFX_OUTPUT_FOLDER`,
`TESSERA_POSTGRES_*`). → multi-sheet Excel in `output/edfx_process_status/`.

## Build OpenSearch queries from a CSV (local only)
`python build_opensearch_entity_query_from_csv.py --csv <file.csv> --output-dir queries`
Reads a `companyIdentifier` column; writes full + chunked `_search` JSON and a queries
payload under `output/build_opensearch_query/`. Use `--distinct-count` to inspect counts
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
