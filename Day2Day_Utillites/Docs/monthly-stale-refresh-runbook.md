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
- **Batch posting is the default — do NOT use `--one-per-request`.** The "Multiple Overlay Process
  Ids" bug that previously required one-per-request was fixed by PR #2564 / EDFX-28971 and deployed
  2026-07-24. Batching is ~100× fewer HTTP calls (197k → ~2k requests for a 200k custom run).
- **Keep `--workers 3` when batching.** `--workers 20` with batched payloads caused sustained HTTP
  502 gateway errors on 2026-07-24. Low workers + batching is the safe shape. (`--one-per-request`
  tolerates 20 workers because payloads are tiny — but don't use it; it's ~10 hrs vs ~6 min.)

## How `refreshEntities` actually works (verified from edfx-tessera-service source)

- **It enqueues, it does not refresh synchronously.** `POST /tesseraui/v1/refreshEntities` returns
  `"Submitted"` (HTTP 200) after putting an SQS message on the refresh queue. The real recompute +
  persist happens **downstream in the SQS consumer** (`EntityRefreshService`). So **a 200 ≠ the PD
  moved.**
- **Therefore re-validate only after the refresh queue drains** — not merely when Postgres "looks
  settled." Low yield seen minutes/hours after posting is usually the async consumer still working
  (or entities that genuinely can't advance), not failed posts.
- The service internally chunks at **5 public / 10 private / 100 custom-financials** per message —
  so a large client `--batch-size` (default 15k) just means fewer HTTP posts with the same downstream throughput.
- `force: true` (which the script sends) bypasses the service's staleness threshold and refreshes
  the named entities regardless of recency.

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

### 1b. (Optional) PD pre-check report — see what's worth refreshing / what's orphaned
```
.\.venv\Scripts\python validate_pd_precheck.py --entity-type custom   # or private / public
```
Classifies the stale set using the authoritative PD check:
- **private/custom** → `/edfx/v1/entities/pds` (custom uses `externalId-financialsProcessId`);
  if pds has no data → `/entity/v1/mapping`; empty ⇒ **orphaned** (written to a separate
  `.orphaned.csv` delete-candidate list). Buckets: `refreshable`/`current_pd` (POST),
  `no_pd`/`source_stale`/`mapped_no_pd`/`orphaned` (SKIP).
- **public** → DB-only, report-only: `public_fresh` (current-month PD + Active/null status)
  vs `public_stale`.
Needs SSO env (private/custom). Add `--limit N` to sample. Read-only — never posts.

### 2. Dry-run the refresh (no posting; confirms the count)
```
.\.venv\Scripts\python refresh_stale_non_public_entities.py --entity-type custom --stale-date-column pd_last_known_date --dry-run
```

### 3. Live refresh (posts to queue, batched)
```
.\.venv\Scripts\python refresh_stale_non_public_entities.py --entity-type custom --stale-date-column pd_last_known_date --workers 3
```
Repeat steps 2–3 with `--entity-type private`.

### 3b. Check entity_refresh_status for downstream failures and resubmit

After posting the live refresh, check the `entity_refresh_status` table for entities that
failed during downstream processing (the SQS consumer, not the HTTP submission itself).
These failures are independent of the stale-date filter — an entity may have received a 200
from `refreshEntities` but still failed inside `EntityRefreshService`.

```powershell
# Report only — see what failed since the start of the month
.\.venv\Scripts\python monitor_entity_refresh_status.py --source Scoring --since 2026-08-01

# Resubmit failures (dry-run first)
.\.venv\Scripts\python monitor_entity_refresh_status.py --source Scoring --since 2026-08-01 --resubmit --dry-run

# Resubmit failures (live)
.\.venv\Scripts\python monitor_entity_refresh_status.py --source Scoring --since 2026-08-01 --resubmit --workers 3
```

Tip: use `--since` matching the current month's 1st (same date as `--date-filter` in the refresh
run). Use `--correlation-id <id>` to scope to a specific batch from the refresh log.
The CSV output shows `entity_type_resolved` (custom/private/not_found) and the action taken.

### 4. Re-validate & iterate
After the queue settles (allow time — async), re-run step 1. If a residual remains, re-run step 3
and step 3b on it. Repeat until the count plateaus.

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
