---
name: stale-entity-refresh
description: Use when refreshing or reconciling stale non-public (private/custom) entities, or running the monthly stale-entity refresh — finding which external ids are stale by pd_last_known_date, exporting them, submitting refreshes via the Tessera refreshEntities API, or verifying a refresh actually advanced the PD.
---

# Stale Entity Refresh

Tools live in `Day2Day_Utillites/`. Run everything from that folder with its venv
(`.\.venv\Scripts\python`), with `.env` populated. Canonical args/env for every command are in
`Day2Day_Utillites/utilities.yaml` (browse via the dashboard, bottom). Full monthly procedure:
`Day2Day_Utillites/Docs/monthly-stale-refresh-runbook.md`.

## Three corrections that matter (get these wrong and the run is invalid)

- **Measure staleness by `--stale-date-column pd_last_known_date`, NOT the default `updated_date`.**
  A refresh bumps `updated_date` even when the PD doesn't advance, so `updated_date` makes the queue
  look caught up when it isn't. `pd_last_known_date` is the true signal.
- **Exclude the deprecated giant** by setting `STALE_REFRESH_EXCLUDED_TENANTS=001aJ00000Cwqc2QAB`
  in `.env`. This also *includes* `0014000000NXtS8` (the script's built-in default excludes it).
- **One entity per request + iterate.** `refreshEntities` returns 200 but drops ~13–17% per pass.
  Re-validate and re-refresh the residual until the count plateaus.

## Monthly run (custom + private, by PD date)

Same commands every month — `--date-filter` defaults to the 1st of the current month (August
auto-targets `2026-08-01`; override with `--date-filter YYYY-MM-01`).

1. **Find stale (read-only)** — per type, writes CSV + `.summary.json`:
   `python validate_stale_entities.py --entity-type custom --stale-date-column pd_last_known_date`
   (repeat with `--entity-type private`; one tenant only: add `--tenant-id <id>`).
2. **Dry-run** (no posting, confirm count):
   `python refresh_stale_non_public_entities.py --entity-type custom --stale-date-column pd_last_known_date --one-per-request --dry-run`
3. **Live refresh** (posts to prod queue):
   `python refresh_stale_non_public_entities.py --entity-type custom --stale-date-column pd_last_known_date --one-per-request --workers 20`
   (repeat with `--entity-type private`).
4. **Re-validate after the queue settles** (repeat step 1); re-run step 3 on any residual until it plateaus.
5. **Spot-verify (optional):** `python test_single_entity_refresh.py --entity-type custom --count 10`
   — submits a few individually and polls until `pd_last_known_date` advances.

**Optional PD pre-filter** (skip futile posts): add `--pd-precheck` to the refresh command (needs
`--stale-date-column pd_last_known_date`) to post only genuine candidates — skips entities already
fresh or whose peer group already has the PD. `validate_pd_precheck.py --entity-type <t>` reports the
POST/SKIP split read-only (`public` is report-only). Peer-group PD currently uses a DB `MAX(peerId)`
fallback; the external-source resolver is a documented stub pending its endpoint.

Outputs: `output/<script>/…` (CSVs, snapshots) and `logs/<script>/…` (run log + `.summary.json`).

## PD-date rule per type
- **Custom:** PD lands on the **1st** of the month (fresh = pd_last_known_date == 1st).
- **Private:** PD lands **any day** in the current month (vendor-dependent).
- Both share the stale cutoff `pd_last_known_date < 1st-of-month`; only `--entity-type` differs.
- **Public** entities are vendor-driven — not refreshable here (report-only, planned).

## Safety
- `refresh_*` and `test_single_*` **write to prod** via Tessera. Dry-run, small `--limit`/`--count`, verify, then scale.
- `validate_*` / `export_*` are read-only Postgres queries.

## Prereqs
`.env` must have `MOODYS_SSO_USERNAME`, `MOODYS_SSO_PASSWORD`, `TESSERA_BASE_URL`, the
`TESSERA_POSTGRES_*` group, and `STALE_REFRESH_EXCLUDED_TENANTS=001aJ00000Cwqc2QAB`.

## Dashboard
```powershell
cd Day2Day_Utillites
.\.venv\Scripts\python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021
# http://127.0.0.1:8021/app/ — cards, copy-ready commands, recent run history.
```
