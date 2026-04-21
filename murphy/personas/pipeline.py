"""Persona pipeline orchestrator — ties PostHog data fetching, discovery, and scoring together.

Top-level entry point: :func:`run_persona_pipeline`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from browser_use.tokens.service import TokenCost
from murphy.config import (
	PERSONA_DISCOVERY_SESSIONS,
	PERSONA_LLM_CONCURRENCY,
	PERSONA_MAX_CLUSTERS,
	PERSONA_MIN_EVENTS,
	PERSONA_MONTHS_BACK,
	PERSONA_NUM_CLUSTERS,
	PERSONA_SCORING_SESSIONS,
	POSTHOG_API_KEY,
	POSTHOG_HOST,
	POSTHOG_PROJECT_ID,
)
from murphy.llm import create_llm
from murphy.models import TokenUsage
from murphy.personas.clustering import cluster_sessions
from murphy.personas.compressor import compress_session
from murphy.personas.discovery import run_discovery
from murphy.personas.models import AnalyticsSession
from murphy.personas.persona_labeling import build_persona_result, label_personas
from murphy.personas.pipeline_models import PersonaResult, SessionScore, TraitSchema
from murphy.personas.posthog_adapter import PostHogAdapter
from murphy.personas.posthog_client import PostHogClient
from murphy.personas.scoring import run_scoring

logger = logging.getLogger(__name__)

PERSON_BATCH_SIZE = 200


async def fetch_person_contexts(
	client: PostHogClient,
	user_ids: list[str],
) -> dict[str, dict[str, Any]]:
	"""Fetch person properties for a batch of user IDs (distinct_ids).

	Returns dict mapping distinct_id -> {created_at, initial_referring_domain, ...}.

	Uses a HogQL join on person_distinct_ids + persons since the existing
	fetch_persons() method cannot filter by distinct_id.
	"""
	if not user_ids:
		return {}

	result: dict[str, dict[str, Any]] = {}

	for i in range(0, len(user_ids), PERSON_BATCH_SIZE):
		batch = user_ids[i : i + PERSON_BATCH_SIZE]
		escaped = ', '.join(f"'{uid}'" for uid in batch)
		query = (
			f'SELECT'
			f' pdi.distinct_id,'
			f' p.created_at,'
			f' p.properties.$initial_referring_domain as initial_ref'
			f' FROM person_distinct_ids pdi'
			f' JOIN persons p ON pdi.person_id = p.id'
			f' WHERE pdi.distinct_id IN ({escaped})'
		)
		rows = await client.query(query)
		columns = rows.get('columns', [])
		for row in rows.get('results', []):
			row_dict = dict(zip(columns, row))
			did = row_dict.get('distinct_id', '')
			if did:
				result[did] = {
					'created_at': row_dict.get('created_at'),
					'initial_referring_domain': row_dict.get('initial_ref'),
				}

	logger.info('Fetched person context for %d/%d user IDs', len(result), len(user_ids))
	return result


async def fetch_population_paths(client: PostHogClient, after: str) -> str:
	"""Run an aggregate behavioral flow query and format as text context.

	Returns a formatted string summarizing the top navigation flows for
	LLM context during trait aggregation.
	"""
	query = (
		f'SELECT'
		f' properties.$pathname as page,'
		f' count() as visits'
		f' FROM events'
		f" WHERE event = '$pageview'"
		f" AND timestamp > '{after}'"
		f' GROUP BY page'
		f' ORDER BY visits DESC'
		f' LIMIT 30'
	)

	try:
		rows = await client.query(query)
		columns = rows.get('columns', [])
		results = rows.get('results', [])
		if not results:
			return 'No aggregate flow data available.'

		lines = ['Top pages by visit count:']
		for row in results:
			row_dict = dict(zip(columns, row))
			lines.append(f'  {row_dict.get("page", "?")} — {row_dict.get("visits", 0)} visits')
		return '\n'.join(lines)
	except Exception:
		logger.warning('Failed to fetch population paths', exc_info=True)
		return 'Aggregate flow data unavailable.'


def _unique_user_ids(sessions: list[AnalyticsSession]) -> list[str]:
	seen: set[str] = set()
	result: list[str] = []
	for s in sessions:
		if s.user_id not in seen:
			seen.add(s.user_id)
			result.append(s.user_id)
	return result


def _effective_num_clusters(num_clusters: int | None) -> int | None:
	"""Resolve K for clustering.

	``0`` means automatic selection (silhouette). When the caller omits
	``num_clusters`` (``None``), use :data:`~murphy.config.PERSONA_NUM_CLUSTERS`
	(unless that is ``0``, which also means auto).
	"""
	if num_clusters == 0:
		return None
	if num_clusters is not None:
		return num_clusters
	return None if PERSONA_NUM_CLUSTERS == 0 else PERSONA_NUM_CLUSTERS


async def run_persona_pipeline(
	model: str = 'gpt-5-mini',
	provider: str = 'openai',
	discovery_sessions: int = PERSONA_DISCOVERY_SESSIONS,
	scoring_sessions: int = PERSONA_SCORING_SESSIONS,
	min_events: int = PERSONA_MIN_EVENTS,
	months_back: int = PERSONA_MONTHS_BACK,
	max_concurrent: int = PERSONA_LLM_CONCURRENCY,
	max_clusters: int = PERSONA_MAX_CLUSTERS,
	num_clusters: int | None = None,
) -> tuple[TraitSchema, list[SessionScore], PersonaResult, str | None, TokenUsage]:
	"""Run the full persona discovery, scoring, and clustering pipeline.

	1. Fetch discovery sessions from PostHog.
	2. Enrich with person properties and population paths.
	3. Run Phase 1 discovery -> TraitSchema.
	4. Fetch scoring sessions (distinct from discovery via offset).
	5. Enrich scoring sessions with person properties.
	6. Run Phase 2 scoring -> list[SessionScore].
	7. Run Phase 3 clustering -> PersonaResult.

	Returns ``(schema, scores, persona_result, discovery_timeline_sample, token_usage)``.
	"""
	async with PostHogClient(
		api_key=POSTHOG_API_KEY,
		project_id=POSTHOG_PROJECT_ID,
		host=POSTHOG_HOST,
	) as client:
		adapter = PostHogAdapter(client)
		llm = create_llm(model, provider=provider)

		token_cost = TokenCost()
		token_cost.register_llm(llm)

		after_date = datetime.now(tz=timezone.utc) - timedelta(days=months_back * 30)
		after_iso = after_date.strftime('%Y-%m-%d %H:%M:%S')

		# Phase 1: Discovery
		logger.info('Fetching %d sessions for discovery (after=%s)', discovery_sessions, after_iso)
		disc_sessions = await adapter.get_sessions(
			num_sessions=discovery_sessions,
			min_events=min_events,
			after=after_iso,
			offset=0,
		)
		logger.info('Got %d discovery sessions', len(disc_sessions))

		disc_user_ids = _unique_user_ids(disc_sessions)
		person_contexts = await fetch_person_contexts(client, disc_user_ids)

		population_paths = await fetch_population_paths(client, after_iso)

		discovery_timeline_sample: str | None = None
		if disc_sessions:
			first = disc_sessions[0]
			discovery_timeline_sample = compress_session(
				first,
				person_contexts.get(first.user_id),
			)

		schema = await run_discovery(
			llm,
			disc_sessions,
			person_contexts,
			population_paths=population_paths,
			max_concurrent=max_concurrent,
		)

		# Phase 2: Scoring
		logger.info('Fetching %d sessions for scoring (offset=%d)', scoring_sessions, discovery_sessions)
		score_sessions = await adapter.get_sessions(
			num_sessions=scoring_sessions,
			min_events=min_events,
			after=after_iso,
			offset=discovery_sessions,
		)
		logger.info('Got %d scoring sessions', len(score_sessions))

		score_user_ids = _unique_user_ids(score_sessions)
		new_user_ids = [uid for uid in score_user_ids if uid not in person_contexts]
		if new_user_ids:
			new_contexts = await fetch_person_contexts(client, new_user_ids)
			person_contexts.update(new_contexts)

		scores = await run_scoring(
			llm,
			schema,
			score_sessions,
			person_contexts,
			max_concurrent=max_concurrent,
		)

		# Phase 3: Clustering + Labeling
		k_clusters = _effective_num_clusters(num_clusters)
		logger.info('Clustering %d scored sessions (num_clusters=%s, max_clusters=%d)', len(scores), k_clusters, max_clusters)
		clustering = cluster_sessions(scores, schema, k=k_clusters, k_range=(2, max_clusters))

		cluster_sizes = [int((clustering.labels == i).sum()) for i in range(clustering.k)]
		labels = await label_personas(llm, schema, clustering.centroids, cluster_sizes)
		persona_result = build_persona_result(schema, scores, clustering, labels)
		logger.info(
			'Persona pipeline complete: %d personas (silhouette=%.4f)',
			persona_result.num_clusters,
			persona_result.silhouette_score,
		)

		usage = token_cost.get_usage_tokens_for_model(model)
		token_usage = TokenUsage(
			input_tokens=usage.prompt_tokens,
			output_tokens=usage.completion_tokens,
		)
		logger.info(
			'Persona discovery tokens: input=%d, output=%d',
			token_usage.input_tokens,
			token_usage.output_tokens,
		)

		return schema, scores, persona_result, discovery_timeline_sample, token_usage
