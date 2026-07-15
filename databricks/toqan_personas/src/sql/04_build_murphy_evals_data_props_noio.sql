-- I/O ablation: copy of murphy_evals_data_props with the conversation I/O removed.
--
-- Identical sessions, events, and PostHog properties as murphy_evals_data_props, but the
-- `interactions[]` array (the Toqan conversation turns = user/agent message content) is
-- emptied, and message_count is zeroed. This isolates the effect of conversation I/O:
-- personas built from this table see UI events + properties only, no I/O.
--
-- Session selection downstream is unaffected (it filters on event_count, which is unchanged),
-- so the SAME sessions are selected as for murphy_evals_data_props.
--
-- Params: :output_catalog, :output_schema, :source_table (=murphy_evals_data_props),
--         :noio_table (=murphy_evals_data_props_noio).
-- Target: toqan_analytics_internal.toqan_restaurants_evals.murphy_evals_data_props_noio

CREATE OR REPLACE TABLE IDENTIFIER(
  :output_catalog || '.' || :output_schema || '.' || :noio_table
) AS
SELECT
  conversation_id,
  session_id,
  user_email,
  session_start,
  session_end,
  event_count,                               -- unchanged -> same sessions selected
  origin_title,
  space_id,
  CAST(0 AS BIGINT) AS message_count,        -- I/O metadata zeroed
  events,                                    -- UI events + properties kept as-is
  filter(interactions, x -> false) AS interactions  -- emptied (preserves column type)
FROM IDENTIFIER(:output_catalog || '.' || :output_schema || '.' || :source_table);
