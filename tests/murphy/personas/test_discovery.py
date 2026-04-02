"""Tests for Phase 1 — discovery (mocked LLM calls)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from murphy.personas.discovery import (
	_deduplicate_traits,
	cluster_trait_dimensions,
	observe_session,
	run_discovery,
)
from murphy.personas.models import AnalyticsEvent, AnalyticsSession
from murphy.personas.pipeline_models import (
	SessionObservation,
	TraitDimension,
	TraitSchema,
)


def _make_event(name: str, ts: datetime, props: dict | None = None) -> AnalyticsEvent:
	return AnalyticsEvent(
		event_id='e1',
		event_name=name,
		user_id='user-a',
		session_id='sess-1',
		timestamp=ts,
		properties=props or {},
		source='posthog',
	)


def _make_session(session_id: str = 'sess-1', user_id: str = 'user-a') -> AnalyticsSession:
	base = datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)
	from datetime import timedelta

	events = [
		_make_event('$pageview', base, {'$pathname': '/'}),
		_make_event('conversation_started', base + timedelta(minutes=1), {'model': 'gpt-4'}),
	]
	return AnalyticsSession(
		session_id=session_id,
		user_id=user_id,
		started_at=base,
		ended_at=base + timedelta(minutes=5),
		event_count=len(events),
		events=events,
		source='posthog',
	)


MOCK_OBSERVATION = SessionObservation(
	session_id='sess-1',
	observed_traits=['feature-focused', 'linear navigation'],
	behavioral_summary='User went straight to conversations and started chatting.',
)

MOCK_SCHEMA = TraitSchema(
	dimensions=[
		TraitDimension(
			name='engagement_depth',
			description='How deeply the user engages.',
			why_chosen='Observations emphasized depth of interaction.',
			low_description='Passive browsing',
			high_description='Deep multi-feature usage',
		),
		TraitDimension(
			name='exploration_breadth',
			description='How many features the user explores.',
			why_chosen='Breadth of navigation varied across sessions.',
			low_description='Single feature focus',
			high_description='Wide exploration across features',
		),
	],
	rationale='These dimensions capture the core behavioral axes observed.',
)


def _mock_llm_for_observation() -> AsyncMock:
	llm = AsyncMock()
	response = MagicMock()
	response.completion = MOCK_OBSERVATION
	llm.ainvoke.return_value = response
	return llm


def _mock_llm_for_schema() -> AsyncMock:
	llm = AsyncMock()
	response = MagicMock()
	response.completion = MOCK_SCHEMA
	llm.ainvoke.return_value = response
	return llm


# ─── observe_session ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_observe_session_returns_observation():
	llm = _mock_llm_for_observation()
	result = await observe_session(llm, 'some timeline text', 'sess-1')

	assert isinstance(result, SessionObservation)
	assert result.session_id == 'sess-1'
	assert len(result.observed_traits) >= 1
	llm.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_observe_session_passes_timeline_in_prompt():
	llm = _mock_llm_for_observation()
	await observe_session(llm, 'MY_UNIQUE_TIMELINE', 'sess-1')

	call_args = llm.ainvoke.call_args
	messages = call_args.args[0] if call_args.args else call_args.kwargs['messages']
	user_msg = messages[-1]
	assert 'MY_UNIQUE_TIMELINE' in user_msg.content


# ─── _deduplicate_traits ─────────────────────────────────────────────────────


def test_deduplicate_traits_case_insensitive():
	observations = [
		SessionObservation(session_id='s1', observed_traits=['Patient', 'patient', 'Methodical'], behavioral_summary=''),
		SessionObservation(session_id='s2', observed_traits=['methodical', 'Curious'], behavioral_summary=''),
	]
	result = _deduplicate_traits(observations)
	assert len(result) == 3
	lower = [t.lower() for t in result]
	assert 'patient' in lower
	assert 'methodical' in lower
	assert 'curious' in lower


def test_deduplicate_traits_strips_whitespace():
	observations = [
		SessionObservation(session_id='s1', observed_traits=['  Patient  ', 'Patient'], behavioral_summary=''),
	]
	result = _deduplicate_traits(observations)
	assert result == ['Patient']


# ─── cluster_trait_dimensions ────────────────────────────────────────────────


def _mock_embeddings(n: int, dim: int = 8) -> np.ndarray:
	"""Create deterministic mock embeddings with distinct clusters."""
	rng = np.random.RandomState(42)
	return rng.randn(n, dim)


@pytest.mark.asyncio
async def test_cluster_trait_dimensions_returns_schema():
	mock_dim = TraitDimension(
		name='Patience',
		description='How patient the user is.',
		why_chosen='Traits related to waiting and retrying clustered together.',
		low_description='Abandons quickly',
		high_description='Retries calmly',
	)

	llm = AsyncMock()
	resp = MagicMock()
	resp.completion = mock_dim
	llm.ainvoke.return_value = resp

	observations = [
		SessionObservation(session_id='s1', observed_traits=['patient', 'calm', 'deliberate'], behavioral_summary='Waited calmly.'),
		SessionObservation(session_id='s2', observed_traits=['impatient', 'rushed', 'exploratory'], behavioral_summary='Moved fast.'),
		SessionObservation(session_id='s3', observed_traits=['methodical', 'focused', 'thorough'], behavioral_summary='Checked everything.'),
	]

	embeddings = _mock_embeddings(9)

	with patch('murphy.personas.discovery._embed_traits', return_value=embeddings):
		result = await cluster_trait_dimensions(llm, observations, k_range=(2, 4))

	assert isinstance(result, TraitSchema)
	assert len(result.dimensions) >= 2
	assert 'silhouette' in result.rationale.lower() or 'clustered' in result.rationale.lower()


@pytest.mark.asyncio
async def test_cluster_trait_dimensions_empty_observations():
	llm = AsyncMock()
	result = await cluster_trait_dimensions(llm, [])
	assert isinstance(result, TraitSchema)
	assert len(result.dimensions) == 0
	llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_cluster_trait_dimensions_includes_population_paths():
	mock_dim = TraitDimension(
		name='Patience',
		description='desc',
		why_chosen='why',
		low_description='low',
		high_description='high',
	)

	llm = AsyncMock()
	resp = MagicMock()
	resp.completion = mock_dim
	llm.ainvoke.return_value = resp

	observations = [
		SessionObservation(session_id='s1', observed_traits=['patient', 'calm', 'deliberate', 'fast', 'slow'], behavioral_summary=''),
	]
	embeddings = _mock_embeddings(5)

	with patch('murphy.personas.discovery._embed_traits', return_value=embeddings):
		await cluster_trait_dimensions(
			llm,
			observations,
			population_paths='/ -> /spaces -> /conversations',
			k_range=(2, 4),
		)

	call_args = llm.ainvoke.call_args
	messages = call_args.args[0] if call_args.args else call_args.kwargs['messages']
	user_msg = messages[-1]
	assert '/ -> /spaces -> /conversations' in user_msg.content


# ─── run_discovery ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_discovery_end_to_end():
	obs_call_count = 0
	naming_call_count = 0

	mock_dim = TraitDimension(
		name='TestDim',
		description='desc',
		why_chosen='why',
		low_description='low',
		high_description='high',
	)

	async def _side_effect(messages, output_format=None, **kwargs):
		nonlocal obs_call_count, naming_call_count
		resp = MagicMock()
		if output_format is SessionObservation:
			obs_call_count += 1
			resp.completion = MOCK_OBSERVATION
		else:
			naming_call_count += 1
			resp.completion = mock_dim
		return resp

	llm = AsyncMock()
	llm.ainvoke.side_effect = _side_effect

	sessions = [_make_session(f'sess-{i}', f'user-{i}') for i in range(3)]
	person_contexts = {f'user-{i}': {'created_at': '2025-01-01T00:00:00Z'} for i in range(3)}

	embeddings = _mock_embeddings(2)

	with patch('murphy.personas.discovery._embed_traits', return_value=embeddings):
		schema = await run_discovery(
			llm,
			sessions,
			person_contexts,
			population_paths='test paths',
			max_concurrent=2,
		)

	assert isinstance(schema, TraitSchema)
	assert obs_call_count == 3
	assert naming_call_count >= 1
