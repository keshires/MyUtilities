# PD-Aware Pre-Submission Validation — Design Spec

**Date:** 2026-07-15
**Status:** Approved design, ready for implementation planning
**Author:** Sham Sunder Keshireddy (with Claude)

---

## 1. Purpose

Before posting a stale non-public entity to the Tessera `refreshEntities` queue, decide whether a
refresh is actually warranted — skipping entities that already carry a current PD, or whose peer
group already has the latest PD, or whose peer group has no latest PD (so a refresh can't help).
This avoids pointless queue posts and DB churn, and produces a categorized report of the stale
population for custom, private, and public entities.

**Problem it solves:** we currently post the entire `pd_last_known_date`-stale set. Analysis of one
month showed a large fraction of posts are futile (peer-driven entities matching a stale group, or
entities whose peer group is itself stale). The queue is expensive; the pre-check filters it.

---

## 2. Key decisions (resolved during brainstorming)

| Decision | Choice |
|----------|--------|
| Staleness signal | `pd_last_known_date` (never `updated_date`) |
| "Latest PD exists" signal | Entity's own current PD **and** peer-group PD (fallback) |
| Peer-driven rule | Compare entity PD date to peer-group PD date: **equal → SKIP**, **entity older → POST** |
| Peer-group PD source | **External source/API** (behind a resolver interface); DB-derived `MAX(pd_last_known_date)` over `peerId` as offline/fallback |
| Delivery | Shared classifier module used by **both** a standalone report **and** an opt-in refresh pre-filter |
| Entity types | Custom + private are refreshable; **public is report-only** (vendor-driven, never posted) |
| PD-date granularity | **Custom = exact 1st-of-month**; **private/public = any day in current month** |
| Target month | First-of-current-month (matches the stale cutoff; monthly cadence) |

---

## 3. Entity-type model

| Type | Identity (`public.entity`) | Postable? | "Has current PD" (fresh) |
|------|----------------------------|-----------|--------------------------|
| Custom | `data_type='Private'`, `custom_id IS NOT NULL` | yes | `pd_last_known_date == first-of-month` (exact) |
| Private | `data_type='Private'`, `custom_id IS NULL` | yes | `pd_last_known_date` in current month (`>= first-of-month`) |
| Public | `data_type <> 'Private'` (confirm exact values in impl) | **no** | `pd_last_known_date` in current month |

Stale (in scope) for all types: `pd_last_known_date IS NULL OR pd_last_known_date < first-of-month`,
with the existing `financialStmtDate <= N years` gate and tenant-exclusion
(`STALE_REFRESH_EXCLUDED_TENANTS`, incl. deprecated giant `001aJ00000Cwqc2QAB`).

---

## 4. Components

### 4.1 `pd_precheck.py` (new shared module)
Pure-logic core, no DB/network of its own.

- **`month_start(today) -> date`** — first of the current month.
- **`is_pd_current(entity_type, pd_date, ref_month_start) -> bool`**
  - custom: `pd_date is not None and pd_date >= ref_month_start` (custom PDs land on the 1st).
  - private/public: `pd_date is not None and pd_date >= ref_month_start`.
  - *(Same threshold today; kept type-parameterized so custom can tighten to exact-1st if needed.)*
- **`pd_periods_match(entity_type, entity_pd, group_pd) -> bool`**
  - custom: exact date equality (`entity_pd == group_pd`).
  - private/public: same calendar month (`(y,m)` equal).
- **`classify(*, entity_type, is_peer_driven, entity_pd, group_pd, ref_month_start) -> Classification`**
  returning `category` + `action` (`POST`/`SKIP`) + `reason`:

  | Condition | category | action |
  |-----------|----------|--------|
  | `is_pd_current(entity_pd)` | `already_fresh` | SKIP |
  | not peer-driven | `standalone` | POST |
  | peer-driven, `group_pd is None` | `peer_unknown` | POST |
  | peer-driven, `pd_periods_match(entity_pd, group_pd)` | `matches_group` | SKIP |
  | peer-driven, entity older than group | `peer_lag` (+ `group_fresh`/`group_stale` sub-flag via `is_pd_current(group_pd)`) | POST |

- **`PeerGroupPdResolver`** (ABC): `resolve(peer_ids: Iterable[str]) -> dict[str, date | None]`.
  - **`DbMaxPeerGroupPdResolver`** — `MAX(pd_last_known_date)` grouped by `entity_data->>'peerId'`;
    used offline/tests and as the fallback when the API is unavailable.
  - **`ApiPeerGroupPdResolver`** — queries the external source for each peer group's latest PD date.
    **Endpoint + auth are the one open integration point** (§8); until wired it raises a clear
    `NotImplementedError` and callers fall back to the DB resolver with a logged warning.

### 4.2 `validate_pd_precheck.py` (new report script)
Read-only. For a chosen `--entity-type` in {custom, private, public}:
1. Query the stale set (reuse the existing stale predicate + `pd_last_known_date` column).
2. Batch-resolve peer-group PD dates for the distinct `peerId`s (resolver, default DB fallback;
   `--resolver api` opts into the external source once wired).
3. `classify` each entity.
4. Write CSV (all stale entities + `category`/`action`/`reason` + peer fields + `financialStmtDate`)
   to `output/validate_pd_precheck/…` and a `.summary.json` to `logs/validate_pd_precheck/…`.

Summary JSON per type: `stale_found`, `expected_to_refresh` (POST count; 0 for public),
`skipped{already_fresh, matches_group}`, `post{standalone, peer_lag_fresh, peer_lag_stale, peer_unknown}`,
`null_pd`, and a per-tenant rollup. `refreshed` vs `pending` are derived by running the report before
and after a refresh (the `stale_found` delta), so no extra state is stored.

### 4.3 `refresh_stale_non_public_entities.py` — `--pd-precheck` flag (opt-in)
When set: after resolving the stale set, run the classifier (using the resolver) and submit only
`action == POST` entities; SKIP entities are counted by reason and written into the run
`.summary.json` (`precheck_skipped{…}`). No behavior change when the flag is absent. Public type is
rejected for refresh (report-only).

---

## 5. Data flow

```
stale query (pd_last_known_date < month_start, financials, tenant-exclusion)
        │  rows: external_id, tenant_id, pd_last_known_date, entity_data(peerId,isPeerDriven), type
        ▼
distinct peerIds ──► PeerGroupPdResolver.resolve() ──► {peerId: group_pd_date}
        │                                                        │
        └───────────────► classify(entity, group_pd) ◄──────────┘
                                   │
                 ┌─────────────────┴──────────────────┐
                 ▼                                     ▼
        validate_pd_precheck (report CSV+JSON)   refresh --pd-precheck (POST subset only)
```

---

## 6. Error handling
- Resolver API failure → log warning, fall back to `DbMaxPeerGroupPdResolver` for that batch; record
  `resolver=fallback` in the summary so the run is auditable.
- Missing/unparseable `peerId` or `pd_last_known_date` → treated as `peer_unknown`/stale (POST), never crashes.
- `validate_*` is read-only; `refresh --pd-precheck` keeps existing dry-run/retry/one-per-request safety.

## 7. Testing
- **Classifier + helpers:** pure unit tests (pytest) — one case per category, plus custom-vs-private
  date-granularity cases and null-PD cases. Fully offline.
- **DbMaxPeerGroupPdResolver:** unit test with an injected fake fetch (no live DB).
- **Report script:** test the classification-to-summary aggregation with a fake resolver + in-memory rows.
- **Refresh integration:** test that `--pd-precheck` filters the POST set (fake resolver + classifier),
  with `submit_refresh_batch` monkeypatched so nothing hits prod.
- pytest added as a dev dependency (`requirements-dev.txt`); tests live in `Day2Day_Utillites/tests/`.

## 8. Open items / assumptions
- **External peer-group PD endpoint + auth** — the authoritative source the user named. `ApiPeerGroupPdResolver`
  isolates it; must be supplied to complete that resolver. Until then the DB fallback runs (documented, warned).
- **`data_type` value(s) for "public"** — confirm during implementation (probe distinct `data_type`).
- **`peerId` scope** assumed global (across tenants) for the DB resolver.
- Target month = first-of-current-month; PDs are monthly-dated in the data.

## 9. Out of scope (YAGNI)
- Auto-refreshing peer groups / driver entities (only classify + post individual entities).
- Changing the existing `updated_date` behavior or other utilities.
- Any public-entity posting (report-only, always).

---

## Addendum (2026-07-16) — authoritative pds/mapping/orphan resolver

The §8 external resolver is now defined. The peer-group `MAX(peerId)` heuristic is
superseded for the POST/SKIP decision by the **authoritative PD check**:

- **private** → `POST /edfx/v1/entities/pds` with `entityId = external_id`.
- **custom** → same endpoint with `entityId = "<external_id>-<financials_process_id>"`
  (`financials_process_id` from `public.entity_custom_data`, joined on `external_id`).
- Response per entity: `asOfDate` (+ `pd` when computable) or a `message` ("No data found").
- **pds "no data"** → `POST /entity/v1/mapping` (`queries` by `entityId` and
  `customEntityIdentifier`). Empty response ⇒ **orphaned** (delete-candidate; exported to
  a separate `.orphaned.csv`). Confirmed by the operator: not-in-pds-and-not-in-mapping is
  orphaned even if a stale DB `pd_last_known_date` row lingers.
- **public** → DB-only: fresh if `pd_last_known_date` is in the current month **and**
  `legal_status` is null/Active; report-only (never posted).

Classification categories (`pd_precheck.classify_status` / `classify_public`):
`refreshable`/`current_pd` → POST; `no_pd`, `source_stale`, `mapped_no_pd`, `orphaned`,
`public_fresh`, `public_stale`, `public_invalid_status` → SKIP (public never posts).

Currency nuance: for **custom**, pds `asOfDate` is the financials-statement date (not the
publication date), so a computable `pd` (not `asOfDate`) is the POST signal; for **private**,
`asOfDate` in the current month is the signal.

Resolver (`PdMappingResolver`) takes injected `pds_post_batch` + `mapping_lookup`, so the pure
logic is unit-tested offline; the scripts supply SSO-authenticated batched implementations.
Mapping "found" is detected by the id appearing in the batched response body.

Building blocks retained: `DbMaxPeerGroupPdResolver` (offline/tests) and the peer-group
classifier remain in `pd_precheck.py` as reusable, tested code.

### Refresh mechanics — verified against edfx-tessera-service source (2026-07-18)

- `POST /tesseraui/v1/refreshEntities` is **enqueue-only**: it returns `"Submitted"` (200) after
  putting an SQS message on the refresh queue; the recompute + persist happen **downstream in the
  SQS consumer** (`EntityRefreshService`). **A 200 does not mean the PD advanced.** Consequence for
  this design: re-validation must run **after the refresh queue drains**, not just when Postgres
  looks settled; mid-processing low yield is expected.
- `refreshEntities` is a **batch** endpoint (internally chunks 5 public / 10 private / 100
  custom-financials). `--one-per-request` was a temporary workaround for a batch bug; the fix
  (PR #2564 / EDFX-28971) deployed to prod 2026-07-24 — batching is now the default. Keep
  `--workers 3` with batching; 20 workers + batched payloads caused HTTP 502 gateway errors.
- Eligibility rules `pd_last_known_date` staleness and `financialStmtDate ≤3y` are **intentional
  homegrown validations** (the latter matches unmerged branch EDFX-27547); the service's own
  scheduler uses `as_of_date`/`updated_date` hour-thresholds instead. Public entities are refreshed
  by a **separate daily batch** (`edfx-portfolio-refresh-batch`, direct CreditEdge SQL → Postgres),
  never via `refreshEntities` — so public stays report-only here. Full mechanics in memory
  `edfx-refresh-mechanics`.
