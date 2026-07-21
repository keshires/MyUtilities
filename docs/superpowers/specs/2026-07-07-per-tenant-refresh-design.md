# Per-tenant refresh for refresh_stale_non_public_entities.py

**Date:** 2026-07-07
**Status:** Approved

## Goal

Let the stale-entity refresh run tenant-by-tenant, while always honoring the
excluded-tenant list. Keep an easy single-tenant path.

## Flags

- `--per-tenant` — discover every tenant with stale entities (minus excluded),
  then run the refresh independently for each: per-tenant count, plan, batches,
  and summary entry, plus an aggregate summary.
- `--tenant-id X` (existing) — single-tenant run; now also honors exclusion (a
  named excluded tenant is refused instead of overriding exclusion).
- `--per-tenant` and `--tenant-id` are mutually exclusive.

## Exclusion (always wins)

- Excluded tenants are removed from `--per-tenant` discovery.
- A `--tenant-id` in the excluded list is refused with a clear message.
- The default "all tenants" path already excludes.

## Structure

- `TENANTS_QUERY_BASE` + `discover_tenants(...)`:
  `SELECT DISTINCT tenant_id ... <custom/financial/stale predicates>
   AND tenant_id <> ALL($2::text[]) ORDER BY tenant_id`.
- Refactor the count → plan → process → summary block in `main` into
  `execute_refresh(scope_tenant_id, ...)` returning a per-scope summary dict.
  All three paths (all / single / per-tenant loop) reuse it. One SSO auth and
  HTTP session are shared across tenants.
- Summary JSON: `{ "mode": "all|single|per-tenant", "tenants": [ ... ],
  "totals": { batches_ok, batches_failed, stale_entities_found, ... } }`.

## Edge cases

- `--per-tenant` + `--resume-from-batch` → error (batch numbering resets per
  tenant).
- `--per-tenant` + `--limit` → `--limit` caps entities **per tenant** (testing).
- Tenants with 0 stale entities are skipped.

## Out of scope

`validate_stale_entities.py` and `test_single_entity_refresh.py` keep their
existing single `--tenant-id` support; no per-tenant iteration added there.
