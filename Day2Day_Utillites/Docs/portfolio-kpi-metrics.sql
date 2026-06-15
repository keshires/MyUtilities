-- Portfolio KPI update log — operational metrics
-- Table: public.portfolio_kpi_update_log (partitioned on message_created_at)
--
-- Python runner (uses .env; sets the same session params automatically):
--   python portfolio_kpi_metrics_postgres.py --start "2026-05-20 00:00:00" --end "2026-05-21 00:00:00" --report hourly
--
-- Reports are tagged with:  -- REPORT: <name>

-- =============================================================================
-- PARAMS — DBeaver: edit ONLY the three datetime/source values below, then
-- Execute this block once per session (Ctrl+Enter). Every report below reads
-- these settings; you never repeat timestamps inside individual queries.
-- =============================================================================
SELECT
  set_config('portfolio_kpi.window_start', '2026-05-20 00:00:00', false),
  set_config('portfolio_kpi.window_end',   '2026-05-21 00:00:00', false),
  set_config('portfolio_kpi.source_filter', '', false);
-- window_start  : inclusive lower bound (timestamp text)
-- window_end    : exclusive upper bound (timestamp text)
-- source_filter : optional; '' = all, or e.g. 'Custom Financials' (hourly_totals, slow reports)

-- Optional: confirm what is active in this session
-- SELECT
--   current_setting('portfolio_kpi.window_start')  AS window_start,
--   current_setting('portfolio_kpi.window_end')    AS window_end,
--   current_setting('portfolio_kpi.source_filter') AS source_filter;

-- =============================================================================
-- REPORT: hourly_totals
-- Messages received per hour vs processed per hour, broken down by source.
-- =============================================================================
WITH params AS (
  SELECT
    current_setting('portfolio_kpi.window_start')::timestamp AS start_ts,
    current_setting('portfolio_kpi.window_end')::timestamp   AS end_ts,
    NULLIF(TRIM(current_setting('portfolio_kpi.source_filter')), '')::text AS source_filter
),
received AS (
  SELECT
    date_trunc('hour', l.message_received_at) AS hour_utc,
    COALESCE(l.entity_refresh_message->>'source', '(null)') AS source,
    COUNT(*) AS messages_received
  FROM public.portfolio_kpi_update_log l
  CROSS JOIN params p
  WHERE l.message_created_at >= p.start_ts
    AND l.message_created_at < p.end_ts
    AND l.message_received_at IS NOT NULL
    AND l.message_received_at >= p.start_ts
    AND l.message_received_at < p.end_ts
    AND (
      p.source_filter IS NULL
      OR l.entity_refresh_message->>'source' = p.source_filter
    )
  GROUP BY 1, 2
),
processed AS (
  SELECT
    date_trunc('hour', l.processing_completed_at) AS hour_utc,
    COALESCE(l.entity_refresh_message->>'source', '(null)') AS source,
    COUNT(*) AS messages_processed
  FROM public.portfolio_kpi_update_log l
  CROSS JOIN params p
  WHERE l.message_created_at >= p.start_ts
    AND l.message_created_at < p.end_ts
    AND l.processing_completed_at IS NOT NULL
    AND l.processing_completed_at >= p.start_ts
    AND l.processing_completed_at < p.end_ts
    AND (
      p.source_filter IS NULL
      OR l.entity_refresh_message->>'source' = p.source_filter
    )
  GROUP BY 1, 2
)
SELECT
  COALESCE(r.hour_utc, p.hour_utc) AS hour_utc,
  COALESCE(r.source, p.source)       AS source,
  COALESCE(r.messages_received, 0)  AS messages_received,
  COALESCE(p.messages_processed, 0) AS messages_processed
FROM received r
FULL OUTER JOIN processed p
  ON p.hour_utc = r.hour_utc AND p.source = r.source
ORDER BY hour_utc, source;

-- =============================================================================
-- REPORT: hourly_by_status
-- Same as hourly_totals, broken down by status.
-- =============================================================================
WITH params AS (
  SELECT
    current_setting('portfolio_kpi.window_start')::timestamp AS start_ts,
    current_setting('portfolio_kpi.window_end')::timestamp   AS end_ts,
    NULLIF(TRIM(current_setting('portfolio_kpi.source_filter')), '')::text AS source_filter
),
received AS (
  SELECT
    date_trunc('hour', l.message_received_at) AS hour_utc,
    COALESCE(l.status, '(null)') AS status,
    COUNT(*) AS messages_received
  FROM public.portfolio_kpi_update_log l
  CROSS JOIN params p
  WHERE l.message_created_at >= p.start_ts
    AND l.message_created_at < p.end_ts
    AND l.message_received_at IS NOT NULL
    AND l.message_received_at >= p.start_ts
    AND l.message_received_at < p.end_ts
  GROUP BY 1, 2
),
processed AS (
  SELECT
    date_trunc('hour', l.processing_completed_at) AS hour_utc,
    COALESCE(l.status, '(null)') AS status,
    COUNT(*) AS messages_processed
  FROM public.portfolio_kpi_update_log l
  CROSS JOIN params p
  WHERE l.message_created_at >= p.start_ts
    AND l.message_created_at < p.end_ts
    AND l.processing_completed_at IS NOT NULL
    AND l.processing_completed_at >= p.start_ts
    AND l.processing_completed_at < p.end_ts
  GROUP BY 1, 2
)
SELECT
  COALESCE(r.hour_utc, p.hour_utc) AS hour_utc,
  COALESCE(r.status, p.status)       AS status,
  COALESCE(r.messages_received, 0)   AS messages_received,
  COALESCE(p.messages_processed, 0)  AS messages_processed
FROM received r
FULL OUTER JOIN processed p
  ON p.hour_utc = r.hour_utc AND p.status = r.status
ORDER BY hour_utc, status;

-- =============================================================================
-- REPORT: status_summary
-- Row counts by status in the window.
-- =============================================================================
WITH params AS (
  SELECT
    current_setting('portfolio_kpi.window_start')::timestamp AS start_ts,
    current_setting('portfolio_kpi.window_end')::timestamp   AS end_ts,
    NULLIF(TRIM(current_setting('portfolio_kpi.source_filter')), '')::text AS source_filter
)
SELECT
  COALESCE(l.status, '(null)') AS status,
  COUNT(*) AS row_count
FROM public.portfolio_kpi_update_log l
CROSS JOIN params p
WHERE l.message_created_at >= p.start_ts
  AND l.message_created_at < p.end_ts
GROUP BY 1
ORDER BY row_count DESC;

-- =============================================================================
-- REPORT: portfolio_updates_by_source
-- Update count per portfolio, broken down by source, in the window.
-- For "all history through a date": set window_start early (e.g. 2020-01-01)
-- and window_end to the as-of timestamp (exclusive upper bound).
-- =============================================================================
WITH params AS (
  SELECT
    current_setting('portfolio_kpi.window_start')::timestamp AS start_ts,
    current_setting('portfolio_kpi.window_end')::timestamp   AS end_ts,
    NULLIF(TRIM(current_setting('portfolio_kpi.source_filter')), '')::text AS source_filter
)
SELECT
  l.portfolio_id,
  COALESCE(l.entity_refresh_message->>'source', '(null)') AS source,
  COUNT(*) AS update_count,
  MIN(l.message_created_at) AS first_update_at,
  MAX(l.message_created_at) AS last_update_at
FROM public.portfolio_kpi_update_log l
CROSS JOIN params p
WHERE l.message_created_at >= p.start_ts
  AND l.message_created_at < p.end_ts
  AND (
    p.source_filter IS NULL
    OR l.entity_refresh_message->>'source' = p.source_filter
  )
GROUP BY
  l.portfolio_id,
  COALESCE(l.entity_refresh_message->>'source', '(null)')
ORDER BY update_count DESC, portfolio_id, source;

-- =============================================================================
-- REPORT: source_update_totals
-- Total updates and distinct portfolios per source in the window.
-- =============================================================================
WITH params AS (
  SELECT
    current_setting('portfolio_kpi.window_start')::timestamp AS start_ts,
    current_setting('portfolio_kpi.window_end')::timestamp   AS end_ts,
    NULLIF(TRIM(current_setting('portfolio_kpi.source_filter')), '')::text AS source_filter
)
SELECT
  COALESCE(l.entity_refresh_message->>'source', '(null)') AS source,
  COUNT(*) AS total_updates,
  COUNT(DISTINCT l.portfolio_id) AS portfolios_updated,
  MIN(l.message_created_at) AS first_update_at,
  MAX(l.message_created_at) AS last_update_at
FROM public.portfolio_kpi_update_log l
CROSS JOIN params p
WHERE l.message_created_at >= p.start_ts
  AND l.message_created_at < p.end_ts
  AND (
    p.source_filter IS NULL
    OR l.entity_refresh_message->>'source' = p.source_filter
  )
GROUP BY 1
ORDER BY total_updates DESC, source;

-- =============================================================================
-- REPORT: triggering_entity_counts
-- Unnest triggering_entity_external_ids (text[] like {uuid,uuid,...}) and
-- count each entity id. Example row with 10 ids becomes 10 expanded rows.
-- =============================================================================
WITH params AS (
  SELECT
    current_setting('portfolio_kpi.window_start')::timestamp AS start_ts,
    current_setting('portfolio_kpi.window_end')::timestamp   AS end_ts,
    NULLIF(TRIM(current_setting('portfolio_kpi.source_filter')), '')::text AS source_filter
),
expanded AS (
  SELECT
    l.portfolio_id,
    COALESCE(l.entity_refresh_message->>'source', '(null)') AS source,
    entity_id
  FROM public.portfolio_kpi_update_log l
  CROSS JOIN params p
  CROSS JOIN LATERAL unnest(l.triggering_entity_external_ids) AS entity_id
  WHERE l.message_created_at >= p.start_ts
    AND l.message_created_at < p.end_ts
    AND l.triggering_entity_external_ids IS NOT NULL
    AND cardinality(l.triggering_entity_external_ids) > 0
    AND (
      p.source_filter IS NULL
      OR l.entity_refresh_message->>'source' = p.source_filter
    )
)
SELECT
  entity_id,
  source,
  COUNT(*) AS trigger_count,
  COUNT(DISTINCT portfolio_id) AS portfolios_affected
FROM expanded
GROUP BY entity_id, source
ORDER BY trigger_count DESC, entity_id, source;

-- =============================================================================
-- REPORT: slow_global
-- Completed messages slower than global P95 processing time in the window.
-- =============================================================================
WITH params AS (
  SELECT
    current_setting('portfolio_kpi.window_start')::timestamp AS start_ts,
    current_setting('portfolio_kpi.window_end')::timestamp   AS end_ts,
    NULLIF(TRIM(current_setting('portfolio_kpi.source_filter')), '')::text AS source_filter
),
completed AS (
  SELECT
    l.id,
    l.message_created_at,
    l.message_id,
    l.portfolio_id,
    COALESCE(l.status, '(null)') AS status,
    COALESCE(l.entity_refresh_message->>'source', '(null)') AS source,
    l.entity_refresh_message->>'group' AS "group",
    l.entity_refresh_message,
    l.triggering_entity_external_ids,
    l.message_received_at,
    l.processing_started_at,
    l.processing_completed_at,
    ROUND(
      EXTRACT(EPOCH FROM (l.processing_completed_at - l.processing_started_at))::numeric,
      3
    ) AS process_seconds_computed,
    l.duration_seconds AS process_seconds_stored,
    ROUND(
      EXTRACT(EPOCH FROM (l.processing_started_at - l.message_received_at))::numeric,
      3
    ) AS queue_wait_seconds
  FROM public.portfolio_kpi_update_log l
  CROSS JOIN params p
  WHERE l.message_created_at >= p.start_ts
    AND l.message_created_at < p.end_ts
    AND l.processing_started_at IS NOT NULL
    AND l.processing_completed_at IS NOT NULL
    AND l.processing_completed_at >= l.processing_started_at
    AND (
      p.source_filter IS NULL
      OR l.entity_refresh_message->>'source' = p.source_filter
    )
),
baseline AS (
  SELECT
    COUNT(*) AS sample_size,
    ROUND(AVG(process_seconds_computed)::numeric, 3) AS avg_process_sec,
    ROUND(
      (PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY process_seconds_computed))::numeric,
      3
    ) AS median_process_sec,
    ROUND(
      (PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY process_seconds_computed))::numeric,
      3
    ) AS p95_process_sec,
    ROUND(
      (PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY process_seconds_computed))::numeric,
      3
    ) AS p99_process_sec
  FROM completed
)
SELECT
  c.id,
  c.message_created_at,
  c.message_id,
  c.portfolio_id,
  c.status,
  c.source,
  c."group",
  c.entity_refresh_message,
  c.triggering_entity_external_ids,
  c.message_received_at,
  c.processing_started_at,
  c.processing_completed_at,
  c.process_seconds_computed,
  c.process_seconds_stored,
  c.queue_wait_seconds,
  b.sample_size,
  b.avg_process_sec,
  b.median_process_sec,
  b.p95_process_sec,
  b.p99_process_sec,
  ROUND((c.process_seconds_computed / NULLIF(b.median_process_sec, 0))::numeric, 2)
    AS times_median,
  ROUND((c.process_seconds_computed / NULLIF(b.p95_process_sec, 0))::numeric, 2)
    AS times_p95
FROM completed c
CROSS JOIN baseline b
WHERE c.process_seconds_computed > b.p95_process_sec
ORDER BY c.process_seconds_computed DESC;

-- =============================================================================
-- REPORT: slow_by_source
-- Slow = above P95 processing time within each source.
-- =============================================================================
WITH params AS (
  SELECT
    current_setting('portfolio_kpi.window_start')::timestamp AS start_ts,
    current_setting('portfolio_kpi.window_end')::timestamp   AS end_ts,
    NULLIF(TRIM(current_setting('portfolio_kpi.source_filter')), '')::text AS source_filter
),
completed AS (
  SELECT
    l.id,
    l.message_created_at,
    l.message_id,
    l.portfolio_id,
    COALESCE(l.status, '(null)') AS status,
    COALESCE(l.entity_refresh_message->>'source', '(null)') AS source,
    l.entity_refresh_message->>'group' AS "group",
    l.entity_refresh_message,
    l.triggering_entity_external_ids,
    l.message_received_at,
    l.processing_started_at,
    l.processing_completed_at,
    ROUND(
      EXTRACT(EPOCH FROM (l.processing_completed_at - l.processing_started_at))::numeric,
      3
    ) AS process_seconds_computed,
    l.duration_seconds AS process_seconds_stored
  FROM public.portfolio_kpi_update_log l
  CROSS JOIN params p
  WHERE l.message_created_at >= p.start_ts
    AND l.message_created_at < p.end_ts
    AND l.processing_started_at IS NOT NULL
    AND l.processing_completed_at IS NOT NULL
    AND l.processing_completed_at >= l.processing_started_at
    AND (
      p.source_filter IS NULL
      OR l.entity_refresh_message->>'source' = p.source_filter
    )
),
baseline_by_source AS (
  SELECT
    source,
    COUNT(*) AS sample_size,
    ROUND(
      (PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY process_seconds_computed))::numeric,
      3
    ) AS p95_process_sec
  FROM completed
  GROUP BY source
)
SELECT
  c.id,
  c.message_created_at,
  c.message_id,
  c.portfolio_id,
  c.status,
  c.source,
  c."group",
  c.entity_refresh_message,
  c.triggering_entity_external_ids,
  c.message_received_at,
  c.processing_started_at,
  c.processing_completed_at,
  c.process_seconds_computed,
  c.process_seconds_stored,
  b.sample_size,
  b.p95_process_sec,
  ROUND((c.process_seconds_computed / NULLIF(b.p95_process_sec, 0))::numeric, 2)
    AS times_source_p95
FROM completed c
JOIN baseline_by_source b ON b.source = c.source
WHERE c.process_seconds_computed > b.p95_process_sec
ORDER BY c.process_seconds_computed DESC;

-- =============================================================================
-- REPORT: triggering_entity_counts_by_day
-- Unnest triggering_entity_external_ids and count triggers per day.
-- =============================================================================
WITH params AS (
  SELECT
    current_setting('portfolio_kpi.window_start')::timestamp AS start_ts,
    current_setting('portfolio_kpi.window_end')::timestamp   AS end_ts,
    NULLIF(TRIM(current_setting('portfolio_kpi.source_filter')), '')::text AS source_filter
),
expanded AS (
  SELECT
    date_trunc('day', l.message_created_at)::date AS day,
    l.portfolio_id,
    COALESCE(l.entity_refresh_message->>'source', '(null)') AS source,
    entity_id
  FROM public.portfolio_kpi_update_log l
  CROSS JOIN params p
  CROSS JOIN LATERAL unnest(l.triggering_entity_external_ids) AS entity_id
  WHERE l.message_created_at >= p.start_ts
    AND l.message_created_at < p.end_ts
    AND l.triggering_entity_external_ids IS NOT NULL
    AND cardinality(l.triggering_entity_external_ids) > 0
    AND (
      p.source_filter IS NULL
      OR l.entity_refresh_message->>'source' = p.source_filter
    )
)
SELECT
  day,
  source,
  COUNT(*) AS entity_trigger_count,
  COUNT(DISTINCT entity_id) AS distinct_entities,
  COUNT(DISTINCT portfolio_id) AS portfolios_affected
FROM expanded
GROUP BY day, source
ORDER BY day, source;