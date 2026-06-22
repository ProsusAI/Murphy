"""Tests for the Databricks adapter (mocked SQL)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from murphy.personas.databricks_adapter import DatabricksAdapter

SAMPLE_ROW = {
	'conversation_id': 'conv-1',
	'session_id': 'sess-1',
	'user_email': 'alice@example.com',
	'session_start': '2026-05-10T12:00:00+00:00',
	'session_end': '2026-05-10T12:30:00+00:00',
	'event_count': 1,
	'origin_title': 'Help',
	'space_id': 'space-1',
	'message_count': 0,
	'events': [
		{
			'event_id': 'e1',
			'event_name': '$pageview',
			'event_timestamp': '2026-05-10T12:00:00+00:00',
			'pathname': '/home',
		}
	],
	'interactions': [],
}


@pytest.fixture
def mock_client() -> MagicMock:
	client = MagicMock()
	client.query = AsyncMock(return_value=[SAMPLE_ROW])
	return client


@pytest.mark.asyncio
async def test_get_sessions_maps_row_and_context(mock_client: MagicMock):
	adapter = DatabricksAdapter(client=mock_client, table='catalog.schema.table')
	sessions = await adapter.get_sessions(num_sessions=1, min_events=30, offset=0, event_date_from='2026-05-01')

	assert len(sessions) == 1
	assert sessions[0].session_id == 'conv-1:sess-1'
	assert sessions[0].user_id == 'alice@example.com'
	assert sessions[0].events[0].properties['$pathname'] == '/home'
	assert 'conv-1:sess-1' in adapter.last_session_contexts
	assert adapter.last_session_contexts['conv-1:sess-1']['origin_title'] == 'Help'

	mock_client.query.assert_awaited_once()
	sql = mock_client.query.await_args.args[0]
	assert 'catalog.schema.table' in sql
	assert 'hash(conversation_id, session_id)' in sql
	params = mock_client.query.await_args.args[1]
	assert params['min_events'] == 30
	assert params['offset'] == 0


@pytest.mark.asyncio
async def test_fetch_population_paths_formats_output(mock_client: MagicMock):
	mock_client.query = AsyncMock(return_value=[{'page': '/home', 'visits': 42}])
	adapter = DatabricksAdapter(client=mock_client, table='t')
	text = await adapter.fetch_population_paths('2026-05-01')
	assert '/home' in text
	assert '42' in text
