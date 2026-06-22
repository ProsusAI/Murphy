-- Session-grain join: one row per (conversation_id, session_id).
-- events[]     = all PostHog FE events in the session (incl. pre-chat backfill)
-- interactions[] = web messages whose message_created_at falls within session bounds
--
-- Join: ix.origin_id = ph.conversation_id (no email; 5 multi-email convos excluded)
-- Filters:
-- ix.platform_type = 'web'
-- ph.is_analytics_signal = true
--
-- Target: toqan_analytics_internal.toqan_restaurants_evals.murphy_evals_data

CREATE OR REPLACE TABLE IDENTIFIER(
  :output_catalog || '.' || :output_schema || '.' || :output_table
) AS
WITH excluded_conversations AS (
  SELECT conversation_id
  FROM (
    VALUES
      ('465014e8-26c6-4950-b3a3-f1f6e07a4014'),
      ('fa519f19-7512-41ea-a703-ec90bfca3200'),
      ('4cfdaee6-331f-4b26-bb02-65a1f98dcea4'),
      ('3181b11f-e827-4044-b807-98c3f70a5534'),
      ('3aa84695-b0c4-4aeb-969f-7f1352f18b53')
  ) AS t(conversation_id)
),
posthog AS (
  SELECT
    ph.event_id,
    ph.event_name,
    ph.event_timestamp,
    ph.event_date,
    ph.distinct_id,
    ph.user_email,
    ph.email_source,
    ph.session_id,
    ph.conversation_id,
    ph.pathname,
    ph.surface,
    ph.tab,
    ph.feedback
  FROM IDENTIFIER(:source_catalog || '.' || :source_schema || '.posthog_events_restaurants_pii') ph
  WHERE ph.is_analytics_signal = true
    AND ph.event_date >= cast(:event_date_from AS date)
    AND ph.session_id IS NOT NULL
    AND trim(ph.session_id) != ''
),
interactions AS (
  SELECT
    ix.interaction_id,
    ix.origin_id,
    lower(trim(ix.user_email)) AS user_email,
    ix.platform_type,
    ix.message_created_at,
    ix.message_completed_at,
    ix.message_text_content,
    ix.response_text_content,
    ix.full_tool_calls,
    ix.configuration.model_name AS model_name,
    ix.author.role AS author_role,
    ix.message_provided_files,
    ix.response_files,
    ix.message_language_code,
    ix.origin_title,
    ix.space_id
  FROM IDENTIFIER(:source_catalog || '.' || :source_schema || '.analytics_agents_interactions_restaurants_pii') ix
  WHERE ix.platform_type = 'web'
    AND ix.origin_id IS NOT NULL
    AND trim(ix.origin_id) != ''
    AND ix.origin_id NOT IN (SELECT conversation_id FROM excluded_conversations)
    AND ix.message_created_at >= cast(:event_date_from AS date)
),
conversation_meta AS (
  SELECT
    ix.origin_id AS conversation_id,
    any_value(ix.user_email) AS user_email,
    any_value(ix.origin_title) AS origin_title,
    any_value(ix.space_id) AS space_id
  FROM interactions ix
  GROUP BY ix.origin_id
),
valid_conversations AS (
  SELECT DISTINCT ix.origin_id AS conversation_id
  FROM interactions ix
  INNER JOIN posthog ph
    ON ix.origin_id = ph.conversation_id
),
conv_sessions AS (
  SELECT DISTINCT
    vc.conversation_id,
    ph.session_id
  FROM valid_conversations vc
  INNER JOIN posthog ph
    ON vc.conversation_id = ph.conversation_id
),
session_events AS (
  SELECT
    cs.conversation_id,
    cs.session_id,
    ph.event_id,
    ph.event_name,
    ph.event_timestamp,
    ph.conversation_id AS ph_conversation_id,
    ph.pathname,
    ph.surface,
    ph.tab,
    ph.feedback,
    ph.distinct_id,
    ph.email_source,
    ph.user_email
  FROM conv_sessions cs
  INNER JOIN posthog ph
    ON cs.session_id = ph.session_id
),
session_bounds AS (
  SELECT
    conversation_id,
    session_id,
    min(event_timestamp) AS session_start,
    max(event_timestamp) AS session_end,
    count(*) AS event_count
  FROM session_events
  GROUP BY conversation_id, session_id
),
dominant_ph_email AS (
  SELECT conversation_id, session_id, ph_user_email
  FROM (
    SELECT
      se.conversation_id,
      se.session_id,
      lower(trim(se.user_email)) AS ph_user_email,
      row_number() OVER (
        PARTITION BY se.conversation_id, se.session_id
        ORDER BY count(*) DESC, lower(trim(se.user_email))
      ) AS rn
    FROM session_events se
    WHERE se.user_email IS NOT NULL
      AND trim(se.user_email) != ''
    GROUP BY se.conversation_id, se.session_id, lower(trim(se.user_email))
  )
  WHERE rn = 1
),
events_agg AS (
  SELECT
    se.conversation_id,
    se.session_id,
    sort_array(
      collect_list(
        named_struct(
          'sort_ts', unix_timestamp(se.event_timestamp),
          'event_id', se.event_id,
          'event_name', se.event_name,
          'event_timestamp', se.event_timestamp,
          'conversation_id', se.ph_conversation_id,
          'pathname', se.pathname,
          'surface', se.surface,
          'tab', se.tab,
          'feedback', se.feedback,
          'distinct_id', se.distinct_id,
          'email_source', se.email_source,
          'ph_event_has_conversation_id', se.ph_conversation_id IS NOT NULL
        )
      )
    ) AS events_raw
  FROM session_events se
  GROUP BY se.conversation_id, se.session_id
),
interactions_agg AS (
  SELECT
    sb.conversation_id,
    sb.session_id,
    sort_array(
      collect_list(
        named_struct(
          'sort_ts', unix_timestamp(ix.message_created_at),
          'interaction_id', ix.interaction_id,
          'message_created_at', ix.message_created_at,
          'message_completed_at', ix.message_completed_at,
          'message_text_content', ix.message_text_content,
          'response_text_content', ix.response_text_content,
          'full_tool_calls', ix.full_tool_calls,
          'model_name', ix.model_name,
          'author_role', ix.author_role,
          'message_provided_files', ix.message_provided_files,
          'response_files', ix.response_files,
          'message_language_code', ix.message_language_code
        )
      )
    ) AS interactions_raw
  FROM session_bounds sb
  INNER JOIN interactions ix
    ON sb.conversation_id = ix.origin_id
    AND ix.message_created_at BETWEEN sb.session_start AND sb.session_end
  GROUP BY sb.conversation_id, sb.session_id
)
SELECT
  sb.conversation_id,
  sb.session_id,
  coalesce(cm.user_email, dpe.ph_user_email) AS user_email,
  sb.session_start,
  sb.session_end,
  sb.event_count,
  cm.origin_title,
  cm.space_id,
  coalesce(size(ia.interactions_raw), 0) AS message_count,
  transform(
    ea.events_raw,
    e -> named_struct(
      'event_id', e.event_id,
      'event_name', e.event_name,
      'event_timestamp', e.event_timestamp,
      'conversation_id', e.conversation_id,
      'pathname', e.pathname,
      'surface', e.surface,
      'tab', e.tab,
      'feedback', e.feedback,
      'distinct_id', e.distinct_id,
      'email_source', e.email_source,
      'ph_event_has_conversation_id', e.ph_event_has_conversation_id
    )
  ) AS events,
  coalesce(
    transform(
      ia.interactions_raw,
      i -> named_struct(
        'interaction_id', i.interaction_id,
        'message_created_at', i.message_created_at,
        'message_completed_at', i.message_completed_at,
        'message_text_content', i.message_text_content,
        'response_text_content', i.response_text_content,
        'full_tool_calls', i.full_tool_calls,
        'model_name', i.model_name,
        'author_role', i.author_role,
        'message_provided_files', i.message_provided_files,
        'response_files', i.response_files,
        'message_language_code', i.message_language_code
      )
    ),
    array()
  ) AS interactions
FROM session_bounds sb
INNER JOIN events_agg ea
  ON sb.conversation_id = ea.conversation_id
  AND sb.session_id = ea.session_id
LEFT JOIN interactions_agg ia
  ON sb.conversation_id = ia.conversation_id
  AND sb.session_id = ia.session_id
LEFT JOIN conversation_meta cm
  ON sb.conversation_id = cm.conversation_id
LEFT JOIN dominant_ph_email dpe
  ON sb.conversation_id = dpe.conversation_id
  AND sb.session_id = dpe.session_id;
