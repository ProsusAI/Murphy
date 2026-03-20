"""Tests for the PostHog adapter (PostHogClient → canonical models)."""

from unittest.mock import AsyncMock

import pytest

from murphy.personas.base import AnalyticsConnector
from murphy.personas.models import AnalyticsEvent, AnalyticsSession
from murphy.personas.posthog_adapter import PostHogAdapter


@pytest.fixture
def mock_client():
	client = AsyncMock()
	return client


@pytest.fixture
def adapter(mock_client):
	return PostHogAdapter(mock_client)


# ─── Protocol conformance ────────────────────────────────────────────────────


def test_adapter_satisfies_protocol():
	assert isinstance(PostHogAdapter(AsyncMock()), AnalyticsConnector)


# ─── get_events ──────────────────────────────────────────────────────────────


async def test_get_events_maps_fields(adapter: PostHogAdapter, mock_client):
	mock_client.fetch_events.return_value = [
		{
			'uuid': 'evt-1',
			'event': '$pageview',
			'distinct_id': 'user-a',
			'session_id': 'sess-1',
			'timestamp': '2025-06-01T10:00:00Z',
			'properties': {'$current_url': '/home'},
		},
		{
			'uuid': 'evt-2',
			'event': '$autocapture',
			'distinct_id': 'user-b',
			'session_id': None,
			'timestamp': '2025-06-01T11:00:00Z',
			'properties': {},
		},
	]

	events = await adapter.get_events(after='2025-06-01', limit=100)

	mock_client.fetch_events.assert_awaited_once_with(after='2025-06-01', before=None, limit=100)
	assert len(events) == 2
	assert all(isinstance(e, AnalyticsEvent) for e in events)

	assert events[0].event_id == 'evt-1'
	assert events[0].event_name == '$pageview'
	assert events[0].user_id == 'user-a'
	assert events[0].session_id == 'sess-1'
	assert events[0].properties == {'$current_url': '/home'}
	assert events[0].source == 'posthog'
	assert events[0].raw is not None
	assert events[0].raw['uuid'] == 'evt-1'

	assert events[1].session_id is None


async def test_get_events_empty(adapter: PostHogAdapter, mock_client):
	mock_client.fetch_events.return_value = []

	events = await adapter.get_events()

	assert events == []


# ─── get_sessions ────────────────────────────────────────────────────────────


async def test_get_sessions_maps_fields(adapter: PostHogAdapter, mock_client):
	mock_client.sample_user_sessions.return_value = {
		'user-a': [
			{
				'session_id': 'sess-1',
				'session_start': '2025-06-01T10:00:00Z',
				'session_end': '2025-06-01T10:05:00Z',
				'event_count': 2,
				'events': [
					{
						'session_id': 'sess-1',
						'event': '$pageview',
						'distinct_id': 'user-a',
						'timestamp': '2025-06-01T10:00:00Z',
						'properties': {},
					},
					{
						'session_id': 'sess-1',
						'event': '$autocapture',
						'distinct_id': 'user-a',
						'timestamp': '2025-06-01T10:01:00Z',
						'properties': {'$element_tag': 'button'},
					},
				],
			},
		],
		'user-b': [
			{
				'session_id': 'sess-2',
				'session_start': '2025-06-01T12:00:00Z',
				'session_end': '2025-06-01T12:10:00Z',
				'event_count': 1,
				'events': [
					{
						'session_id': 'sess-2',
						'event': '$pageview',
						'distinct_id': 'user-b',
						'timestamp': '2025-06-01T12:00:00Z',
						'properties': {},
					},
				],
			},
		],
	}

	sessions = await adapter.get_sessions(num_sessions=5, min_events=1)

	mock_client.sample_user_sessions.assert_awaited_once_with(
		num_sessions=5,
		min_events=1,
		after=None,
		before=None,
		offset=0,
	)
	assert len(sessions) == 2
	assert all(isinstance(s, AnalyticsSession) for s in sessions)

	by_user = {s.user_id: s for s in sessions}
	sess_a = by_user['user-a']
	assert sess_a.session_id == 'sess-1'
	assert sess_a.event_count == 2
	assert len(sess_a.events) == 2
	assert sess_a.events[0].event_name == '$pageview'
	assert sess_a.events[1].event_name == '$autocapture'
	assert sess_a.source == 'posthog'

	sess_b = by_user['user-b']
	assert sess_b.session_id == 'sess-2'
	assert len(sess_b.events) == 1


async def test_get_sessions_empty(adapter: PostHogAdapter, mock_client):
	mock_client.sample_user_sessions.return_value = {}

	sessions = await adapter.get_sessions()

	assert sessions == []


async def test_session_events_get_generated_ids(adapter: PostHogAdapter, mock_client):
	"""Session events (which lack UUIDs from PostHog) should still get unique event_ids."""
	mock_client.sample_user_sessions.return_value = {
		'user-a': [
			{
				'session_id': 'sess-1',
				'session_start': '2025-06-01T10:00:00Z',
				'session_end': '2025-06-01T10:01:00Z',
				'event_count': 2,
				'events': [
					{
						'session_id': 'sess-1',
						'event': '$pageview',
						'distinct_id': 'user-a',
						'timestamp': '2025-06-01T10:00:00Z',
						'properties': {},
					},
					{
						'session_id': 'sess-1',
						'event': '$autocapture',
						'distinct_id': 'user-a',
						'timestamp': '2025-06-01T10:01:00Z',
						'properties': {},
					},
				],
			},
		],
	}

	sessions = await adapter.get_sessions()

	ids = [e.event_id for e in sessions[0].events]
	assert len(ids) == 2
	assert ids[0] != ids[1]
	assert all(len(eid) == 32 for eid in ids)
