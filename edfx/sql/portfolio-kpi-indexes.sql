-- OPTIONAL performance aid for ad-hoc DBeaver queries that hit the BASE table
-- directly (public.portfolio_kpi_update_log). The Python runner does NOT need
-- this — it materializes temp tables. Run in a maintenance window.
--
-- Speeds up filtering/grouping by source, which today requires a JSONB
-- extraction on every row (the existing GIN index only helps containment @>).

-- Option A — per partition, non-blocking (repeat for each partition):
--   CREATE INDEX CONCURRENTLY IF NOT EXISTS
--     idx_<partition>_source
--     ON public.<partition_name> ((entity_refresh_message->>'source'));

-- Option B — on the partitioned parent (cascades to partitions, but takes a
-- brief lock and CANNOT be combined with CONCURRENTLY on the parent):
CREATE INDEX IF NOT EXISTS idx_portfolio_kpi_log_source
  ON public.portfolio_kpi_update_log ((entity_refresh_message->>'source'));

-- Verify:
--   SELECT indexname FROM pg_indexes
--   WHERE tablename = 'portfolio_kpi_update_log' AND indexname LIKE '%source%';
