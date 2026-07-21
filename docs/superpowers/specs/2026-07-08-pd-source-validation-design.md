# PD-source validation for leftover stale entities

**Date:** 2026-07-08
**Status:** Implemented

## Problem

After refreshing, a residual set of custom entities keeps matching the stale test
(`pd_last_known_date < first-of-month`, financials ≤ 3 yr). We needed to know, per
entity, whether it is **already dated to the maximum its source data supports**
(nothing more to do) or **genuinely behind** what the model can produce (worth a
refresh).

## Approach — `validate_stale_pd_source.py`

1. Select the leftover stale entities (same predicates as the refresh), joined to
   `entity_custom_data` for `financials_process_id` (1:1 with entity).
2. Build `entityId = {external_id}-{financials_process_id}` and POST batches to
   `/edfx/v1/entities/pds` (`asyncResponse=false`, details off), reading the latest
   `asOfDate` the model returns. Responses are keyed by the full `entityId`, since
   one `financials_process_id` may map to multiple entities.
3. Compare API `asOfDate` with DB `pd_last_known_date` → verdict:
   - `at_source_max` — equal (dated to the source max; no action)
   - `db_behind_api` — API newer than DB (real gap; refresh helps)
   - `db_ahead_api` — DB newer (rare)
   - `no_api_data` — API returned no PD (usually Failed/Aborted financials)
   - `no_process_id_refresh_submitted` — NULL `financials_process_id`; submitted for
     refresh to obtain a new process id
4. Write a per-entity CSV (DB fields + API fields + verdict) and a verdict summary.

## Options

`--entity-type`, `--stale-date-column`, `--financial-max-age-years`, `--date-filter`,
`--tenant-id`, `--limit`, `--api-batch-size` (default 50), `--api-pause` (default
0.25 s, to avoid overloading the API), `--no-refresh-missing`, `--dry-run`.

## First run (custom, 2026-07-08)

1,860 entities: 1,387 `at_source_max`, 112 `db_behind_api`, 304 `no_api_data`
(Failed/Aborted financials), 57 NULL-process-id (submitted for refresh). The 112
`db_behind_api` were then re-submitted one-per-request and are expected to advance
to 2026-07-01.

## Reuse

Auth (`TokenManager`), retry/backoff, and the stale-query building blocks are
imported from `refresh_stale_non_public_entities.py`. Read-only on the DB; the only
writes are the refresh submissions for NULL-process-id rows (skipped under
`--dry-run` / `--no-refresh-missing`).

## Addendum (2026-07-09): peer-aware validation — the client "Calculation Date"

The client report `/tesseraui/v2/portfolio/{id}/download` is produced by the
Postgres function `export_portfolio` → `vw_exportable_portfolio_data`, which maps
**`pd_last_known_date` → "Calculation Date"**. Clients expect July; many custom
entities showed an earlier month.

Root cause: those entities are **peer-driven** (`isPeerDriven=true`, confidence
`PN-P…`). The refresh computes their PD via EDFX `/entities/pds` **with the
`peerId`** and the effective entityId (`get_effective_entity_id`), and the
peer-driven PD is **bounded by the peer group's latest metric month** (stuck at
2025-12-01 for the affected groups). The DB `pd_last_known_date` correctly equals
that peer-bounded value — the refresh is not at fault.

The first version of this tool queried `/entities/pds` **without** `peerId`, so it
compared peer-driven entities against the *standalone* (newer) PD and produced
false `db_behind_api` verdicts (163 of them). Fix: replicate the refresh's request
exactly — effective entityId + `peerId` + `endDate=today` + `modelDetail`. After
the fix, genuine `db_behind_api` dropped 163 → 3; 1,496/1,845 are `at_source_max`.

New outputs: per-entity CSV now carries `is_peer_driven`, `peer_group_id`,
`peer_group_name`, `confidence_code`; plus a companion **peer-group CSV**
(`stale_peer_groups_*.csv`) listing the peer groups whose stale members need
reprocessing, with affected-entity counts and tenants.

## Peer-group reprocess (investigation)

There is **no tessera-side trigger** to reprocess a peer group's PD. Tessera only
**reads** peer metrics from EDFX (`client_edfx_global.get_peers_metrics` /
`get_peers_percentile`); the peer group's `as_of_date` is the newest metric EDFX
returns. Advancing the peer-driven PD to July requires the **upstream EDFX peers/
percentile pipeline** to compute current-month metrics for the affected peer groups
(46 groups, all currently capped at 2025-12-01). This is owned outside
edfx-tessera-service.
