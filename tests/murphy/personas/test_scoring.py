"""Tests for Phase 2 — scoring (mocked LLM calls)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from murphy.personas.models import AnalyticsEvent, AnalyticsSession
from murphy.personas.pipeline_models import (
	DimensionScore,
	SessionScore,
	TraitDimension,
	TraitSchema,
)
from murphy.personas.scoring import run_scoring, score_session


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


SCHEMA = TraitSchema(
	dimensions=[
		TraitDimension(
			name='engagement_depth',
			description='How deeply the user engages.',
			why_chosen='Multiple sessions showed different depth of product use.',
			low_description='Passive browsing',
			high_description='Deep multi-feature usage',
		),
		TraitDimension(
			name='exploration_breadth',
			description='How many features the user explores.',
			why_chosen='Some users stayed in one area; others sampled many routes.',
			low_description='Single feature focus',
			high_description='Wide exploration across features',
		),
	],
	rationale='Core behavioral axes.',
)

MOCK_SCORE = SessionScore(
	session_id='sess-1',
	user_id='user-a',
	scores=[
		DimensionScore(trait_name='engagement_depth', score=4),
		DimensionScore(trait_name='exploration_breadth', score=2),
	],
	reasoning='User showed deep engagement but narrow exploration.',
)


def _mock_llm() -> AsyncMock:
	llm = AsyncMock()
	response = MagicMock()
	response.completion = MOCK_SCORE
	llm.ainvoke.return_value = response
	return llm


# ─── score_session ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_score_session_returns_score():
	llm = _mock_llm()
	result = await score_session(llm, SCHEMA, 'timeline text', 'sess-1', 'user-a')

	assert isinstance(result, SessionScore)
	assert result.session_id == 'sess-1'
	assert result.user_id == 'user-a'
	assert 'engagement_depth' in result.scores_as_dict()
	llm.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_score_session_uses_trusted_session_identifiers():
	llm = _mock_llm()
	llm.ainvoke.return_value.completion = MOCK_SCORE.model_copy(
		update={'session_id': 'hallucinated-session', 'user_id': 'hallucinated-user'}
	)

	result = await score_session(llm, SCHEMA, 'timeline text', 'trusted-session', 'trusted-user')

	assert result.session_id == 'trusted-session'
	assert result.user_id == 'trusted-user'


@pytest.mark.asyncio
async def test_score_session_includes_schema_in_prompt():
	llm = _mock_llm()
	await score_session(llm, SCHEMA, 'timeline', 'sess-1', 'user-a')

	call_args = llm.ainvoke.call_args
	messages = call_args.args[0] if call_args.args else call_args.kwargs['messages']
	user_msg = messages[-1]
	assert 'engagement_depth' in user_msg.content
	assert 'exploration_breadth' in user_msg.content
	assert 'Why this dimension:' in user_msg.content
	assert 'Multiple sessions showed different depth' in user_msg.content


@pytest.mark.asyncio
async def test_score_session_includes_timeline_in_prompt():
	llm = _mock_llm()
	await score_session(llm, SCHEMA, 'MY_UNIQUE_TIMELINE', 'sess-1', 'user-a')

	call_args = llm.ainvoke.call_args
	messages = call_args.args[0] if call_args.args else call_args.kwargs['messages']
	user_msg = messages[-1]
	assert 'MY_UNIQUE_TIMELINE' in user_msg.content


# ─── run_scoring ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_scoring_end_to_end():
	call_count = 0

	async def _side_effect(messages, output_format=None, **kwargs):
		nonlocal call_count
		call_count += 1
		resp = MagicMock()
		resp.completion = SessionScore(
			session_id=f'sess-{call_count}',
			user_id=f'user-{call_count}',
			scores=[
				DimensionScore(trait_name='engagement_depth', score=3),
				DimensionScore(trait_name='exploration_breadth', score=3),
			],
			reasoning='Average engagement.',
		)
		return resp

	llm = AsyncMock()
	llm.ainvoke.side_effect = _side_effect

	sessions = [_make_session(f'sess-{i}', f'user-{i}') for i in range(5)]
	person_contexts = {f'user-{i}': {'created_at': '2025-01-01T00:00:00Z'} for i in range(5)}

	scores = await run_scoring(
		llm,
		SCHEMA,
		sessions,
		person_contexts,
		max_concurrent=2,
	)

	assert len(scores) == 5
	assert all(isinstance(s, SessionScore) for s in scores)
	assert call_count == 5


@pytest.mark.asyncio
async def test_run_scoring_respects_concurrency():
	"""Verify the semaphore limits concurrent calls."""
	import asyncio

	max_concurrent_seen = 0
	current_concurrent = 0
	lock = asyncio.Lock()

	async def _side_effect(messages, output_format=None, **kwargs):
		nonlocal max_concurrent_seen, current_concurrent
		async with lock:
			current_concurrent += 1
			if current_concurrent > max_concurrent_seen:
				max_concurrent_seen = current_concurrent
		await asyncio.sleep(0.01)
		async with lock:
			current_concurrent -= 1
		resp = MagicMock()
		resp.completion = MOCK_SCORE
		return resp

	llm = AsyncMock()
	llm.ainvoke.side_effect = _side_effect

	sessions = [_make_session(f'sess-{i}', f'user-{i}') for i in range(10)]
	person_contexts = {}

	await run_scoring(llm, SCHEMA, sessions, person_contexts, max_concurrent=3)

	assert max_concurrent_seen <= 3
