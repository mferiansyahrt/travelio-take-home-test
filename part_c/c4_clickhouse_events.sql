-- C4 (bonus): this daily report on `events` got slow past tens of millions of rows.
--
--   SELECT toDate(created_at) d, count() FROM events WHERE event_type = 'booking' GROUP BY d
--
-- Why: the table is ORDER BY (id). The primary index is sparse and only helps filters on id, so this query
-- can't skip any granule. It reads event_type and created_at for every row, over the whole history, on every run.
-- With no date PARTITION BY there is nothing to prune either.


-- Fix 1: sort and partition the table the way it is queried.
-- ORDER BY can't be changed in place, so build a new table and swap it in.
CREATE TABLE events_v2
(
    id          UInt64,
    event_type  LowCardinality(String),
    created_at  DateTime
    -- other columns of events
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (event_type, toDate(created_at), id);

INSERT INTO events_v2 SELECT * FROM events;     -- batch per month for a large table; pause or dual-write ingestion meanwhile
EXCHANGE TABLES events AND events_v2;

-- Only if lookups by id are still needed after the new sort key:
ALTER TABLE events ADD INDEX idx_id id TYPE bloom_filter GRANULARITY 4;
ALTER TABLE events MATERIALIZE INDEX idx_id;


-- Fix 2: give the report a date range, so partitions and key ranges are skipped.
SELECT toDate(created_at) AS d, count() AS bookings
FROM events
WHERE event_type = 'booking'
  AND created_at >= today() - 90
GROUP BY d
ORDER BY d;


-- Fix 3 (dashboard that runs all day): a daily rollup kept up to date by a materialized view.
CREATE TABLE daily_event_counts
(
    d           Date,
    event_type  LowCardinality(String),
    events      UInt64
)
ENGINE = SummingMergeTree
ORDER BY (event_type, d);

CREATE MATERIALIZED VIEW daily_event_counts_mv TO daily_event_counts AS
SELECT toDate(created_at) AS d, event_type, count() AS events
FROM events
GROUP BY d, event_type;

-- The view only sees new inserts, so backfill history once, up to the moment the view was created.
INSERT INTO daily_event_counts
SELECT toDate(created_at) AS d, event_type, count() AS events
FROM events
WHERE created_at < '2026-09-15 00:00:00'        -- replace with the view's creation time
GROUP BY d, event_type;

-- sum() because SummingMergeTree merges rows in the background, not at insert time.
SELECT d, sum(events) AS bookings
FROM daily_event_counts
WHERE event_type = 'booking'
GROUP BY d
ORDER BY d;


-- Check the effect: granules selected before and after, and read_rows in system.query_log.
EXPLAIN indexes = 1
SELECT toDate(created_at) AS d, count() FROM events WHERE event_type = 'booking' GROUP BY d;
