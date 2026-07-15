-- Enriched copy of murphy_evals_data with PostHog event `properties` added per event.
--
-- Reads the EXISTING murphy_evals_data (does NOT re-run 02_build), explodes events[],
-- and LEFT JOINs posthog_events_restaurants_pii by event_id to attach ONLY the
-- `properties` VARIANT (serialized to a JSON string). Re-aggregates preserving the
-- original per-event order. Every other column and event_count are carried unchanged,
-- so the row set / per-session event set is identical to the source by construction --
-- only a `properties` field is added to each event struct.
--
-- Correctness rationale: a PostHog event's properties are immutable per event_id; only
-- the *set* of events per session grows over time. Joining the live posthog table by the
-- event_ids already present in murphy_evals_data returns those events' original properties
-- and never pulls in newer events.
--
-- Params: :output_catalog, :output_schema, :source_table (=murphy_evals_data),
--         :props_table (=murphy_evals_data_props), :source_catalog, :source_schema.
-- Target: toqan_analytics_internal.toqan_restaurants_evals.murphy_evals_data_props

CREATE OR REPLACE TABLE IDENTIFIER(
  :output_catalog || '.' || :output_schema || '.' || :props_table
) AS
WITH base AS (
  SELECT *
  FROM IDENTIFIER(:output_catalog || '.' || :output_schema || '.' || :source_table)
),
-- One row per event_id (posthog event_id is not guaranteed unique upstream); pick the
-- earliest deterministically so the LEFT JOIN below cannot multiply rows.
ph_dedup AS (
  SELECT event_id, properties_json
  FROM (
    SELECT
      ph.event_id,
      to_json(ph.properties) AS properties_json,
      row_number() OVER (PARTITION BY ph.event_id ORDER BY ph.event_timestamp) AS rn
    FROM IDENTIFIER(:source_catalog || '.' || :source_schema || '.posthog_events_restaurants_pii') ph
    WHERE ph.event_id IS NOT NULL
  )
  WHERE rn = 1
),
-- Explode keeping the original array index so ordering is preserved exactly.
exploded AS (
  SELECT
    b.conversation_id,
    b.session_id,
    e.pos AS idx,
    e.ev  AS ev
  FROM base b
  LATERAL VIEW posexplode(b.events) e AS pos, ev
),
joined AS (
  SELECT
    x.conversation_id,
    x.session_id,
    x.idx,
    named_struct(
      'event_id', x.ev.event_id,
      'event_name', x.ev.event_name,
      'event_timestamp', x.ev.event_timestamp,
      'conversation_id', x.ev.conversation_id,
      'pathname', x.ev.pathname,
      'surface', x.ev.surface,
      'tab', x.ev.tab,
      'feedback', x.ev.feedback,
      'distinct_id', x.ev.distinct_id,
      'email_source', x.ev.email_source,
      'ph_event_has_conversation_id', x.ev.ph_event_has_conversation_id,
      'properties', pd.properties_json  -- NEW: JSON string serialized from the VARIANT
    ) AS ev
  FROM exploded x
  LEFT JOIN ph_dedup pd
    ON x.ev.event_id = pd.event_id
),
enriched_events AS (
  SELECT
    conversation_id,
    session_id,
    transform(
      array_sort(
        collect_list(named_struct('idx', idx, 'ev', ev)),
        (l, r) -> CASE WHEN l.idx < r.idx THEN -1 WHEN l.idx > r.idx THEN 1 ELSE 0 END
      ),
      s -> s.ev
    ) AS events
  FROM joined
  GROUP BY conversation_id, session_id
)
SELECT
  b.conversation_id,
  b.session_id,
  b.user_email,
  b.session_start,
  b.session_end,
  b.event_count,          -- carried, never recomputed
  b.origin_title,
  b.space_id,
  b.message_count,
  ee.events,              -- enriched with properties
  b.interactions          -- untouched
FROM base b
INNER JOIN enriched_events ee
  ON b.conversation_id = ee.conversation_id
  AND b.session_id = ee.session_id;
