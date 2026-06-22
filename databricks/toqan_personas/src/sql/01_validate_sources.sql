-- Sanity check: source tables exist and are non-empty.
SELECT
  'posthog_events_restaurants_pii' AS table_name,
  count(*) AS row_count,
  count(DISTINCT user_email) AS distinct_users,
  min(event_date) AS min_event_date,
  max(event_date) AS max_event_date
FROM IDENTIFIER(:source_catalog || '.' || :source_schema || '.posthog_events_restaurants_pii')

UNION ALL

SELECT
  'analytics_agents_interactions_restaurants_pii' AS table_name,
  count(*) AS row_count,
  count(DISTINCT lower(trim(user_email))) AS distinct_users,
  cast(min(message_created_at) AS date) AS min_event_date,
  cast(max(message_created_at) AS date) AS max_event_date
FROM IDENTIFIER(:source_catalog || '.' || :source_schema || '.analytics_agents_interactions_restaurants_pii')
WHERE user_email IS NOT NULL AND trim(user_email) != '';
