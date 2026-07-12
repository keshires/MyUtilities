# Runbook: `ce2_get_report_builder_pit_v7` suddenly slow (1s → ~1 min)

**Database:** `CreditEdge_Internal`
**Proc:** `dbo.ce2_get_report_builder_pit_v7`
**Diagnostic script:** [`Day2Day_Utillites/sql/diagnose_slow_sp_blocking.sql`](../../Day2Day_Utillites/sql/diagnose_slow_sp_blocking.sql)
**First investigated:** 2026-07-08

---

## TL;DR

If this proc "used to run in 1 second and now takes ~1 minute" **with no meaningful data growth**, it is almost certainly **not** the query itself. The SPID is spending ~59 of those 60 seconds **SUSPENDED, waiting on a lock** held by an in-progress or **rolling-back** transaction on one of the base tables it reads. Run the diagnostic script **while the slow run is happening** and look at Section 1 → Section 3.

**Fast path:**
1. Run [`diagnose_slow_sp_blocking.sql`](../../Day2Day_Utillites/sql/diagnose_slow_sp_blocking.sql) Section 1 during a slow execution.
2. If `wait_type LIKE 'LCK_M_%'` and `blocking_session_id` is set → blocking confirmed. Go to Section 3, find the blocker; if it's in `ROLLING BACK` you've found it. Let the rollback finish or address the process that issued/killed it.
3. Structural fix so readers stop blocking on writers: enable **`READ_COMMITTED_SNAPSHOT`** on `CreditEdge_Internal` (test tempdb sizing first).

---

## Symptom → cause reasoning

The key diagnostic signal is the **shape** of the slowdown:

| Observation | What it implies |
|---|---|
| Same inputs, same data volume, was 1s, now 60s | Execution logic is fine; time is being spent **waiting**, not computing |
| Slowness is **intermittent** (not every run) | **External contention** — a bad plan / stale stats would be slow *consistently* |
| DB team reports in-progress **suspends and rollbacks** | Matches lock-wait hypothesis directly |

**Why a rollback blocks this proc:**
1. A rollback holds its X/U locks until it **fully completes**. Rollback is largely single-threaded and can take *longer* than the original forward operation.
2. This proc reads a wide fan of base tables under default **READ COMMITTED**, needing **S locks** on each. An S lock is incompatible with the blocker's X lock → the SPID parks in `LCK_M_S`.
3. The "1 minute" ≈ **time for the blocker to finish rolling back**, not CPU time.

## Why this proc is especially fragile to contention

Even though the *trigger* is external, the proc's design amplifies any contention:

- **Scalar UDF `dbo.ce2_udf_get_previous_date()`** called in nearly every UPDATE/subquery → row-by-row execution, forces serial plans (pre-2019 / when not inlinable).
- **Dozens of correlated subqueries** with `MAX()` + self-references re-scanning the same base tables per UPDATE.
- **~8 temp tables + several `SELECT … INTO`** → tempdb metadata/allocation pressure; `SELECT INTO` holds allocation locks.
- **No row-versioning / snapshot isolation** → fully exposed to *any* writer on *any* of the ~12 base tables it touches (`organization`, `credit_risk_measure_edf_9_daily_base`, `gen_history`, `mir_global_daily`, `financial_statement`, `ratings`, `eicds_hist`, `firm_edficds_hist`, `cds_spread_market_data`, `size_rsq_hist`, …). One rogue rollback anywhere in that set stalls the whole proc.

---

## How to diagnose (run during a slow execution)

Use [`diagnose_slow_sp_blocking.sql`](../../Day2Day_Utillites/sql/diagnose_slow_sp_blocking.sql). It is **read-only** (sets `READ UNCOMMITTED` so the diagnostics don't join the blocking queue) with 7 independent sections:

| # | Section | Answers |
|---|---------|---------|
| 1 | Active requests + waits + blockers | **Run first.** Is our SPID `suspended` on `LCK_M_S`/`LCK_M_U` with a non-null `blocking_session_id`? |
| 2 | Blocking chain | Head blocker and the batch it's running |
| 3 | Long / open / **rolling-back** transactions | Flags `transaction_state = ROLLING BACK`, `KILLED/ROLLBACK`, `percent_complete`, `open_seconds` |
| 4 | tempdb PFS/GAM/SGAM latch contention | `PAGELATCH_UP` on `2:1:x`? + tempdb data-file count |
| 5 | tempdb space by session | Which SPID's temp tables / version store is the pressure |
| 6 | `sp_whoisactive`-style snapshot | One row per active session (no module install needed) |
| 7 | Cached plan stats for the proc | Rules the *other* theory (plan regression / stale stats) in/out |

Knobs at the top: `@proc_name` (leave `NULL` to see everything), `@proc_db`.

> ⚠️ **You must run it while the slow execution is in flight.** A query at rest reveals nothing about what it waits on.

### Interpretation cheat-sheet

| Section 1 signal | Meaning | Action |
|---|---|---|
| `LCK_M_%` + `blocking_session_id` set | **Blocking confirmed** | Section 2/3 → find head blocker; if in `ROLLING BACK`, let it finish |
| `PAGELATCH_UP` on `2:1:x` | tempdb allocation contention | Add equally-sized tempdb data files (Section 4) |
| `WRITELOG` high, no blocker | log/IO subsystem | Storage/log tuning — not this proc |
| No waits, but Section 7 `max_elapsed >> min_elapsed` | plan regression / param sniffing / stale stats | Update stats; consider Query Store to force the good plan |

> Note: Section 7 keys off `sys.dm_exec_query_stats`, which for a heavy-temp-table proc often recompiles per execution, so plan rows may be sparse. If durable plan history is needed, use **Query Store** (if enabled on that DB).

---

## Fixes

**Immediate (unblock now)**
- Identify the blocker (Section 3). Let the rollback complete, or fix the process that issues/kills large transactions against these tables during read hours.

**Short-term (make the proc resilient to writers)**
- Enable **`READ_COMMITTED_SNAPSHOT` (RCSI)** on `CreditEdge_Internal` so readers use row versions and stop blocking on writers. Highest-leverage fix for *this exact symptom*, and far safer for financial data than sprinkling `NOLOCK`. Test tempdb/version-store sizing first.
- If Section 4 shows tempdb latch contention, add **multiple equally-sized tempdb data files**.

**Medium-term (harden)**
- Turn on **Query Store** — permanently settles plan-regression vs. blocking, and lets you force the fast plan.
- `UPDATE STATISTICS` / index maintenance on the base tables.
- If SQL 2019+, verify **scalar UDF inlining** applies to `ce2_udf_get_previous_date`; if not, rewrite it as an **inline TVF** or fold the date logic into set-based CTEs.

---

## Bottom line

The proc didn't get slower — it's **waiting on a blocker**. Given "no data growth" + "1s → 60s" + DB team seeing in-progress rollbacks/suspends, the near-certain cause is **lock contention: the reader is blocked behind an X-lock held by a rolling-back or long-open transaction** on one of the base tables. Confirm with Sections 1–3; RCSI is the best structural fix.
