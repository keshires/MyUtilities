/**********************************************************************************************
  diagnose_slow_sp_blocking.sql
  --------------------------------------------------------------------------------------------
  Purpose : Diagnose why a proc that "used to run in 1s now takes ~1 min" with no data growth.
            Hypothesis: the SPID is SUSPENDED waiting on a lock held by an in-progress /
            rolling-back transaction, OR is hitting tempdb allocation contention.

  Target  : ce2_get_report_builder_pit_v7  (DB: CreditEdge_Internal) -- but generic to any proc.

  HOW TO USE
    * Run this WHILE the slow execution is happening (that is the whole point -- a query at
      rest tells you nothing about what it waits on).
    * Sections are independent. Run Section 1 first; it points you at the rest.
    * Read-only. No schema/data changes. Safe to hand to the DB team as-is.

  WHAT EACH SECTION ANSWERS
    1. Is our session waiting, and on whom?              (the smoking gun)
    2. Full blocking chain (head blocker -> victims)
    3. Long-running / rolling-back transactions          (KILLED/ROLLBACK, % complete)
    4. tempdb allocation-latch contention (PFS/GAM/SGAM)
    5. tempdb space consumers (this proc creates ~8 temp tables + SELECT INTO)
    6. sp_whoisactive-style all-active-sessions snapshot (self-contained; no install needed)
    7. Optional: is a plan-regression the real cause instead? (rules the theory in/out)

  NOTE: uses NOLOCK-free DMVs. No dependency on sp_whoisactive.
**********************************************************************************************/

SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;  -- diagnostics only; do not block on the blocker

-- Optional: focus everything on one proc name. Leave NULL to see everything.
DECLARE @proc_name SYSNAME = NULL;  -- e.g. N'ce2_get_report_builder_pit_v7'
DECLARE @proc_db   SYSNAME = N'CreditEdge_Internal';

/*============================================================================================
  SECTION 1 -- Is our session waiting, and on whom?  (RUN THIS FIRST)
  Look for: wait_type LIKE 'LCK_M_%'  and a non-NULL blocking_session_id.
            That confirms blocking. PAGELATCH_* on tempdb -> go to Section 4.
============================================================================================*/
PRINT '=== SECTION 1: Active requests, waits, and blockers ===';

SELECT  r.session_id,
        r.blocking_session_id,
        r.status,                         -- 'suspended' = waiting on a resource
        r.wait_type,                      -- LCK_M_S / LCK_M_U = blocked by a writer
        r.wait_time      AS wait_ms,
        r.last_wait_type,
        r.wait_resource,                  -- which key/page/object it is stuck on
        r.command,
        r.cpu_time,
        r.total_elapsed_time AS elapsed_ms,
        r.reads, r.writes, r.logical_reads,
        DB_NAME(r.database_id) AS database_name,
        OBJECT_NAME(st.objectid, st.dbid) AS object_name,
        SUBSTRING(st.text,
                  (r.statement_start_offset/2)+1,
                  ((CASE r.statement_end_offset WHEN -1 THEN DATALENGTH(st.text)
                        ELSE r.statement_end_offset END - r.statement_start_offset)/2)+1
                 ) AS running_statement,
        s.login_name, s.host_name, s.program_name
FROM    sys.dm_exec_requests r
JOIN    sys.dm_exec_sessions s ON s.session_id = r.session_id
CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) st
WHERE   r.session_id <> @@SPID
  AND   s.is_user_process = 1
  AND   ( @proc_name IS NULL
          OR OBJECT_NAME(st.objectid, st.dbid) = @proc_name )
ORDER BY r.blocking_session_id DESC, r.wait_time DESC;

/*============================================================================================
  SECTION 2 -- Full blocking chain (head blocker -> victims)
  The row(s) with blocking_session_id = 0/NULL but that ARE blocking others = head blocker.
============================================================================================*/
PRINT '=== SECTION 2: Blocking chain (waiting tasks) ===';

SELECT  wt.blocking_session_id           AS blocker_spid,
        wt.session_id                    AS waiter_spid,
        wt.wait_duration_ms,
        wt.wait_type,
        wt.resource_description,
        blk.status                       AS blocker_status,
        blk.command                      AS blocker_command,
        DB_NAME(blk_req.database_id)     AS blocker_db,
        SUBSTRING(blk_txt.text, 1, 300)  AS blocker_current_batch,
        blk.login_name                   AS blocker_login,
        blk.host_name                    AS blocker_host,
        blk.program_name                 AS blocker_program
FROM    sys.dm_os_waiting_tasks wt
LEFT JOIN sys.dm_exec_sessions blk      ON blk.session_id = wt.blocking_session_id
LEFT JOIN sys.dm_exec_requests blk_req  ON blk_req.session_id = wt.blocking_session_id
OUTER APPLY sys.dm_exec_sql_text(blk_req.sql_handle) blk_txt
WHERE   wt.blocking_session_id IS NOT NULL
  AND   wt.blocking_session_id <> wt.session_id
ORDER BY wt.wait_duration_ms DESC;

/*============================================================================================
  SECTION 3 -- Long-running / rolling-back transactions  (the DB team's suspicion)
  Look for: status/command = 'KILLED/ROLLBACK', or percent_complete climbing on a ROLLBACK,
            or a very old transaction_begin_time still holding locks.
============================================================================================*/
PRINT '=== SECTION 3: Long / open / rolling-back transactions ===';

SELECT  s.session_id,
        s.status                         AS session_status,
        r.command,                       -- 'KILLED/ROLLBACK' or 'ROLLBACK' during recovery
        r.percent_complete,              -- for a rollback this creeps 0 -> 100
        r.estimated_completion_time/1000.0 AS est_seconds_left,
        at.transaction_begin_time,
        DATEDIFF(SECOND, at.transaction_begin_time, GETDATE()) AS open_seconds,
        CASE at.transaction_state
             WHEN 3 THEN 'active'
             WHEN 4 THEN 'DISTRIBUTED-active'
             WHEN 5 THEN 'prepared'
             WHEN 6 THEN 'committed'
             WHEN 7 THEN 'ROLLING BACK'      -- <-- this is what we are hunting
             WHEN 8 THEN 'rolled back'
             ELSE CONVERT(VARCHAR(20), at.transaction_state) END AS transaction_state,
        DB_NAME(dt.database_id)          AS database_name,
        s.login_name, s.host_name, s.program_name,
        SUBSTRING(txt.text, 1, 300)      AS last_statement
FROM    sys.dm_tran_active_transactions at
JOIN    sys.dm_tran_session_transactions st ON st.transaction_id = at.transaction_id
JOIN    sys.dm_exec_sessions s              ON s.session_id = st.session_id
LEFT JOIN sys.dm_tran_database_transactions dt ON dt.transaction_id = at.transaction_id
LEFT JOIN sys.dm_exec_requests r            ON r.session_id = s.session_id
OUTER APPLY sys.dm_exec_sql_text(r.sql_handle) txt
ORDER BY at.transaction_begin_time ASC;   -- oldest first

/*============================================================================================
  SECTION 4 -- tempdb allocation-latch contention (PFS / GAM / SGAM)
  This proc creates ~8 temp tables + several SELECT INTO. If Section 1 shows PAGELATCH_UP
  waits on pages like 2:1:1 (PFS), 2:1:2 (GAM), 2:1:3 (SGAM) -> tempdb file contention.
  Fix: add more equally-sized tempdb data files.
============================================================================================*/
PRINT '=== SECTION 4: tempdb PFS/GAM/SGAM latch contention ===';

SELECT  wt.session_id,
        wt.wait_type,
        wt.wait_duration_ms,
        wt.resource_description,
        CASE
            WHEN wt.resource_description LIKE '2:%' THEN
                CASE
                    WHEN CAST(PARSENAME(REPLACE(wt.resource_description,':','.'),1) AS INT) = 1
                         THEN 'PFS page'
                    WHEN CAST(PARSENAME(REPLACE(wt.resource_description,':','.'),1) AS INT) = 2
                         THEN 'GAM page'
                    WHEN CAST(PARSENAME(REPLACE(wt.resource_description,':','.'),1) AS INT) = 3
                         THEN 'SGAM page'
                    ELSE 'other tempdb page'
                END
            ELSE 'not tempdb'
        END AS latch_class_guess
FROM    sys.dm_os_waiting_tasks wt
WHERE   wt.wait_type LIKE 'PAGELATCH%'
  AND   wt.resource_description LIKE '2:%'   -- database_id 2 = tempdb
ORDER BY wt.wait_duration_ms DESC;

-- tempdb data file count (a single file is the classic contention cause)
SELECT  COUNT(*) AS tempdb_data_files,
        MIN(size/128.0) AS min_file_mb,
        MAX(size/128.0) AS max_file_mb
FROM    tempdb.sys.database_files
WHERE   type_desc = 'ROWS';

/*============================================================================================
  SECTION 5 -- Who is consuming tempdb space right now
  Confirms whether this proc's temp tables / version store are the pressure.
============================================================================================*/
PRINT '=== SECTION 5: tempdb space usage by session ===';

SELECT  su.session_id,
        s.login_name, s.host_name, s.program_name,
        (su.user_objects_alloc_page_count      * 8)/1024.0 AS user_obj_mb,       -- #temp tables
        (su.internal_objects_alloc_page_count  * 8)/1024.0 AS internal_obj_mb,   -- sorts/hashes/spools
        r.command,
        DB_NAME(r.database_id) AS current_db,
        OBJECT_NAME(st.objectid, st.dbid) AS object_name
FROM    sys.dm_db_session_space_usage su
JOIN    sys.dm_exec_sessions s ON s.session_id = su.session_id
LEFT JOIN sys.dm_exec_requests r ON r.session_id = su.session_id
OUTER APPLY sys.dm_exec_sql_text(r.sql_handle) st
WHERE   su.user_objects_alloc_page_count + su.internal_objects_alloc_page_count > 0
ORDER BY (su.user_objects_alloc_page_count + su.internal_objects_alloc_page_count) DESC;

-- version store size (large here => READ_COMMITTED_SNAPSHOT / long open txn pressure)
SELECT  SUM(version_store_reserved_page_count) * 8 / 1024.0 AS version_store_mb
FROM    tempdb.sys.dm_db_file_space_usage;

/*============================================================================================
  SECTION 6 -- sp_whoisactive-style snapshot (self-contained; no module to install)
  One row per active user request, most-blocked / longest-running first.
============================================================================================*/
PRINT '=== SECTION 6: Active sessions snapshot (whoisactive-style) ===';

SELECT  r.session_id                                        AS spid,
        r.blocking_session_id                               AS blocked_by,
        r.status,
        r.wait_type,
        r.wait_time                                         AS wait_ms,
        r.total_elapsed_time                                AS elapsed_ms,
        r.cpu_time                                          AS cpu_ms,
        r.logical_reads,
        r.open_transaction_count                            AS open_txns,
        DB_NAME(r.database_id)                              AS database_name,
        OBJECT_NAME(st.objectid, st.dbid)                   AS object_name,
        SUBSTRING(st.text,
                  (r.statement_start_offset/2)+1,
                  ((CASE r.statement_end_offset WHEN -1 THEN DATALENGTH(st.text)
                        ELSE r.statement_end_offset END - r.statement_start_offset)/2)+1
                 )                                          AS current_statement,
        s.login_name, s.host_name, s.program_name,
        s.last_request_start_time
FROM    sys.dm_exec_requests r
JOIN    sys.dm_exec_sessions s ON s.session_id = r.session_id
CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) st
WHERE   s.is_user_process = 1
  AND   r.session_id <> @@SPID
ORDER BY r.blocking_session_id DESC, r.total_elapsed_time DESC;

/*============================================================================================
  SECTION 7 -- (OPTIONAL) Rule out a plan regression instead of blocking.
  If Sections 1-3 show NO blocking and NO tempdb waits, the slowdown may be a bad cached plan
  or stale stats. This compares cached plans for the proc: high worker_time / big gaps between
  min & max elapsed = plan instability / parameter sniffing.
  Requires the proc to have run at least once since last cache flush.
============================================================================================*/
PRINT '=== SECTION 7: Cached plan stats for the proc (plan-regression check) ===';

SELECT  DB_NAME(qt.dbid)                    AS database_name,
        OBJECT_NAME(qt.objectid, qt.dbid)   AS object_name,
        qs.execution_count,
        qs.total_worker_time/1000.0/NULLIF(qs.execution_count,0)  AS avg_cpu_ms,
        qs.total_elapsed_time/1000.0/NULLIF(qs.execution_count,0) AS avg_elapsed_ms,
        qs.min_elapsed_time/1000.0          AS min_elapsed_ms,
        qs.max_elapsed_time/1000.0          AS max_elapsed_ms,   -- big vs min => unstable plan
        qs.total_logical_reads/NULLIF(qs.execution_count,0)      AS avg_logical_reads,
        qs.creation_time                    AS plan_cached_at,
        qs.last_execution_time
FROM    sys.dm_exec_query_stats qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) qt
WHERE   OBJECT_NAME(qt.objectid, qt.dbid) = ISNULL(@proc_name, N'ce2_get_report_builder_pit_v7')
ORDER BY qs.max_elapsed_time DESC;

/*============================================================================================
  INTERPRETATION CHEAT-SHEET
  --------------------------------------------------------------------------------------------
  Section 1 wait_type LIKE 'LCK_M_%' + blocking_session_id set
        => CONFIRMED blocking. Go to Section 2/3, find the head blocker.
           If head blocker is in ROLLBACK (Section 3) -> the DB team is right. Let it finish,
           and enable READ_COMMITTED_SNAPSHOT so readers stop blocking on writers.

  Section 1 wait_type = PAGELATCH_UP on 2:1:x
        => tempdb allocation contention. Add equally-sized tempdb data files (Section 4).

  Section 1 wait_type = WRITELOG / high, no blocker
        => log/IO subsystem, not this proc.

  No waits anywhere, but Section 7 max_elapsed >> min_elapsed
        => plan regression / parameter sniffing / stale stats. Update stats, consider
           Query Store to force the good plan.
============================================================================================*/