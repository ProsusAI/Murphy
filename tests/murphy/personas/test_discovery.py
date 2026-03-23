"""Tests for Phase 1 — discovery (mocked LLM calls)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from murphy.personas.discovery import (
	aggregate_trait_schema,
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


# ─── aggregate_trait_schema ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aggregate_returns_schema():
	llm = _mock_llm_for_schema()
	observations = [MOCK_OBSERVATION, MOCK_OBSERVATION]

	result = await aggregate_trait_schema(llm, observations)

	assert isinstance(result, TraitSchema)
	assert len(result.dimensions) >= 1
	llm.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_aggregate_includes_population_paths():
	llm = _mock_llm_for_schema()

	await aggregate_trait_schema(
		llm,
		[MOCK_OBSERVATION],
		population_paths='/ -> /spaces -> /conversations',
	)

	call_args = llm.ainvoke.call_args
	messages = call_args.args[0] if call_args.args else call_args.kwargs['messages']
	user_msg = messages[-1]
	assert '/ -> /spaces -> /conversations' in user_msg.content


# ─── run_discovery ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_discovery_end_to_end():
	call_count = 0

	async def _side_effect(messages, output_format=None, **kwargs):
		nonlocal call_count
		call_count += 1
		resp = MagicMock()
		if output_format is SessionObservation:
			resp.completion = MOCK_OBSERVATION
		else:
			resp.completion = MOCK_SCHEMA
		return resp

	llm = AsyncMock()
	llm.ainvoke.side_effect = _side_effect

	sessions = [_make_session(f'sess-{i}', f'user-{i}') for i in range(3)]
	person_contexts = {f'user-{i}': {'created_at': '2025-01-01T00:00:00Z'} for i in range(3)}

	schema = await run_discovery(
		llm,
		sessions,
		person_contexts,
		population_paths='test paths',
		max_concurrent=2,
	)

	assert isinstance(schema, TraitSchema)
	# 3 observation calls + 1 aggregation call = 4
	assert call_count == 4
