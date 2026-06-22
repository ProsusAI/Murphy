# Murphy evals data — Databricks DAB bundle

Builds the joined eval dataset in Unity Catalog. **All data stays in Databricks** —
no local parquet exports, no downloads.

## Tables

### Sources (read-only)

| Table | Role |
|-------|------|
| `toqan_analytics_internal.toqan_restaurants_pii.posthog_events_restaurants_pii` | PostHog FE events |
| `toqan_analytics_internal.toqan_restaurants_pii.analytics_agents_interactions_restaurants_pii` | Toqan agent interactions |

### Output (created by this bundle)

| Table | Full path |
|-------|-----------|
| **`murphy_evals_data`** | `toqan_analytics_internal.toqan_restaurants_evals.murphy_evals_data` |

## Output grain

**One row per `(conversation_id, session_id)`** — matches Murphy's session-based persona pipeline.

| Column | Description |
|--------|-------------|
| `conversation_id` | Toqan conversation / interaction `origin_id` |
| `session_id` | PostHog browser session |
| `user_email` | From interactions; fallback to dominant PostHog email in session |
| `session_start`, `session_end` | min/max `event_timestamp` in session |
| `event_count` | Number of PostHog events in session |
| `origin_title` | Conversation title from interactions |
| `space_id` | Restaurant workspace |
| `message_count` | Size of `interactions[]` |
| `events` | Array of PostHog FE events (sorted by time), incl. pre-chat backfill |
| `interactions` | Array of web messages within session time window (sorted by time) |

### `events[]` struct fields

`event_id`, `event_name`, `event_timestamp`, `conversation_id`, `pathname`, `surface`,
`tab`, `feedback`, `distinct_id`, `email_source`, `ph_event_has_conversation_id`

### `interactions[]` struct fields

`interaction_id`, `message_created_at`, `message_completed_at`, `message_text_content`,
`response_text_content`, `full_tool_calls`, `model_name`, `author_role`,
`message_provided_files`, `response_files`, `message_language_code`

## Join logic

1. **Valid conversations** — web interactions joined to PostHog on `origin_id = conversation_id`
2. **Session collection** — distinct `session_id` from PostHog rows with that `conversation_id`
3. **Session backfill** — all PostHog events in those sessions (incl. rows with null `conversation_id`)
4. **Session-windowed interactions** — messages where `message_created_at` is between `session_start` and `session_end`

| Rule | Value |
|------|-------|
| Join key | `ix.origin_id = ph.conversation_id` (no email) |
| Interaction filter | `ix.platform_type = 'web'` |
| PostHog filter | `ph.is_analytics_signal = true` |
| Date filter | `event_date_from` job param on PostHog `event_date` and interactions `message_created_at` |
| Min events | None — all sessions included regardless of event count |

### Excluded conversations (multi-email PostHog artifact)

These 5 `conversation_id`s are excluded from the join:

- `465014e8-26c6-4950-b3a3-f1f6e07a4014`
- `fa519f19-7512-41ea-a703-ec90bfca3200`
- `4cfdaee6-331f-4b26-bb02-65a1f98dcea4`
- `3181b11f-e827-4044-b807-98c3f70a5534`
- `3aa84695-b0c4-4aeb-969f-7f1352f18b53`

## Compute

All tasks are **`sql_task`** jobs on a **serverless SQL warehouse** (configured via
`warehouse_id` lookup in `databricks.yml`). No classic job clusters, no local compute.

Update the warehouse name in `databricks.yml`:

```yaml
warehouse_id:
  lookup:
    warehouse: <your-serverless-warehouse-name>
```

List warehouses: `databricks warehouses list --profile <PROFILE>`

## Prerequisites

1. Databricks CLI ≥ 0.292.0
2. CLI profile with:
   - `SELECT` on both source tables in `toqan_restaurants_pii`
   - `USE CATALOG` / `USE SCHEMA` / `CREATE TABLE` on `toqan_restaurants_evals`
3. Schema `toqan_analytics_internal.toqan_restaurants_evals` must exist
4. Set `workspace.profile` in `databricks.yml`

## Deploy and run

```bash
cd databricks/toqan_personas

databricks bundle validate --strict --target dev --profile <PROFILE>
databricks bundle deploy -t dev --profile <PROFILE>
databricks bundle run murphy_evals_data -t dev --profile <PROFILE>
```

Run with a custom date filter:

```bash
databricks bundle run murphy_evals_data -t dev --profile <PROFILE> \
  --params event_date_from=2026-05-01
```

## Verify in Databricks

```sql
-- Row count (expect low thousands, not event-level hundreds of thousands)
SELECT count(*) FROM toqan_analytics_internal.toqan_restaurants_evals.murphy_evals_data;

-- Grain check: no duplicate (conversation_id, session_id)
SELECT conversation_id, session_id, count(*) AS n
FROM toqan_analytics_internal.toqan_restaurants_evals.murphy_evals_data
GROUP BY 1, 2
HAVING n > 1;

-- Backfill: some events have null conversation_id (pre-chat navigation)
SELECT count(*)
FROM toqan_analytics_internal.toqan_restaurants_evals.murphy_evals_data
WHERE exists(events, e -> e.conversation_id IS NULL);

-- Session-windowing: messages must fall within session bounds
SELECT *
FROM toqan_analytics_internal.toqan_restaurants_evals.murphy_evals_data
WHERE message_count > 0
  AND exists(
    interactions,
    i -> i.message_created_at < session_start OR i.message_created_at > session_end
  );
-- expect 0 rows

-- Sample row
SELECT conversation_id, session_id, event_count, message_count, origin_title
FROM toqan_analytics_internal.toqan_restaurants_evals.murphy_evals_data
LIMIT 5;
```

## Job tasks

```
validate_sources  →  build_murphy_evals_data
```

| Task | SQL file | Purpose |
|------|----------|---------|
| `validate_sources` | `01_validate_sources.sql` | Row counts on both source tables |
| `build_murphy_evals_data` | `02_build_murphy_evals_data.sql` | CREATE OR REPLACE output table |

## Repo layout

```
Murphy/
└── databricks/toqan_personas/     ← this bundle (versioned in git)
    ├── databricks.yml             ← catalog/schema/table vars, serverless warehouse
    ├── resources/
    │   └── murphy_evals_data.job.yml
    └── src/sql/
        ├── 01_validate_sources.sql
        └── 02_build_murphy_evals_data.sql
```

Murphy will read from UC directly (future `DatabricksAdapter`) — not from local files.

## Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `source_catalog` | `toqan_analytics_internal` | Source UC catalog |
| `source_schema` | `toqan_restaurants_pii` | Source schema |
| `output_catalog` | `toqan_analytics_internal` | Output UC catalog |
| `output_schema` | `toqan_restaurants_evals` | Output schema |
| `output_table` | `murphy_evals_data` | Output table name |
| `event_date_from` | `2026-05-01` | Job param — filter PostHog `event_date` and interactions `message_created_at` |

## Next steps

1. Wire Murphy persona pipeline to query UC via `DatabricksAdapter` (no local export)
2. Apply `PERSONA_MIN_EVENTS` filter at read time when sampling sessions for discovery/scoring
