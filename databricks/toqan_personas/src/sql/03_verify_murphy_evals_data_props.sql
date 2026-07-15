-- Read-only verification for murphy_evals_data_props (run after 03_build_...).
-- Confirms the enriched table is identical to the source, with only `properties` added.
--
-- Params: :output_catalog, :output_schema, :source_table (=murphy_evals_data),
--         :props_table (=murphy_evals_data_props).

-- 1) Row/count identity: expect equal_count = true and both anti-join counts = 0.
WITH src AS (SELECT * FROM IDENTIFIER(:output_catalog||'.'||:output_schema||'.'||:source_table)),
     props AS (SELECT * FROM IDENTIFIER(:output_catalog||'.'||:output_schema||'.'||:props_table))
SELECT
  (SELECT count(*) FROM src)   AS src_rows,
  (SELECT count(*) FROM props) AS props_rows,
  (SELECT count(*) FROM src)   = (SELECT count(*) FROM props) AS equal_count,
  (SELECT count(*) FROM (
     SELECT conversation_id, session_id, event_count FROM src
     EXCEPT
     SELECT conversation_id, session_id, event_count FROM props)) AS src_minus_props,
  (SELECT count(*) FROM (
     SELECT conversation_id, session_id, event_count FROM props
     EXCEPT
     SELECT conversation_id, session_id, event_count FROM src)) AS props_minus_src;

-- 2) Per-session event identity: expect mismatched_sessions = 0.
--    Compares the sorted multiset of event_id per (conversation_id, session_id).
WITH src_ev AS (
  SELECT conversation_id, session_id,
         sort_array(collect_list(e.event_id)) AS ids
  FROM IDENTIFIER(:output_catalog||'.'||:output_schema||'.'||:source_table)
  LATERAL VIEW explode(events) t AS e
  GROUP BY conversation_id, session_id
),
props_ev AS (
  SELECT conversation_id, session_id,
         sort_array(collect_list(e.event_id)) AS ids
  FROM IDENTIFIER(:output_catalog||'.'||:output_schema||'.'||:props_table)
  LATERAL VIEW explode(events) t AS e
  GROUP BY conversation_id, session_id
)
SELECT count(*) AS mismatched_sessions
FROM src_ev s
FULL OUTER JOIN props_ev p
  ON s.conversation_id = p.conversation_id AND s.session_id = p.session_id
WHERE NOT (
  size(array_except(s.ids, p.ids)) = 0
  AND size(array_except(p.ids, s.ids)) = 0
);

-- 3) Coverage sanity (not a gate): % of events with non-null properties per event_name.
SELECT
  e.event_name,
  count(*) AS events,
  sum(CASE WHEN e.properties IS NOT NULL THEN 1 ELSE 0 END) AS with_props,
  round(100.0 * sum(CASE WHEN e.properties IS NOT NULL THEN 1 ELSE 0 END) / count(*), 1) AS pct_with_props
FROM IDENTIFIER(:output_catalog||'.'||:output_schema||'.'||:props_table)
LATERAL VIEW explode(events) t AS e
GROUP BY e.event_name
ORDER BY events DESC;
