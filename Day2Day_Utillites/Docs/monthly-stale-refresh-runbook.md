# Monthly Stale Non-Public Entity Refresh — Runbook

Repeatable monthly process to find and refresh stale **custom** and **private** entities
by their **PD date**. Run from `Day2Day_Utillites` in PowerShell with `.env` populated.
The same commands work every month unchanged — `--date-filter` defaults to the **1st of the
current month**, so running them in August automatically targets `2026-08-01`.

## Why these specific flags (hard-won)

- **Measure staleness by `pd_last_known_date`, NOT `updated_date`.** A refresh bumps
  `updated_date` even when the PD does not advance, so an `updated_date` filter makes the queue
  look "caught up" when it isn't. `pd_last_known_date` is the true signal.
- **Exclude the deprecated giant `001aJ00000Cwqc2QAB`** (unsupported, cleanup pending). Setting
  `STALE_REFRESH_EXCLUDED_TENANTS` to it also means tenant `0014000000NXtS8` is *included*
  (the script's built-in default would otherwise exclude NXtS8).
- **One entity per request + iterate.** The Tessera `refreshEntities` path is lossy: every submit
  returns HTTP 200 but ~13–17% are not processed per pass. Re-run on the residual until the count
  plateaus.

## PD-date rule per entity type

| Type | PD lands on | "Fresh" means | Stale (in scope) |
|------|-------------|---------------|------------------|
| **Custom** | 1st of the month (always) | `pd_last_known_date` == 1st of current month | `< 1st-of-month` or null |
| **Private** | any day in current month (vendor) | `pd_last_known_date` anywhere in current month | `< 1st-of-month` or null |

Both use the same stale cutoff (`pd_last_known_date < 1st-of-month`); only `--entity-type` differs.

## One-time setup

Add to `.env`:
```
STALE_REFRESH_EXCLUDED_TENANTS=001aJ00000Cwqc2QAB
```
Ensure `.env` also has `TESSERA_POSTGRES_*` (validate) and `MOODYS_SSO_USERNAME` /
`MOODYS_SSO_PASSWORD` / `TESSERA_BASE_URL` (refresh).

## The monthly steps

### 1. Look for stale entities (read-only)
```
.\.venv\Scripts\python validate_stale_entities.py --entity-type custom --stale-date-column pd_last_known_date
```
```
.\.venv\Scripts\python validate_stale_entities.py --entity-type private --stale-date-column pd_last_known_date
```
Writes a CSV under `output\validate_stale_entities\` + a `.summary.json` (with the count) under
`logs\validate_stale_entities\`. Restrict to one tenant with `--tenant-id <id>`.

### 1b. (Optional) PD pre-check report — see what's worth refreshing
```
.\.venv\Scripts\python validate_pd_precheck.py --entity-type custom
```
Classifies the stale set POST vs SKIP (already-fresh / matches peer-group PD), using each
entity's PD and its peer group's PD. Add `--pd-precheck` to the refresh command (step 3) to
post only the POST candidates and skip futile ones. `public` is report-only.

### 2. Dry-run the refresh (no posting; confirms the count)
```
.\.venv\Scripts\python refresh_stale_non_public_entities.py --entity-type custom --stale-date-column pd_last_known_date --one-per-request --dry-run
```

### 3. Live refresh (posts to queue), one entity per request
```
.\.venv\Scripts\python refresh_stale_non_public_entities.py --entity-type custom --stale-date-column pd_last_known_date --one-per-request --workers 20
```
Repeat steps 2–3 with `--entity-type private`.

### 4. Re-validate & iterate
After the queue settles (allow time — async), re-run step 1. If a residual remains, re-run step 3
on it. Repeat until the count plateaus.

### 5. Spot-verify (optional)
```
.\.venv\Scripts\python test_single_entity_refresh.py --entity-type custom --count 10
```
Submits a few individually and polls until `pd_last_known_date` advances.

## Explicit month override (optional)
`--date-filter` defaults to the 1st of the current month. To target a specific month:
```
... --date-filter 2026-08-01
```

## Not yet automated
- **Public** entities (report-only, vendor-driven) and the **peer-group-aware pre-check**
  (skip entities whose peer group already has the PD; don't post futile ones) are a planned
  feature, not in these commands yet.
