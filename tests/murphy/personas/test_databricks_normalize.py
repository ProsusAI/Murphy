"""Tests for Databricks event/session normalization."""

from databricks.sql.types import Row

from murphy.personas.databricks_normalize import (
	databricks_event_to_analytics_event,
	databricks_row_to_session,
)
from murphy.personas.models import AnalyticsSession


def test_databricks_event_maps_flat_fields_to_properties():
	row = {
		'event_id': 'evt-1',
		'event_name': '$pageview',
		'event_timestamp': '2026-05-10T12:00:00+00:00',
		'pathname': '/spaces/abc',
		'surface': 'sidebar',
		'tab': 'Settings',
		'feedback': None,
		'conversation_id': 'conv-1',
		'ph_event_has_conversation_id': True,
		'distinct_id': 'user-123',
	}
	event = databricks_event_to_analytics_event(
		row,
		user_id='alice@example.com',
		composite_session_id='conv-1:sess-1',
	)
	assert event.event_name == '$pageview'
	assert event.properties['$pathname'] == '/spaces/abc'
	assert event.properties['surface'] == 'sidebar'
	assert event.properties['tab'] == 'Settings'
	assert event.properties['conversation_id'] == 'conv-1'
	assert event.elements_chain == ''
	assert event.source == 'databricks'


def test_databricks_row_to_session_builds_composite_id_and_context():
	row = {
		'conversation_id': 'conv-1',
		'session_id': 'sess-1',
		'user_email': 'alice@example.com',
		'session_start': '2026-05-10T12:00:00+00:00',
		'session_end': '2026-05-10T12:30:00+00:00',
		'event_count': 2,
		'origin_title': 'Menu help',
		'space_id': 'space-99',
		'message_count': 1,
		'events': [
			{
				'event_id': 'e1',
				'event_name': 'conversation_started',
				'event_timestamp': '2026-05-10T12:05:00+00:00',
				'pathname': '/chat',
			},
			{
				'event_id': 'e2',
				'event_name': '$autocapture',
				'event_timestamp': '2026-05-10T12:06:00+00:00',
				'pathname': '/chat',
				'surface': 'composer',
				'tab': 'Chat',
			},
		],
		'interactions': [
			{
				'message_created_at': '2026-05-10T12:07:00+00:00',
				'message_text_content': 'How do I add a menu item?',
				'response_text_content': 'You can open Settings and click Add item.',
				'full_tool_calls': [],
				'model_name': 'gpt-4.1',
				'author_role': 'user',
			}
		],
	}
	session, session_context, person_context = databricks_row_to_session(row)
	assert session.session_id == 'conv-1:sess-1'
	assert session.user_id == 'alice@example.com'
	assert isinstance(session, AnalyticsSession)
	assert session_context['origin_title'] == 'Menu help'
	assert session_context['space_id'] == 'space-99'
	assert len(session_context['interactions']) == 1
	assert person_context['user_email'] == 'alice@example.com'
	assert session.events[0].properties.get('model') == 'gpt-4.1'


def test_databricks_row_to_session_accepts_sql_row_structs():
	event = Row(
		event_id='e1',
		event_name='$pageview',
		event_timestamp='2026-05-10T12:00:00+00:00',
		pathname='/home',
	)
	row = {
		'conversation_id': 'conv-1',
		'session_id': 'sess-1',
		'user_email': 'alice@example.com',
		'session_start': '2026-05-10T12:00:00+00:00',
		'session_end': '2026-05-10T12:30:00+00:00',
		'event_count': 1,
		'events': [event],
		'interactions': [],
	}
	session, _, _ = databricks_row_to_session(row)
	assert session.events[0].event_name == '$pageview'
	assert session.events[0].properties['$pathname'] == '/home'


def test_databricks_row_to_session_accepts_json_string_events():
	row = {
		'conversation_id': 'conv-1',
		'session_id': 'sess-1',
		'user_email': 'alice@example.com',
		'session_start': '2026-05-10T12:00:00+00:00',
		'session_end': '2026-05-10T12:30:00+00:00',
		'event_count': 1,
		'events': '[{"event_id":"e1","event_name":"$pageview","event_timestamp":"2026-05-10T12:00:00+00:00","pathname":"/home"}]',
		'interactions': '[]',
	}
	session, _, _ = databricks_row_to_session(row)
	assert session.events[0].properties['$pathname'] == '/home'


def test_databricks_row_to_session_accepts_row_literal_strings():
	row = {
		'conversation_id': 'conv-1',
		'session_id': 'sess-1',
		'user_email': 'alice@example.com',
		'session_start': '2026-05-10T12:00:00+00:00',
		'session_end': '2026-05-10T12:30:00+00:00',
		'event_count': 1,
		'events': [
			"Row(event_id='e1', event_name='$pageview', event_timestamp='2026-05-10T12:00:00+00:00', pathname='/home')",
		],
		'interactions': [],
	}
	session, _, _ = databricks_row_to_session(row)
	assert session.events[0].event_name == '$pageview'
