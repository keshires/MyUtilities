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
   → `output/export_stale_entities/stale_external_ids_<utc>.csv`.

2. **Reconcile** — dump every still-stale entity with `entity_data` flattened (read-only):
   `python validate_stale_entities.py --entity-type custom`
   → `output/validate_stale_entities/stale_reconcile_<type>_<utc>.csv` + a `.summary.json`
   in `logs/validate_stale_entities/`.

3. **Refresh** — submit to Tessera. **Always dry-run first**:
   `python refresh_stale_non_public_entities.py --entity-type custom --dry-run`
   then drop `--dry-run` to submit. Key flags: `--stale-date-column {updated_date,pd_last_known_date}`,
   `--batch-size`, `--workers`, `--max-retries`, `--resume-from-batch`, `--limit`, `--tenant-id`.
   → run log + `.summary.json` in `logs/refresh_stale_entities/`.

4. **Verify** a handful end-to-end:
   `python test_single_entity_refresh.py --entity-type custom --count 10`
   polls until `pd_last_known_date` advances.
   → run log in `logs/verify_single_entity_refresh/`, snapshots in `output/verify_single_entity_refresh/`.

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
