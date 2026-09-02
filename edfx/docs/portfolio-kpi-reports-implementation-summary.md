# Portfolio KPI Reports — Optimization + Multi-Env: Implementation Summary

**Merged to `main`:** merge commit `1809160` (local; not yet pushed at time of writing)
**Feature branch:** `Day2Day_StaleEntitiesRefresh`
**Feature commit range:** `5ba61bd..757cd28` (19 commits)
**Spec:** [docs/superpowers/specs/2026-07-13-portfolio-kpi-refresh-reports-optimization-design.md](../../docs/superpowers/specs/2026-07-13-portfolio-kpi-refresh-reports-optimization-design.md)
**Plan:** [docs/superpowers/plans/2026-07-13-portfolio-kpi-refresh-reports-optimization.md](../../docs/superpowers/plans/2026-07-13-portfolio-kpi-refresh-reports-optimization.md)

> Scope note: the merge commit `1809160` carried the whole 81-commit branch into `main`,
> which also includes unrelated work from other sessions (the per-utility I/O standardization
> "PLAN 2", and the PD pre-check validation suite). **This document covers only the
> Portfolio KPI reports feature** built in this effort — the 19 commits listed at the end.

---

## 1. What this delivers

The read-only reporting tool for `public.portfolio_kpi_update_log` was made **fast on
current data volume**, gained **four new report shapes** (including two 2-D pivots), and
can now run against **CI / QA / STG** environments — all without changing the read-only
guarantee.

Three things a user gets that they didn't have before:

1. Running the full report set no longer re-scans the (large, partitioned) table once per
   report — it scans once, then every report reads from cheap in-memory temp tables.
2. New reports answer the operational questions directly:
   - **Entities refreshed per day, per source, per status** (`entities_by_day_source_status`)
   - **Portfolios refreshed per day, per source, per status** (`portfolios_by_day_source_status`)
   - **How many times each entity was refreshed, by source** — 2-D pivot (`entity_by_source`)
   - **How many times each (portfolio, entity) pair was refreshed, by source** — 2-D pivot (`portfolio_entity_source`)
3. `--env qa` (or `ci`/`stg`/`prod`) picks up per-environment DB credentials.

---

## 2. Why it was slow (the problem this solves)

`public.portfolio_kpi_update_log` is `PARTITION BY RANGE (message_created_at)` and has
grown large. The old per-report queries each:

1. **Re-extracted `entity_refresh_message->>'source'` on every row.** The only JSONB index
   is a GIN index, which accelerates containment (`@>`) — it does nothing for `->>` key
   extraction. So `source` was parsed out of JSONB for every row, in every query, for both
   `WHERE` and `GROUP BY`.
2. **Re-scanned the windowed slice once per report.** Running the whole set meant ~12
   independent partition scans, each repeating the JSONB extraction and (for entity reports)
   the array `unnest`.
3. Compounded that with `COUNT(DISTINCT …)` and `unnest LATERAL`.

The window filter (`message_created_at >= start AND < end`) was already good — it enables
partition pruning — and is preserved exactly.

---

## 3. Architecture — "extract once, aggregate many"

The runner now builds **two session `TEMP` tables once per run** (after setting the window
params, before any report), then every report reads from them. One base-table scan + one
unnest replaces ~12 windowed scans.

### `tmp_kpi_window`
The `message_created_at`-windowed slice (partition-pruned), materialized once with:
- `source` = `COALESCE(entity_refresh_message->>'source', '(null)')` extracted to a **plain
  text column** (JSONB parsed once, not per report),
- `"group"` extracted, `day = date_trunc('day', message_created_at)::date`,
- `process_seconds_computed` / `queue_wait_seconds` precomputed with NULL-guards,
- plus `status`, `portfolio_id`, timestamps, `duration_seconds`,
  `triggering_entity_external_ids`, and the raw `entity_refresh_message` (for slow-detail rows).

Indexed on `(source)`, `(day)`, `(status)`, then `ANALYZE`d.

### `tmp_kpi_entity`
`tmp_kpi_window` with `triggering_entity_external_ids` pre-`unnest`ed — one row per entity
trigger: `(day, portfolio_id, source, status, entity_id)`. Indexed on `(source)`, `(day)`,
`(entity_id)`, `(portfolio_id)`, then `ANALYZE`d.

### `--source` scoping
When `--source` is passed, the filter is applied **once, when the temp tables are built**, so
every report (including `status` and `hourly_by_status`, which previously ignored it) is
scoped consistently to that source.

---

## 4. Full report catalog

The SQL file [`Docs/portfolio-kpi-metrics.sql`](portfolio-kpi-metrics.sql) is organized as one
`-- SETUP: build_temp` block plus 16 `-- REPORT:` blocks. The Python runner maps friendly
CLI `--report` aliases to those markers.

| CLI `--report` | SQL marker | What it measures |
|----------------|-----------|------------------|
| `daily` | `daily_totals_source` | Message count per day, per source |
| `hourly` | `hourly_totals` | Received vs processed per hour, per source |
| `hourly_by_status` | `hourly_by_status` | Received vs processed per hour, per status |
| `status` | `status_summary` | Row counts by status |
| `source_update_totals` | `source_update_totals` | Total updates + distinct portfolios per source |
| `portfolio_updates_by_source` | `portfolio_updates_by_source` | Update count per portfolio, per source |
| `portfolio_update_totals` | `portfolio_update_totals` | Total update count per portfolio |
| `entity_counts` | `triggering_entity_counts` | Per-entity trigger counts, by source (large) |
| `entity_source_totals` | `entity_source_totals` | Entity trigger totals per source |
| `entities_by_day` | `triggering_entity_counts_by_day` | Entity triggers per day, per source |
| `entities_by_day_source_status` ★ | `entities_by_day_source_status` | **#1** entity triggers per day / source / status |
| `portfolios_by_day_source_status` ★ | `portfolios_by_day_source_status` | **#2** portfolio refreshes per day / source / status |
| `entity_by_source` ★ | `entity_by_source` | **#3a** 2-D pivot: entity × source |
| `portfolio_entity_source` ★ | `portfolio_entity_source` | **#3b** 2-D pivot: (portfolio, entity) × source |
| `slow` | `slow_global` | Completed jobs slower than global P95 |
| `slow_by_source` | `slow_by_source` | Slow relative to per-source P95 |
| `all` | — | Runs the aggregate set only (see below) |

★ = new in this feature.

**`--report all`** runs the aggregate (small) reports only:
`daily, hourly, hourly_by_status, status, source_update_totals, entity_source_totals,
entities_by_day, entities_by_day_source_status, portfolios_by_day_source_status`.
It deliberately **excludes** the two slow-detail reports, the two large pivots, and the
large per-entity `triggering_entity_counts` (run those explicitly).

### The two 2-D pivots
Pivots are built in **Python** (`pivot_rows`) rather than SQL `crosstab`, so source columns
are discovered dynamically (no `tablefunc` dependency). The SQL returns long form
(`… , source, refresh_count`); Python produces a wide table with one column per source, a
`total` column, rows sorted by `total` DESC then index columns ASC (natural, not string,
order).

---

## 5. CLI surface

```
python portfolio_kpi_metrics_postgres.py \
  --start "2026-06-05 00:00:00" --end "2026-06-30 23:59:00" \
  --report <name> \
  [--env qa] [--source "Custom Financials"] [--top 50] [--export-csv name.csv]
```

| Flag | Behavior |
|------|----------|
| `--start` / `--end` | Window bounds (`--start` inclusive, `--end` exclusive). Drives partition pruning. |
| `--report` | One of the aliases above, or `all`. |
| `--source NAME` | **Scopes the whole run** (applied at temp-table build). |
| `--top N` | For the two pivots: caps rows **printed to stdout**; the CSV export always keeps **all** rows. |
| `--env NAME` | Loads `.env.<env>` ahead of base `.env`. Defaults from `KPI_ENV`. |
| `--export-csv PATH` | One CSV per report (filename gets a `_<marker>` suffix). Relative paths → `output/portfolio_kpi_metrics/`. |

---

## 6. Multi-environment support

- `--env {ci,qa,stg,prod}` (any name accepted) loads `.env.<env>`.
- **Precedence:** real OS environment variables win, then `.env.<env>`, then base `.env`
  fills gaps (implemented with `python-dotenv` `override=False`, env-file loaded before base).
- A missing `.env.<env>` is a **warning**, not an error — base `.env` / OS env may still
  satisfy the required `TESSERA_POSTGRES_*` group.

### Setup
Committed templates (no secrets): `.env.ci.example`, `.env.qa.example`, `.env.stg.example`.
Copy one to `.env.<env>`, fill the `TESSERA_POSTGRES_*` values, run with `--env <env>`:

```
copy .env.qa.example .env.qa    # then fill in QA credentials
python portfolio_kpi_metrics_postgres.py --env qa --start "..." --end "..." --report all
```

`.gitignore` was updated to ignore `.env` and every `.env.*` **except** `*.example`, so
filled-in per-environment files never get committed.

---

## 7. Files changed

| File | Change |
|------|--------|
| `Day2Day_Utillites/portfolio_kpi_metrics_postgres.py` | Core: `load_env`, `pivot_rows`, expanded report registry (`REPORT_ALIASES`/`REPORT_CHOICES`/`ALL_REPORT_KEYS`/`PIVOT_SPECS`), `load_sql_sections`/`load_sql_file_sections` parser, `is_pivot`, rewritten `run_reports` (SETUP once → per-report fetch → pivot dispatch), `build_arg_parser` + `main` with `--env`/`--top`. |
| `Day2Day_Utillites/Docs/portfolio-kpi-metrics.sql` | Rewritten: `-- SETUP: build_temp` (both temp tables) + all 16 reports reading the temp tables (incl. 4 new). |
| `Day2Day_Utillites/Docs/portfolio-kpi-metrics.md` | Reports table, flags, performance note, DBeaver "run SETUP once" step, complete tag→alias mapping. |
| `Day2Day_Utillites/Docs/portfolio-kpi-indexes.sql` | **New.** Optional prod expression index on `((entity_refresh_message->>'source'))` for ad-hoc base-table DBeaver queries — documents the `CONCURRENTLY`-per-partition vs. parent-cascade tradeoff. Not auto-applied. |
| `Day2Day_Utillites/.env.ci.example` / `.env.qa.example` / `.env.stg.example` | **New.** Per-env templates (Postgres group, blank values). |
| `Day2Day_Utillites/.gitignore` | Ignore `.env` + `.env.*`, keep `!*.example`. |
| `Day2Day_Utillites/utilities.yaml` | `portfolio-kpi-metrics-postgres` entry: 17 report choices + `--env`/`--top` + updated purpose (consumed by the catalog dashboard). |
| `.claude/skills/portfolio-kpi-ops/SKILL.md` | Runbook synced with the new reports, pivots, and `--env`/`--top`. |
| `.claude/settings.json` | Harness allowlist pruned (removed one-off `_*_tmp.py` and overly-broad entries). Housekeeping, unrelated to the tool. |
| `Day2Day_Utillites/tests/test_*.py` (6 files) | **New** pytest suites (see below). |

---

## 8. Tests

Six new pytest modules (plain-`assert` style, matching the repo convention; run with
`.\.venv\Scripts\python -m pytest tests/ -v` from `Day2Day_Utillites`). The whole suite —
these plus the pre-existing PD-precheck suite — passes **66/66**.

| Test file | Covers |
|-----------|--------|
| `test_env_loading.py` | `load_env` precedence (OS > `.env.<env>` > base) and missing-file warning. |
| `test_pivot_rows.py` | Pivot wide shape, zero-fill, `total`, `--top` truncation, multi-index, empty input, **natural numeric tie-break**, duplicate-pair summing. |
| `test_report_registry.py` | Alias→marker resolution, `all` exact aggregate set, pivot specs, unknown-report `SystemExit`. |
| `test_sql_sections.py` | The `-- SETUP:` / `-- REPORT:` section parser. |
| `test_sql_file.py` | The real SQL file: both temp tables in SETUP, every alias target marker exists, `all` keys present, pivots return `refresh_count`, and **no report body references the base table**. |
| `test_report_routing.py` | `is_pivot`, and that the parser wires `--env`/`--top`. |

DB-coupled behavior (the actual query results) is verified manually — see §10.

---

## 9. Quality gates applied

Built task-by-task with a fresh implementer + independent reviewer per task, plus a final
whole-branch review. Reviews caught and we fixed five real issues before merge:

1. Dropping an import left `main()` calling an undefined name (`--help` crashed) → rewired to `load_env(None)`.
2. Pivot tie-break sorted numeric ids as strings (`10 < 2`) → natural two-pass sort + tests.
3. `--top` truncated the CSV too → CSV now keeps all rows; only stdout is capped.
4. `--report all` included the large per-entity report → swapped to the small per-source one (+ an exact-set assertion test).
5. Stale doc passages (`--source` "slow only", incomplete mapping table) → corrected.

---

## 10. Deferred: live DB verification (needs non-prod credentials)

Automated tests cover the pure-Python and SQL-structure seams. The end-to-end run against a
real database was **not** exercised (no non-prod creds during implementation). To close it,
once `.env.qa` is populated:

```
python portfolio_kpi_metrics_postgres.py --env qa --start "2026-06-05 00:00:00" --end "2026-06-30 23:59:00" --report all
python portfolio_kpi_metrics_postgres.py --env qa --start "2026-06-05 00:00:00" --end "2026-06-30 23:59:00" --report entity_by_source --top 50
```

Expected: each report prints a table with non-negative counts; the pivot shows a `total`
column capped at 50 stdout rows. Parity check: `entities_by_day` totals should match the
original `triggering_entity_counts_by_day` query for the same window.

---

## 11. Feature commits (`5ba61bd..757cd28`)

```
757cd28 chore: update .claude/settings.json allowlist (prune one-off/broad entries)
4fc9f13 docs(portfolio-kpi-ops): sync skill runbook with new reports, pivots, --env/--top
6ebd2de fix(kpi-metrics): --report all uses per-source entity_source_totals (aggregate-only)
7588249 docs(day2day): final-review fix — all uses entity_source_totals not per-entity counts
f9d5e2a docs(kpi-metrics): fix stale --source scope note + complete report-name mapping
c40cda7 docs(kpi-metrics): document new reports, --env/--top, temp-table perf, optional index
4da3462 chore(day2day): per-env .env templates + gitignore for .env.<env>
c81ace4 fix(kpi-metrics): --top caps stdout only; CSV export keeps all pivot rows
dabf3c1 docs(day2day): Task 6 fix — --top caps stdout only, CSV keeps all pivot rows
47f114a feat(kpi-metrics): execute SETUP once, pivot dispatch, --env/--top wiring
c19e8bf perf(kpi-metrics): temp-table SETUP + reports read tmp tables; add new reports
e650848 feat(kpi-metrics): parse SETUP + REPORT sections from SQL file
eb1bbf8 feat(kpi-metrics): expand report registry + pivot specs
7d29c86 fix(kpi-metrics): pivot_rows sorts index cols in natural (not string) order
4b6e028 docs(day2day): fix Task 2 pivot sort (natural index order) + tie-break/dup tests
c3e4100 feat(kpi-metrics): add pivot_rows helper for 2D report output
03aa8cc fix(kpi-metrics): call load_env(None) in main() so CLI runs after import drop
8e47cbc docs(day2day): Task 1 also rewires main() to load_env(None) so CLI stays runnable
021c733 feat(kpi-metrics): add --env-aware .env loader (load_env)
```
