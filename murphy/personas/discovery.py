# Copyright © 2026 MIH AI B.V.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Phase 1 — Discovery: observe sessions and cluster into a trait schema.

Two steps:
1. Per-session observation (concurrent LLM calls, semaphore-limited).
2. Embedding-based clustering of observed traits into canonical dimensions,
   with a per-cluster LLM call to name each dimension.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.cluster import KMeans

from browser_use.llm import BaseChatModel, SystemMessage, UserMessage
from murphy.config import EMBEDDING_DEVICE, EMBEDDING_MODEL
from murphy.personas.clustering import find_optimal_k
from murphy.personas.compressor import compress_session
from murphy.personas.models import AnalyticsSession
from murphy.personas.pipeline_models import SessionObservation, TraitDimension, TraitSchema

logger = logging.getLogger(__name__)

# ── Prompts ──────────────────────────────────────────────────────────────────

OBSERVE_SYSTEM = """\
You are a behavioral analyst studying user sessions on a web application.
You will receive a compressed timeline of a single user session including
metadata, navigation patterns, cognitive signals, and a sequence of events.

Your job is to identify and describe behavioral characteristics of this
user. Think in terms of personality-like traits that describe who this user
is — for example, are they patient or impatient? Methodical or impulsive?
Confident or hesitant? These are just examples; let the data guide you to
whatever characteristics are actually present.

Be specific and grounded in the data. Do not speculate beyond what the
timeline shows."""

OBSERVE_USER = """\
Analyze this session timeline and identify the behavioral traits you observe.

{timeline}"""

CLUSTER_NAME_SYSTEM = """\
You are a behavioral scientist naming a trait dimension for user personas.

You will receive a cluster of related behavioral trait labels that were
observed across multiple user sessions and grouped by semantic similarity.

Your job is to synthesize these related traits into a single canonical
trait dimension. The dimension should read like a personality trait — e.g.
"Patience" (low = rage-clicks and abandons quickly, high = waits calmly
through delays and retries deliberately) rather than an abstract metric
like "Engagement Depth."

The dimension must:
- Describe a user characteristic, not a product metric
- Be observable from session event data (not speculative)
- Have clear low (1) and high (5) anchors framed as opposing behaviors
- Be useful for distinguishing different user personas
- Include a "why_chosen" field: 1-3 sentences explaining why these traits
  cluster together and why the resulting dimension is meaningful"""

CLUSTER_NAME_USER = """\
The following behavioral traits were observed across user sessions and
clustered together by semantic similarity. Synthesize them into one
canonical trait dimension with a name, description, and low/high anchors.

Trait labels in this cluster:
{trait_list}
{paths_block}"""

EMBEDDING_INSTRUCTION = (
	'Classify this behavioral trait for clustering with semantically similar '
	'user behavior traits observed in web application sessions'
)


# ── LLM calls ────────────────────────────────────────────────────────────────


async def observe_session(llm: BaseChatModel, timeline: str, session_id: str) -> SessionObservation:
	"""Ask the LLM to freely describe behavioral traits observed in one session."""
	response = await llm.ainvoke(
		messages=[
			SystemMessage(content=OBSERVE_SYSTEM),
			UserMessage(content=OBSERVE_USER.format(timeline=timeline)),
		],
		output_format=SessionObservation,
	)
	observation: SessionObservation = response.completion
	if not observation.session_id:
		observation.session_id = session_id
	return observation


# ── Embedding + clustering ───────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _get_embedding_model() -> SentenceTransformer:
	"""Lazy-load and cache the sentence-transformer embedding model."""
	logger.info('Loading embedding model %s on device=%s', EMBEDDING_MODEL, EMBEDDING_DEVICE)
	return SentenceTransformer(EMBEDDING_MODEL, device=EMBEDDING_DEVICE)


def _embed_traits_sync(traits: list[str]) -> np.ndarray:
	"""Embed trait strings using a local sentence-transformer model. Returns (N, dim) array."""
	model = _get_embedding_model()
	formatted = [f'Instruct: {EMBEDDING_INSTRUCTION}\nQuery: {t}' for t in traits]
	embeddings = model.encode(formatted, normalize_embeddings=True, show_progress_bar=False)
	return np.array(embeddings, dtype=np.float64)


async def _embed_traits(traits: list[str]) -> np.ndarray:
	"""Embed trait strings using a local sentence-transformer model. Returns (N, dim) array."""
	return await asyncio.to_thread(_embed_traits_sync, traits)


def _deduplicate_traits(observations: list[SessionObservation]) -> list[str]:
	"""Collect and case-insensitively deduplicate trait strings across all observations."""
	seen: set[str] = set()
	unique: list[str] = []
	for obs in observations:
		for trait in obs.observed_traits:
			key = trait.strip().lower()
			if key and key not in seen:
				seen.add(key)
				unique.append(trait.strip())
	return unique


async def _name_cluster(
	llm: BaseChatModel,
	cluster_traits: list[str],
	population_paths: str | None = None,
) -> TraitDimension:
	"""Use the LLM to name a single trait dimension from its cluster members."""
	trait_list = '\n'.join(f'- {t}' for t in cluster_traits)
	paths_block = f'\n=== Aggregate Navigation Flows (population-level) ===\n{population_paths}' if population_paths else ''

	response = await llm.ainvoke(
		messages=[
			SystemMessage(content=CLUSTER_NAME_SYSTEM),
			UserMessage(
				content=CLUSTER_NAME_USER.format(
					trait_list=trait_list,
					paths_block=paths_block,
				)
			),
		],
		output_format=TraitDimension,
	)
	return response.completion


async def cluster_trait_dimensions(
	llm: BaseChatModel,
	observations: list[SessionObservation],
	population_paths: str | None = None,
	k_range: tuple[int, int] = (4, 10),
) -> TraitSchema:
	"""Cluster observed traits into canonical dimensions via embedding similarity.

	1. Deduplicate trait strings across all observations.
	2. Embed via local Qwen3-Embedding model (instruction-aware).
	3. Find optimal k with silhouette sweep (reuses find_optimal_k from clustering.py).
	4. K-Means cluster with best k.
	5. LLM-name each cluster into a TraitDimension.
	"""
	traits = _deduplicate_traits(observations)
	if not traits:
		return TraitSchema(dimensions=[], rationale='No traits observed.')

	logger.info('Embedding %d unique traits for dimension clustering', len(traits))
	embeddings = await _embed_traits(traits)

	n = embeddings.shape[0]
	lo = max(k_range[0], 2)
	hi = min(k_range[1], n - 1)

	if n <= lo:
		best_k = n
		sil_scores: dict[int, float] = {}
	else:
		best_k, sil_scores = find_optimal_k(embeddings, k_range=(lo, hi))

	logger.info(
		'Trait dimension clustering: best_k=%d (silhouette scores: %s)',
		best_k,
		{k: f'{v:.4f}' for k, v in sil_scores.items()},
	)

	km = KMeans(n_clusters=best_k, n_init=10, random_state=42)  # type: ignore[arg-type]
	labels = km.fit_predict(embeddings)

	cluster_groups: dict[int, list[str]] = {}
	for trait, label in zip(traits, labels):
		cluster_groups.setdefault(int(label), []).append(trait)

	dimensions = await asyncio.gather(*[_name_cluster(llm, cluster_groups[c], population_paths) for c in sorted(cluster_groups)])

	rationale = (
		f'Clustered {len(traits)} unique traits into {best_k} dimensions '
		f'via embedding similarity (silhouette sweep over k={lo}..{hi}).'
	)
	return TraitSchema(dimensions=list(dimensions), rationale=rationale)


# ── Orchestrator ─────────────────────────────────────────────────────────────


async def run_discovery(
	llm: BaseChatModel,
	sessions: list[AnalyticsSession],
	person_contexts: dict[str, dict[str, Any]],
	population_paths: str | None = None,
	max_concurrent: int = 15,
) -> TraitSchema:
	"""Run the full Phase 1 discovery pipeline.

	1. Compress each session into a text timeline.
	2. Run per-session observation LLM calls (concurrently).
	3. Aggregate observations into a TraitSchema.
	"""
	sem = asyncio.Semaphore(max_concurrent)

	async def _observe_one(session: AnalyticsSession) -> SessionObservation | None:
		timeline = compress_session(session, person_contexts.get(session.user_id))
		async with sem:
			try:
				logger.info('Observing session %s (user=%s)', session.session_id, session.user_id)
				return await observe_session(llm, timeline, session.session_id)
			except Exception:
				logger.warning(
					'Failed to observe session %s (user=%s, timeline_len=%d)',
					session.session_id,
					session.user_id,
					len(timeline),
					exc_info=True,
				)
				return None

	results = await asyncio.gather(*[_observe_one(s) for s in sessions])
	observations = [r for r in results if r is not None]
	failed = len(results) - len(observations)
	if failed:
		logger.warning('Discovery completed with %d/%d failures', failed, len(results))
	logger.info('Completed %d session observations, clustering trait dimensions', len(observations))

	schema = await cluster_trait_dimensions(llm, list(observations), population_paths)
	logger.info(
		'Discovered %d trait dimensions: %s',
		len(schema.dimensions),
		[d.name for d in schema.dimensions],
	)
	return schema
