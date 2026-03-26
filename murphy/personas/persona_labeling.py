"""Phase 3b — Persona Labeling: use the LLM to name and describe persona clusters.

Takes algorithmic clustering output (centroids + sizes) and the trait
schema, then asks the LLM to generate memorable archetype names and
descriptions for each cluster.
"""

from __future__ import annotations

import logging

import numpy as np
from browser_use.llm import ChatOpenAI, SystemMessage, UserMessage

from murphy.personas.clustering import ClusteringResult
from murphy.personas.pipeline_models import (
	DimensionScore,
	Persona,
	PersonaLabels,
	PersonaResult,
	SessionPersonaAssignment,
	SessionScore,
	TraitSchema,
)

logger = logging.getLogger(__name__)

# ── Prompts ──────────────────────────────────────────────────────────────────

LABEL_SYSTEM = """\
You are a behavioral scientist naming user personas from clustered session data.

You will receive a set of persona clusters, each described by its centroid
scores on several behavioral trait dimensions. Each dimension has a 1-5 scale
with defined low and high anchors.

For each cluster, provide:
- A short, memorable archetype name (2-4 words, e.g. "Power Explorer",
  "Cautious Evaluator", "Quick Scanner")
- A 2-3 sentence description of who this user is: their motivations,
  typical behavior, and relationship with the product
- The 2-3 traits that most distinguish this persona from the others
  (list dimension names where this cluster's centroid diverges most
  from the overall mean)

Be specific and grounded in the centroid scores. Avoid generic labels."""

LABEL_USER = """\
Name and describe each of the following {num_clusters} persona clusters.

=== Trait Dimensions ===
{schema_block}

=== Clusters ===
{clusters_block}"""


def _format_schema_for_labeling(schema: TraitSchema) -> str:
	lines: list[str] = []
	for dim in schema.dimensions:
		lines.append(f'- **{dim.name}**: {dim.description}')
		lines.append(f'  1 (low) = {dim.low_description}')
		lines.append(f'  5 (high) = {dim.high_description}')
	return '\n'.join(lines)


def _format_clusters(
	schema: TraitSchema,
	centroids: np.ndarray,
	cluster_sizes: list[int],
) -> str:
	dim_names = [d.name for d in schema.dimensions]
	lines: list[str] = []
	for idx in range(centroids.shape[0]):
		lines.append(f'Cluster {idx} ({cluster_sizes[idx]} sessions):')
		for j, name in enumerate(dim_names):
			lines.append(f'  {name}: {centroids[idx, j]:.2f}')
		lines.append('')
	return '\n'.join(lines)


# ── LLM call ─────────────────────────────────────────────────────────────────


async def label_personas(
	llm: ChatOpenAI,
	schema: TraitSchema,
	centroids: np.ndarray,
	cluster_sizes: list[int],
) -> PersonaLabels:
	"""Ask the LLM to name and describe each persona cluster."""
	response = await llm.ainvoke(
		messages=[
			SystemMessage(content=LABEL_SYSTEM),
			UserMessage(
				content=LABEL_USER.format(
					num_clusters=centroids.shape[0],
					schema_block=_format_schema_for_labeling(schema),
					clusters_block=_format_clusters(schema, centroids, cluster_sizes),
				)
			),
		],
		output_format=PersonaLabels,
	)
	labels: PersonaLabels = response.completion
	logger.info('LLM labeled %d personas: %s', len(labels.personas), [p.name for p in labels.personas])
	return labels


# ── Assembly ─────────────────────────────────────────────────────────────────


def build_persona_result(
	schema: TraitSchema,
	scores: list[SessionScore],
	clustering: ClusteringResult,
	labels: PersonaLabels,
) -> PersonaResult:
	"""Merge algorithmic clustering with LLM-generated labels into the final result."""
	dim_names = [d.name for d in schema.dimensions]

	label_map: dict[int, PersonaLabels.personas] = {}
	for p in labels.personas:
		label_map[p.persona_id] = p

	personas: list[Persona] = []
	for cluster_idx in range(clustering.k):
		centroid_scores = [
			DimensionScore(trait_name=name, score=round(float(clustering.centroids[cluster_idx, j]), 2))
			for j, name in enumerate(dim_names)
		]
		size = int(np.sum(clustering.labels == cluster_idx))

		desc = label_map.get(cluster_idx)
		personas.append(
			Persona(
				persona_id=cluster_idx,
				name=desc.name if desc else f'Cluster {cluster_idx}',
				description=desc.description if desc else '',
				centroid=centroid_scores,
				distinguishing_traits=desc.distinguishing_traits if desc else [],
				size=size,
			)
		)

	assignments: list[SessionPersonaAssignment] = []
	for i, s in enumerate(scores):
		assignments.append(
			SessionPersonaAssignment(
				session_id=s.session_id,
				user_id=s.user_id,
				persona_id=int(clustering.labels[i]),
			)
		)

	return PersonaResult(
		personas=personas,
		num_clusters=clustering.k,
		silhouette_score=clustering.silhouette,
		assignments=assignments,
	)
