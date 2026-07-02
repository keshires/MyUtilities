# Stale Entity Reconciliation Export — Design

**Date:** 2026-07-02
**Status:** Approved
**Script:** `Day2Day_Utillites/validate_stale_entities.py` (new, standalone, read-only)

## Goal

Reconcile a stale-entity refresh run: re-run the same stale query the refresh
script (`refresh_stale_non_public_entities.py`) uses and export every entity
that **still matches** (i.e. was *not* updated by the last refresh) to a CSV,
with the `entity_data` JSON column flattened into separate columns.

> **Schema note (confirmed via probe 2026-07-02):** the JSON column is
> `entity_data` (jsonb), *not* `entity_date` as originally described. Its 30
> top-level keys match the provided sample exactly. `public.entity` also has
> `name` (text) and `as_of_date` (date), which are included as core columns.

No API calls, no SSO — pure Postgres read.

## Interface

```
python validate_stale_entities.py --entity-type custom      # default: private
    [--date-filter YYYY-MM-DD]   # default: first of current month
    [--all-entities]             # ignore the stale-date filter
    [--tenant-id <id>]           # override tenant exclusion
    [--limit N]                  # cap rows (testing)
    [--output <path>]            # default: output/stale_entities/stale_reconcile_<type>_<utc>.csv
```

## Query

Same `WHERE` clause as `stale_entities_query` (`data_type='Private'`, custom/private
`custom_id` clause, `external_id IS NOT NULL`, tenant exclusion, `updated_date IS NULL
OR < cutoff`) — but **not** `DISTINCT external_id`. Selects per-row detail:

```sql
SELECT external_id, name, tenant_id, custom_id, updated_date, as_of_date, entity_data
FROM public.entity
WHERE <same stale clause>
ORDER BY external_id
```

Streamed via an async cursor (same pattern as `iter_stale_batches`) to bound memory.
`entity_data` is handled as either `dict` or JSON `str` (guarded `json.loads`).

## CSV columns

1. **Core**: `entity_type`, `external_id`, `name`, `tenant_id`, `custom_id`,
   `updated_date`, `as_of_date`, `days_since_updated` (computed; blank if
   `updated_date` is null).
2. **Flattened `entity_date` keys** (fixed order, from sample — 29 columns):
   `found, hasPgs, isBank, peerId, country, loading, modelId, industry, ewsChange,
   pdTrigger, dataSource, pdBpsChange, hasScorecard, industryCode, isPeerDriven,
   capOneYrTTCIr, capOneYrTTCPd, peerGroupName, confidenceCode, entityLegalForm,
   hasCustomProfile, financialStmtDate, hasCustomPeerGroup, hasCustomFinancials,
   impliedRatingChange, hasAnyCustomizations, confidenceDescription,
   peerGroupPdPercentile, replacementIdentifier, industryClassification`.
3. **Overflow**: `attributes_extra_json` — JSON of any `entity_date` keys not in the
   fixed list, so nothing is silently dropped. Non-empty overflow is logged with the
   new key names.

Written with `csv.DictWriter(fieldnames=..., extrasaction="ignore")`, single streaming pass.

## Output & logging

- CSV to `output/stale_entities/` via `project_paths.output_dir`,
  default name `stale_reconcile_<type>_<utc>.csv`.
- Run log in `logs/`; final summary: rows written, count with null `updated_date`,
  count where `entity_date` was null/unparseable, count of rows using the overflow column.

## Error handling

- Missing `TESSERA_POSTGRES_*` → exit 1 with a clear message.
- `entity_date` NULL or invalid JSON → core columns written, JSON columns blank,
  counted in summary (not fatal).
- Exit 0 on success; "0 stale rows" is a valid, non-error result.

## Decisions

- One CSV row **per DB row** (not deduped per `external_id`) — shows per-tenant staleness.
- Exit 0 even when rows are found — this is a report, not a pass/fail gate.
