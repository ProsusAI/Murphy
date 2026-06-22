"""Databricks persona pipeline orchestrator — UC murphy_evals_data → personas.

Parallel to :func:`murphy.personas.pipeline.run_persona_pipeline` (PostHog-only).
Top-level entry point: :func:`run_databricks_persona_pipeline`.
"""

from __future__ import annotations

import logging
from typing import Any

from browser_use.llm import ChatOpenAI
from browser_use.tokens.service import TokenCost
from murphy.config import (
	DATABRICKS_EVENT_DATE_FROM,
	PERSONA_DISCOVERY_SESSIONS,
	PERSONA_LLM_CONCURRENCY,
	PERSONA_MAX_CLUSTERS,
	PERSONA_MIN_EVENTS,
	PERSONA_SCORING_SESSIONS,
)
from murphy.models import TokenUsage
from murphy.personas.clustering import cluster_sessions
from murphy.personas.compressor import compress_session
from murphy.personas.databricks_adapter import DatabricksAdapter
from murphy.personas.discovery import run_discovery
from murphy.personas.embedder import embed_sessions
from murphy.personas.models import AnalyticsSession
from murphy.personas.persona_labeling import build_persona_result, label_personas
from murphy.personas.pipeline import _effective_num_clusters, _unique_user_ids
from murphy.personas.pipeline_models import PersonaResult, SessionScore, TraitSchema
from murphy.personas.scoring import run_scoring

logger = logging.getLogger(__name__)


def _merge_session_contexts(adapter: DatabricksAdapter, sessions: list[AnalyticsSession]) -> dict[str, dict[str, Any]]:
	return {s.session_id: adapter.last_session_contexts.get(s.session_id, {}) for s in sessions}


def _merge_person_contexts(adapter: DatabricksAdapter, sessions: list[AnalyticsSession]) -> dict[str, dict[str, Any]]:
	result: dict[str, dict[str, Any]] = {}
	for session in sessions:
		ctx = adapter.last_person_contexts.get(session.user_id)
		if ctx:
			result[session.user_id] = ctx
	return result


async def run_databricks_persona_pipeline(
	model: str = 'gpt-5-mini',
	discovery_sessions: int = PERSONA_DISCOVERY_SESSIONS,
	scoring_sessions: int = PERSONA_SCORING_SESSIONS,
	min_events: int = PERSONA_MIN_EVENTS,
	event_date_from: str | None = None,
	max_concurrent: int = PERSONA_LLM_CONCURRENCY,
	max_clusters: int = PERSONA_MAX_CLUSTERS,
	num_clusters: int | None = None,
) -> tuple[TraitSchema, list[SessionScore], PersonaResult, str | None, TokenUsage]:
	"""Run persona discovery, scoring, and clustering from Unity Catalog murphy_evals_data.

	Returns ``(schema, scores, persona_result, discovery_timeline_sample, token_usage)``.
	"""
	date_from = event_date_from or DATABRICKS_EVENT_DATE_FROM
	adapter = DatabricksAdapter()
	llm = ChatOpenAI(model=model, temperature=0.3)

	token_cost = TokenCost()
	token_cost.register_llm(llm)

	logger.info('Fetching %d Databricks sessions for discovery (date_from=%s)', discovery_sessions, date_from)
	disc_sessions = await adapter.get_sessions(
		num_sessions=discovery_sessions,
		min_events=min_events,
		offset=0,
		event_date_from=date_from,
	)
	logger.info('Got %d discovery sessions', len(disc_sessions))

	disc_session_contexts = _merge_session_contexts(adapter, disc_sessions)
	person_contexts = _merge_person_contexts(adapter, disc_sessions)
	population_paths = await adapter.fetch_population_paths(date_from)

	discovery_timeline_sample: str | None = None
	if disc_sessions:
		first = disc_sessions[0]
		discovery_timeline_sample = compress_session(
			first,
			person_contexts.get(first.user_id),
			session_context=disc_session_contexts.get(first.session_id),
		)

	schema = await run_discovery(
		llm,
		disc_sessions,
		person_contexts,
		population_paths=population_paths,
		max_concurrent=max_concurrent,
		session_contexts=disc_session_contexts,
	)

	logger.info('Fetching %d Databricks sessions for scoring (offset=%d)', scoring_sessions, discovery_sessions)
	score_sessions = await adapter.get_sessions(
		num_sessions=scoring_sessions,
		min_events=min_events,
		offset=discovery_sessions,
		event_date_from=date_from,
	)
	logger.info('Got %d scoring sessions', len(score_sessions))

	score_session_contexts = _merge_session_contexts(adapter, score_sessions)
	score_user_ids = _unique_user_ids(score_sessions)
	for uid in score_user_ids:
		if uid not in person_contexts and uid in adapter.last_person_contexts:
			person_contexts[uid] = adapter.last_person_contexts[uid]

	scores = await run_scoring(
		llm,
		schema,
		score_sessions,
		person_contexts,
		max_concurrent=max_concurrent,
		session_contexts=score_session_contexts,
	)

	k_clusters = _effective_num_clusters(num_clusters)
	logger.info('Clustering %d scored sessions (num_clusters=%s, max_clusters=%d)', len(scores), k_clusters, max_clusters)
	clustering = cluster_sessions(scores, schema, k=k_clusters, k_range=(2, max_clusters))

	logger.info('Embedding %d scoring sessions for centroid embeddings', len(score_sessions))
	session_embeddings = await embed_sessions(
		score_sessions,
		person_contexts,
		session_contexts=score_session_contexts,
	)

	cluster_sizes = [int((clustering.labels == i).sum()) for i in range(clustering.k)]
	labels = await label_personas(llm, schema, clustering.centroids, cluster_sizes)
	persona_result = build_persona_result(schema, scores, clustering, labels, session_embeddings)
	logger.info(
		'Databricks persona pipeline complete: %d personas (silhouette=%.4f)',
		persona_result.num_clusters,
		persona_result.silhouette_score,
	)

	usage = token_cost.get_usage_tokens_for_model(model)
	token_usage = TokenUsage(
		input_tokens=usage.prompt_tokens,
		output_tokens=usage.completion_tokens,
	)
	logger.info(
		'Databricks persona discovery tokens: input=%d, output=%d',
		token_usage.input_tokens,
		token_usage.output_tokens,
	)

	return schema, scores, persona_result, discovery_timeline_sample, token_usage
