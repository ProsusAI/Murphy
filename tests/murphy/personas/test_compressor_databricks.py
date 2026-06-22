"""Tests for Databricks-specific compressor behavior."""

from datetime import datetime, timezone

from murphy.personas.compressor import compress_session
from murphy.personas.models import AnalyticsEvent, AnalyticsSession


def _make_event(name: str, ts: datetime, properties: dict | None = None) -> AnalyticsEvent:
	return AnalyticsEvent(
		event_id='e1',
		event_name=name,
		user_id='user-a',
		session_id='conv:sess',
		timestamp=ts,
		properties=properties or {},
		source='databricks',
	)


def _make_session(events: list[AnalyticsEvent]) -> AnalyticsSession:
	return AnalyticsSession(
		session_id='conv:sess',
		user_id='user-a',
		started_at=events[0].timestamp,
		ended_at=events[-1].timestamp,
		event_count=len(events),
		events=events,
		source='databricks',
	)


BASE = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)


def test_posthog_timeline_unchanged_without_session_context():
	events = [
		_make_event('$pageview', BASE, {'$pathname': '/home'}),
		_make_event('conversation_started', BASE.replace(minute=1), {'model': 'gpt-4', 'withinSpace': True}),
	]
	result_without = compress_session(_make_session(events), person_context={'created_at': '2020-01-01'})
	result_explicit_none = compress_session(
		_make_session(events),
		person_context={'created_at': '2020-01-01'},
		session_context=None,
	)
	assert result_without == result_explicit_none
	assert 'Conversation Turns' not in result_without


def test_sparse_autocapture_uses_surface_tab_pathname():
	events = [
		_make_event(
			'$autocapture',
			BASE,
			{'$pathname': '/spaces/abc', 'surface': 'sidebar', 'tab': 'Settings'},
		),
	]
	result = compress_session(_make_session(events))
	assert 'Clicked Settings tab on /spaces/abc' in result


def test_conversation_turns_section_when_session_context_provided():
	events = [_make_event('$pageview', BASE, {'$pathname': '/chat'})]
	session_context = {
		'origin_title': 'Pricing question',
		'space_id': 'space-1',
		'message_count': 1,
		'interactions': [
			{
				'message_created_at': '2026-05-10T12:01:00+00:00',
				'message_text_content': 'What is included in the plan?',
				'response_text_content': 'The plan includes analytics and support.',
				'full_tool_calls': [{'name': 'search'}],
				'model_name': 'gpt-4.1',
				'author_role': 'user',
			}
		],
	}
	result = compress_session(_make_session(events), session_context=session_context)
	assert '=== Conversation Turns ===' in result
	assert 'Conversation: Pricing question' in result
	assert 'Messages in session: 1' in result
	assert 'Turn 1' in result
	assert '1 tool calls' in result
	assert 'What is included' in result
