"""Tests for Phase 3b — persona labeling (mocked LLM calls)."""

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from murphy.personas.clustering import ClusteringResult
from murphy.personas.persona_labeling import build_persona_result, label_personas
from murphy.personas.pipeline_models import (
	DimensionScore,
	PersonaDescription,
	PersonaLabels,
	SessionScore,
	TraitDimension,
	TraitSchema,
)

SCHEMA = TraitSchema(
	dimensions=[
		TraitDimension(
			name='engagement_depth',
			description='How deeply the user engages.',
			why_chosen='Observed variation in depth.',
			low_description='Passive browsing',
			high_description='Deep multi-feature usage',
		),
		TraitDimension(
			name='exploration_breadth',
			description='How many features the user explores.',
			why_chosen='Some users stayed in one area; others explored widely.',
			low_description='Single feature focus',
			high_description='Wide exploration across features',
		),
	],
	rationale='Core behavioral axes.',
)

MOCK_LABELS = PersonaLabels(
	personas=[
		PersonaDescription(
			persona_id=0,
			name='Deep Diver',
			description='Highly engaged users who focus on one area.',
			distinguishing_traits=['engagement_depth'],
			test_orientation='ux',
			success_criteria_guidance='User completes deep exploration of a single feature.',
			execution_hints=['Focus on one area', 'Go deep'],
			judge_questions=['Did the user explore deeply?'],
			suggestion_instruction='As a deeply engaged user, suggest 1-3 depth-of-feature improvements (e.g. advanced filtering, keyboard shortcuts, bulk actions).',
		),
		PersonaDescription(
			persona_id=1,
			name='Broad Explorer',
			description='Users who sample many features with less depth.',
			distinguishing_traits=['exploration_breadth'],
			test_orientation='ux',
			success_criteria_guidance='User samples multiple features.',
			execution_hints=['Try many features', 'Move quickly'],
			judge_questions=['Did the user explore broadly?'],
			suggestion_instruction='As a broad explorer, suggest 1-3 discoverability improvements (e.g. global search, feature highlights, contextual cross-links).',
		),
	]
)


def _mock_llm(labels: PersonaLabels = MOCK_LABELS) -> AsyncMock:
	llm = AsyncMock()
	response = MagicMock()
	response.completion = labels
	llm.ainvoke.return_value = response
	return llm


# ─── label_personas ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_label_personas_returns_labels():
	llm = _mock_llm()
	centroids = np.array([[4.5, 1.5], [1.5, 4.5]])
	result = await label_personas(llm, SCHEMA, centroids, [10, 8])

	assert isinstance(result, PersonaLabels)
	assert len(result.personas) == 2
	assert result.personas[0].name == 'Deep Diver'
	llm.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_label_personas_prompt_contains_centroids():
	llm = _mock_llm()
	centroids = np.array([[4.50, 1.20], [1.80, 4.70]])
	await label_personas(llm, SCHEMA, centroids, [10, 8])

	call_args = llm.ainvoke.call_args
	messages = call_args.args[0] if call_args.args else call_args.kwargs['messages']
	user_msg = messages[-1].content

	assert '4.50' in user_msg
	assert '1.20' in user_msg
	assert '1.80' in user_msg
	assert '4.70' in user_msg


@pytest.mark.asyncio
async def test_label_personas_prompt_contains_schema():
	llm = _mock_llm()
	centroids = np.array([[3.0, 3.0]])
	await label_personas(llm, SCHEMA, centroids, [20])

	call_args = llm.ainvoke.call_args
	messages = call_args.args[0] if call_args.args else call_args.kwargs['messages']
	user_msg = messages[-1].content

	assert 'engagement_depth' in user_msg
	assert 'exploration_breadth' in user_msg
	assert 'Passive browsing' in user_msg
	assert 'Wide exploration' in user_msg


@pytest.mark.asyncio
async def test_label_personas_prompt_contains_cluster_sizes():
	llm = _mock_llm()
	centroids = np.array([[3.0, 3.0], [1.0, 5.0]])
	await label_personas(llm, SCHEMA, centroids, [15, 25])

	call_args = llm.ainvoke.call_args
	messages = call_args.args[0] if call_args.args else call_args.kwargs['messages']
	user_msg = messages[-1].content

	assert '15 sessions' in user_msg
	assert '25 sessions' in user_msg


# ─── build_persona_result ───────────────────────────────────────────────────


def test_build_persona_result_merges_correctly():
	scores = [
		SessionScore(
			session_id='s1',
			user_id='u1',
			scores=[
				DimensionScore(trait_name='engagement_depth', score=5),
				DimensionScore(trait_name='exploration_breadth', score=1),
			],
			reasoning='deep',
		),
		SessionScore(
			session_id='s2',
			user_id='u2',
			scores=[
				DimensionScore(trait_name='engagement_depth', score=1),
				DimensionScore(trait_name='exploration_breadth', score=5),
			],
			reasoning='broad',
		),
		SessionScore(
			session_id='s3',
			user_id='u3',
			scores=[
				DimensionScore(trait_name='engagement_depth', score=4),
				DimensionScore(trait_name='exploration_breadth', score=2),
			],
			reasoning='deep-ish',
		),
	]

	clustering = ClusteringResult(
		labels=np.array([0, 1, 0]),
		centroids=np.array([[4.5, 1.5], [1.0, 5.0]]),
		k=2,
		silhouette=0.85,
		silhouette_scores={2: 0.85},
	)

	result = build_persona_result(SCHEMA, scores, clustering, MOCK_LABELS)

	assert result.num_clusters == 2
	assert result.silhouette_score == 0.85
	assert len(result.assignments) == 3
	assert len(result.personas) == 2

	# Check persona 0 got the LLM label
	p0 = next(p for p in result.personas if p.persona_id == 0)
	assert p0.name == 'Deep Diver'
	assert p0.size == 2
	assert len(p0.centroid) == 2
	assert p0.centroid[0].trait_name == 'engagement_depth'
	assert p0.centroid[0].score == 4.5

	assert p0.suggestion_instruction.startswith('As a deeply engaged user')

	# Check persona 1
	p1 = next(p for p in result.personas if p.persona_id == 1)
	assert p1.name == 'Broad Explorer'
	assert p1.size == 1
	assert p1.suggestion_instruction.startswith('As a broad explorer')

	# Check assignments
	a1 = next(a for a in result.assignments if a.session_id == 's1')
	assert a1.persona_id == 0
	a2 = next(a for a in result.assignments if a.session_id == 's2')
	assert a2.persona_id == 1


def test_build_persona_result_fallback_names():
	"""When LLM labels don't cover a cluster, fallback to 'Cluster N'."""
	scores = [
		SessionScore(
			session_id='s1',
			user_id='u1',
			scores=[
				DimensionScore(trait_name='engagement_depth', score=5),
				DimensionScore(trait_name='exploration_breadth', score=1),
			],
			reasoning='deep',
		),
		SessionScore(
			session_id='s2',
			user_id='u2',
			scores=[
				DimensionScore(trait_name='engagement_depth', score=1),
				DimensionScore(trait_name='exploration_breadth', score=5),
			],
			reasoning='broad',
		),
	]

	clustering = ClusteringResult(
		labels=np.array([0, 1]),
		centroids=np.array([[5.0, 1.0], [1.0, 5.0]]),
		k=2,
		silhouette=0.9,
		silhouette_scores={2: 0.9},
	)

	partial_labels = PersonaLabels(
		personas=[
			PersonaDescription(
				persona_id=0,
				name='Deep Diver',
				description='Deep users.',
				distinguishing_traits=['engagement_depth'],
				test_orientation='ux',
				success_criteria_guidance='User completes deep exploration of a single feature.',
				execution_hints=['Focus on one area', 'Go deep'],
				judge_questions=['Did the user explore deeply?'],
				suggestion_instruction='As a deeply engaged user, suggest 1-3 depth improvements.',
			),
		]
	)

	result = build_persona_result(SCHEMA, scores, clustering, partial_labels)
	p1 = next(p for p in result.personas if p.persona_id == 1)
	assert p1.name == 'Cluster 1'
	assert p1.description == ''
	assert p1.suggestion_instruction == ''
