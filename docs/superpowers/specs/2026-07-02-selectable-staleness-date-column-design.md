# Selectable staleness date column for refresh_stale_non_public_entities.py

**Date:** 2026-07-02
**Status:** Approved

## Goal

Let the stale-entity refresh job compare against `pd_last_known_date` as an
alternative to `updated_date`, selectable per-run via a flag. Default behavior
is unchanged (the monthly job keeps using `updated_date`).

## Interface

- New CLI arg: `--stale-date-column {updated_date,pd_last_known_date}`.
- Resolution order: `--stale-date-column` arg > `STALE_REFRESH_STALE_DATE_COLUMN`
  env var > default `updated_date`.
- The value is validated against a fixed allow-list (`STALE_DATE_COLUMNS`), so it
  is safe to interpolate into SQL. An invalid value raises `SystemExit` with the
  valid choices, mirroring `resolve_entity_mode`.
- `--all-entities` still overrides the stale filter entirely; the column only
  names the field the `$1` cutoff compares against.

## Changes

1. **Clause builder.** Replace the hardcoded `DATE_CLAUSE_STALE` (currently
   naming `updated_date`) with `stale_date_clause(column) -> str` that emits:

   ```sql
   AND (
           {col} IS NULL
           OR {col} < $1::timestamp
         )
   ```

   Same NULL-as-stale semantics as today, parameterized on the column name.

2. **Query builders.** `stale_entities_query()` and
   `stale_entities_count_query()` take a `stale_date_column` param and pass it
   into the clause.

3. **Thread through.** `count_stale_external_ids()`, `iter_stale_batches()`, and
   `process_batches()` accept and forward `stale_date_column` (they already
   thread `date_filter`).

4. **CLI + resolution.** Add the arg in `parse_args`; resolve arg/env/default in
   `main` via a `resolve_stale_date_column()` helper.

5. **Observability.**
   - Line ~884 log changes from a hardcoded `"Date filter (updated_date <):"` to
     reflect the chosen column, e.g. `"Stale cutoff (pd_last_known_date <): ..."`.
   - Add `stale_date_column` to the run-summary JSON.
   - Update the module docstring so it notes the selectable column.

## NULL handling

`{col} IS NULL OR {col} < cutoff` — rows with no value in the chosen column are
treated as stale (included), matching current `updated_date` behavior for both
columns.

## Testing

No test suite exists for this script. Verification: run `--dry-run` for each
column and confirm the SQL query logged at startup shows the correct column and
clause.

## Addendum (2026-07-02): retry-with-backoff on 5xx

A live run surfaced repeated HTTP 502 (Cloudflare gateway) failures on
`refreshEntities`; batch size was not the cause. Added transient-error
resilience to `submit_refresh_batch`:

- New `--max-retries N` arg (env `STALE_REFRESH_MAX_RETRIES`, default 4; `0`
  disables). Retries HTTP `{429, 500, 502, 503, 504}` and network
  (`requests.RequestException`) errors with exponential backoff
  (`2 * 2^(n-1)` s, capped at 30 s, +≤25% jitter) via `retry_backoff_seconds`.
- The existing 401 handling is preserved as a one-shot token refresh and does
  **not** consume the backoff-retry budget.
- `max_retries` threaded through `process_batches`; logged at startup and
  recorded in the run-summary JSON.

## Addendum (2026-07-07): financialStmtDate business filter

An experiment (submitting the top-10 stale custom entities individually) showed
that even one-per-request refreshes advanced `pd_last_known_date` for only 1/10,
while `updated_date` moved for all 10. Root cause: `pd_last_known_date` can only
advance to the latest month the model can compute a PD for, which is gated by the
entity's latest financial statement. Entities whose `financialStmtDate` is older
than ~3 years cannot advance regardless of how often they are refreshed.

Business rule adopted: **do not refresh an entity whose `financialStmtDate` is
older than N years** (default 3). Impact on the custom stale set (pd column):
123,986 → 9,318 (≈92% were data-limited).

- New clause `financial_stmt_clause(max_age_years)` — keeps rows where
  `financialStmtDate` is NULL/empty or `>= NOW() - INTERVAL 'N years'`; `0`
  disables. Added to both count and select query bases.
- New `--financial-max-age-years N` (env `STALE_REFRESH_FINANCIAL_MAX_AGE_YEARS`,
  default 3) in the refresh script, threaded through count/iter/process, logged
  and recorded in the summary. Applies to both `custom` and `private`.
- The same filter and a matching `--stale-date-column` option were added to
  `test_single_entity_refresh.py` (single-request experiment, now supports
  `--entity-type`) and `validate_stale_entities.py` (reconciliation export, which
  also now emits a `pd_last_known_date` column) so all three tools select the
  same population.

