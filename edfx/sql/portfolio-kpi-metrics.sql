-- Portfolio KPI update log — operational metrics (optimized: temp-table strategy)
-- Table: public.portfolio_kpi_update_log (partitioned on message_created_at)
--
-- Python runner (uses .env; sets the same session params + builds temp tables automatically):
--   python portfolio_kpi_metrics_postgres.py --start "2026-05-20 00:00:00" --end "2026-05-21 00:00:00" --report all
--
-- DBeaver: run PARAMS once, then run the SETUP block once, then run any REPORT.
-- Sections are tagged with:  -- SETUP: <name>   and   -- REPORT: <name>

-- =============================================================================
-- PARAMS — edit ONLY these three values, then Execute once per session.
-- =============================================================================
SELECT
  set_config('portfolio_kpi.window_start', '2026-05-20 00:00:00', false),
  set_config('portfolio_kpi.window_end',   '2026-05-21 00:00:00', false),
  set_config('portfolio_kpi.source_filter', '', false);
-- window_start  : inclusive lower bound (timestamp text)
-- window_end    : exclusive upper bound (timestamp text)
-- source_filter : '' = all sources; else e.g. 'Custom Financials' (scopes the WHOLE run)

-- =============================================================================
-- SETUP: build_temp
-- Materialize the windowed slice ONCE (source extracted to a plain column,
-- entity array pre-unnested), so every report below is a cheap temp-table scan.
-- Run this ONCE per session (after PARAMS). Re-running rebuilds the temp tables.
-- =============================================================================
DROP TABLE IF EXISTS tmp_kpi_entity;
DROP TABLE IF EXISTS tmp_kpi_window;

CREATE TEMP TABLE tmp_kpi_window AS
WITH params AS (
  SELECT
    current_setting('portfolio_kpi.window_start')::timestamp AS start_ts,
    current_setting('portfolio_kpi.window_end')::timestamp   AS end_ts,
    NULLIF(TRIM(current_setting('portfolio_kpi.source_filter')), '')::text AS source_filter
)
SELECT
  l.id,
  l.message_created_at,
  l.message_id,
  l.portfolio_id,
  COALESCE(l.status, '(null)')                             AS status,
  COALESCE(l.entity_refresh_message->>'source', '(null)')  AS source,
  l.entity_refresh_message->>'group'                       AS "group",
  date_trunc('day', l.message_created_at)::date            AS day,
  l.message_received_at,
  l.processing_started_at,
  l.processing_completed_at,
  l.duration_seconds,
  CASE
    WHEN l.processing_started_at IS NOT NULL
     AND l.processing_completed_at IS NOT NULL
     AND l.processing_completed_at >= l.processing_started_at
    THEN ROUND(EXTRACT(EPOCH FROM (l.processing_completed_at - l.processing_started_at))::numeric, 3)
  END AS process_seconds_computed,
  CASE
    WHEN l.processing_started_at IS NOT NULL
     AND l.message_received_at IS NOT NULL
    THEN ROUND(EXTRACT(EPOCH FROM (l.processing_started_at - l.message_received_at))::numeric, 3)
  END AS queue_wait_seconds,
  l.triggering_entity_external_ids,
  l.entity_refresh_message
FROM public.portfolio_kpi_update_log l
CROSS JOIN params p
WHERE l.message_created_at >= p.start_ts
  AND l.message_created_at <  p.end_ts
  AND (p.source_filter IS NULL OR l.entity_refresh_message->>'source' = p.source_filter);

CREATE INDEX ON tmp_kpi_window (source);
CREATE INDEX ON tmp_kpi_window (day);
CREATE INDEX ON tmp_kpi_window (status);
ANALYZE tmp_kpi_window;

CREATE TEMP TABLE tmp_kpi_entity AS
SELECT
  w.day,
  w.portfolio_id,
  w.source,
  w.status,
  entity_id
FROM tmp_kpi_window w
CROSS JOIN LATERAL unnest(w.triggering_entity_external_ids) AS entity_id
WHERE w.triggering_entity_external_ids IS NOT NULL
  AND cardinality(w.triggering_entity_external_ids) > 0;

CREATE INDEX ON tmp_kpi_entity (source);
CREATE INDEX ON tmp_kpi_entity (day);
CREATE INDEX ON tmp_kpi_entity (entity_id);
CREATE INDEX ON tmp_kpi_entity (portfolio_id);
ANALYZE tmp_kpi_entity;

-- =============================================================================
-- REPORT: daily_totals_source
-- Message counts per day, broken down by source.
-- =============================================================================
SELECT
  day,
  source,
  COUNT(*) AS message_count
FROM tmp_kpi_window
GROUP BY day, source
ORDER BY day, source;

-- =============================================================================
-- REPORT: hourly_totals
-- Messages received per hour vs processed per hour, broken down by source.
-- =============================================================================
WITH received AS (
  SELECT date_trunc('hour', message_received_at) AS hour_utc, source,
         COUNT(*) AS messages_received
  FROM tmp_kpi_window
  WHERE message_received_at IS NOT NULL
    AND message_received_at >= current_setting('portfolio_kpi.window_start')::timestamp
    AND message_received_at <  current_setting('portfolio_kpi.window_end')::timestamp
  GROUP BY 1, 2
),
processed AS (
  SELECT date_trunc('hour', processing_completed_at) AS hour_utc, source,
         COUNT(*) AS messages_processed
  FROM tmp_kpi_window
  WHERE processing_completed_at IS NOT NULL
    AND processing_completed_at >= current_setting('portfolio_kpi.window_start')::timestamp
    AND processing_completed_at <  current_setting('portfolio_kpi.window_end')::timestamp
  GROUP BY 1, 2
)
SELECT
  COALESCE(r.hour_utc, p.hour_utc) AS hour_utc,
  COALESCE(r.source, p.source)     AS source,
  COALESCE(r.messages_received, 0)  AS messages_received,
  COALESCE(p.messages_processed, 0) AS messages_processed
FROM received r
FULL OUTER JOIN processed p ON p.hour_utc = r.hour_utc AND p.source = r.source
ORDER BY hour_utc, source;

-- =============================================================================
-- REPORT: hourly_by_status
-- Messages received vs processed per hour, broken down by status.
-- =============================================================================
WITH received AS (
  SELECT date_trunc('hour', message_received_at) AS hour_utc, status,
         COUNT(*) AS messages_received
  FROM tmp_kpi_window
  WHERE message_received_at IS NOT NULL
    AND message_received_at >= current_setting('portfolio_kpi.window_start')::timestamp
    AND message_received_at <  current_setting('portfolio_kpi.window_end')::timestamp
  GROUP BY 1, 2
),
processed AS (
  SELECT date_trunc('hour', processing_completed_at) AS hour_utc, status,
         COUNT(*) AS messages_processed
  FROM tmp_kpi_window
  WHERE processing_completed_at IS NOT NULL
    AND processing_completed_at >= current_setting('portfolio_kpi.window_start')::timestamp
    AND processing_completed_at <  current_setting('portfolio_kpi.window_end')::timestamp
  GROUP BY 1, 2
)
SELECT
  COALESCE(r.hour_utc, p.hour_utc) AS hour_utc,
  COALESCE(r.status, p.status)     AS status,
  COALESCE(r.messages_received, 0)  AS messages_received,
  COALESCE(p.messages_processed, 0) AS messages_processed
FROM received r
FULL OUTER JOIN processed p ON p.hour_utc = r.hour_utc AND p.status = r.status
ORDER BY hour_utc, status;

-- =============================================================================
-- REPORT: status_summary
-- Row counts by status in the window.
-- =============================================================================
SELECT
  status,
  COUNT(*) AS row_count
FROM tmp_kpi_window
GROUP BY status
ORDER BY row_count DESC;

-- =============================================================================
-- REPORT: source_update_totals
-- Total updates and distinct portfolios per source.
-- =============================================================================
SELECT
  source,
  COUNT(*) AS total_updates,
  COUNT(DISTINCT portfolio_id) AS portfolios_updated,
  MIN(message_created_at) AS first_update_at,
  MAX(message_created_at) AS last_update_at
FROM tmp_kpi_window
GROUP BY source
ORDER BY total_updates DESC, source;

-- =============================================================================
-- REPORT: portfolio_updates_by_source
-- Update count per portfolio, broken down by source.
-- =============================================================================
SELECT
  portfolio_id,
  source,
  COUNT(*) AS update_count,
  MIN(message_created_at) AS first_update_at,
  MAX(message_created_at) AS last_update_at
FROM tmp_kpi_window
GROUP BY portfolio_id, source
ORDER BY portfolio_id, source;

-- =============================================================================
-- REPORT: portfolio_update_totals
-- Total update count per portfolio (all sources).
-- =============================================================================
SELECT
  portfolio_id,
  COUNT(*) AS update_count
FROM tmp_kpi_window
GROUP BY portfolio_id
ORDER BY update_count DESC, portfolio_id;

-- =============================================================================
-- REPORT: entity_source_totals
-- Entity triggers per source (array unnested): totals only.
-- =============================================================================
SELECT
  source,
  COUNT(*) AS entity_trigger_count,
  COUNT(DISTINCT entity_id) AS distinct_entities,
  COUNT(DISTINCT portfolio_id) AS portfolios_affected
FROM tmp_kpi_entity
GROUP BY source
ORDER BY entity_trigger_count DESC, source;

-- =============================================================================
-- REPORT: triggering_entity_counts
-- Per-entity trigger counts, broken down by source.
-- =============================================================================
SELECT
  entity_id,
  source,
  COUNT(*) AS trigger_count,
  COUNT(DISTINCT portfolio_id) AS portfolios_affected
FROM tmp_kpi_entity
GROUP BY entity_id, source
ORDER BY trigger_count DESC, entity_id, source;

-- =============================================================================
-- REPORT: triggering_entity_counts_by_day
-- Entity triggers per day, broken down by source.
-- =============================================================================
SELECT
  day,
  source,
  COUNT(*) AS entity_trigger_count,
  COUNT(DISTINCT entity_id) AS distinct_entities,
  COUNT(DISTINCT portfolio_id) AS portfolios_affected
FROM tmp_kpi_entity
GROUP BY day, source
ORDER BY day, source;

-- =============================================================================
-- REPORT: entities_by_day_source_status
-- Entity triggers per day, per source, per status.
-- =============================================================================
SELECT
  day,
  source,
  status,
  COUNT(*) AS entity_trigger_count,
  COUNT(DISTINCT entity_id) AS distinct_entities,
  COUNT(DISTINCT portfolio_id) AS portfolios_affected
FROM tmp_kpi_entity
GROUP BY day, source, status
ORDER BY day, source, status;

-- =============================================================================
-- REPORT: portfolios_by_day_source_status
-- Portfolio refreshes (messages) per day, per source, per status.
-- =============================================================================
SELECT
  day,
  source,
  status,
  COUNT(*) AS message_count,
  COUNT(DISTINCT portfolio_id) AS distinct_portfolios
FROM tmp_kpi_window
GROUP BY day, source, status
ORDER BY day, source, status;

-- =============================================================================
-- REPORT: entity_by_source
-- Long form: how many times each entity was refreshed, per source.
-- =============================================================================
SELECT
  entity_id,
  source,
  COUNT(*) AS refresh_count
FROM tmp_kpi_entity
GROUP BY entity_id, source
ORDER BY entity_id, source;

-- =============================================================================
-- REPORT: portfolio_entity_source
-- Long form: how many times each (portfolio, entity) pair was refreshed, per source.
-- =============================================================================
SELECT
  portfolio_id,
  entity_id,
  source,
  COUNT(*) AS refresh_count
FROM tmp_kpi_entity
GROUP BY portfolio_id, entity_id, source
ORDER BY portfolio_id, entity_id, source;

-- =============================================================================
-- REPORT: slow_global
-- Completed messages slower than global P95 processing time in the window.
-- =============================================================================
WITH completed AS (
  SELECT
    id, message_created_at, message_id, portfolio_id, status, source, "group",
    entity_refresh_message, triggering_entity_external_ids,
    message_received_at, processing_started_at, processing_completed_at,
    process_seconds_computed,
    duration_seconds AS process_seconds_stored,
    queue_wait_seconds
  FROM tmp_kpi_window
  WHERE process_seconds_computed IS NOT NULL
),
baseline AS (
  SELECT
    COUNT(*) AS sample_size,
    ROUND(AVG(process_seconds_computed)::numeric, 3) AS avg_process_sec,
    ROUND((PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY process_seconds_computed))::numeric, 3) AS median_process_sec,
    ROUND((PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY process_seconds_computed))::numeric, 3) AS p95_process_sec,
    ROUND((PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY process_seconds_computed))::numeric, 3) AS p99_process_sec
  FROM completed
)
SELECT
  c.id, c.message_created_at, c.message_id, c.portfolio_id, c.status, c.source, c."group",
  c.entity_refresh_message, c.triggering_entity_external_ids,
  c.message_received_at, c.processing_started_at, c.processing_completed_at,
  c.process_seconds_computed, c.process_seconds_stored, c.queue_wait_seconds,
  b.sample_size, b.avg_process_sec, b.median_process_sec, b.p95_process_sec, b.p99_process_sec,
  ROUND((c.process_seconds_computed / NULLIF(b.median_process_sec, 0))::numeric, 2) AS times_median,
  ROUND((c.process_seconds_computed / NULLIF(b.p95_process_sec, 0))::numeric, 2) AS times_p95
FROM completed c
CROSS JOIN baseline b
WHERE c.process_seconds_computed > b.p95_process_sec
ORDER BY c.process_seconds_computed DESC;

-- =============================================================================
-- REPORT: slow_by_source
-- Slow = above P95 processing time within each source.
-- =============================================================================
WITH completed AS (
  SELECT
    id, message_created_at, message_id, portfolio_id, status, source, "group",
    entity_refresh_message, triggering_entity_external_ids,
    message_received_at, processing_started_at, processing_completed_at,
    process_seconds_computed,
    duration_seconds AS process_seconds_stored
  FROM tmp_kpi_window
  WHERE process_seconds_computed IS NOT NULL
),
baseline_by_source AS (
  SELECT
    source,
    COUNT(*) AS sample_size,
    ROUND((PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY process_seconds_computed))::numeric, 3) AS p95_process_sec
  FROM completed
  GROUP BY source
)
SELECT
  c.id, c.message_created_at, c.message_id, c.portfolio_id, c.status, c.source, c."group",
  c.entity_refresh_message, c.triggering_entity_external_ids,
  c.message_received_at, c.processing_started_at, c.processing_completed_at,
  c.process_seconds_computed, c.process_seconds_stored,
  b.sample_size, b.p95_process_sec,
  ROUND((c.process_seconds_computed / NULLIF(b.p95_process_sec, 0))::numeric, 2) AS times_source_p95
FROM completed c
JOIN baseline_by_source b ON b.source = c.source
WHERE c.process_seconds_computed > b.p95_process_sec
ORDER BY c.process_seconds_computed DESC;
