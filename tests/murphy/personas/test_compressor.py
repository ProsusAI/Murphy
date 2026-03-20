"""Tests for the session compressor."""

from datetime import datetime, timezone

from murphy.personas.compressor import compress_session
from murphy.personas.models import AnalyticsEvent, AnalyticsSession


def _make_event(
	name: str,
	ts: datetime,
	properties: dict | None = None,
	user_id: str = 'user-a',
	session_id: str = 'sess-1',
) -> AnalyticsEvent:
	return AnalyticsEvent(
		event_id='e1',
		event_name=name,
		user_id=user_id,
		session_id=session_id,
		timestamp=ts,
		properties=properties or {},
		source='posthog',
	)


def _make_session(events: list[AnalyticsEvent], **kwargs) -> AnalyticsSession:
	defaults = {
		'session_id': 'sess-1',
		'user_id': 'user-a',
		'started_at': events[0].timestamp if events else datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
		'ended_at': events[-1].timestamp if events else datetime(2025, 6, 1, 10, 5, tzinfo=timezone.utc),
		'event_count': len(events),
		'events': events,
		'source': 'posthog',
	}
	defaults.update(kwargs)
	return AnalyticsSession(**defaults)


BASE_TS = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)


def _ts(minutes: int = 0, seconds: int = 0) -> datetime:
	from datetime import timedelta

	return BASE_TS + timedelta(minutes=minutes, seconds=seconds)


# ─── Noise filtering ────────────────────────────────────────────────────────


def test_noise_events_filtered():
	events = [
		_make_event('$pageview', _ts(0), {'$pathname': '/home'}),
		_make_event('$web_vitals', _ts(0, 1)),
		_make_event('$set', _ts(0, 2)),
		_make_event('$identify', _ts(0, 3)),
		_make_event('$feature_flag_called', _ts(0, 4)),
		_make_event('build_outdated', _ts(0, 5)),
		_make_event('$pageleave', _ts(0, 6)),
		_make_event('pusher_connected', _ts(0, 7)),
		_make_event('conversation_started', _ts(1), {'model': 'gpt-4', 'withinSpace': True}),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert 'Navigated to /home' in result
	assert 'Started conversation' in result
	# Noise events should not appear in the timeline
	assert '$web_vitals' not in result.split('=== Event Timeline ===')[1]
	assert '$set' not in result.split('=== Event Timeline ===')[1]
	assert 'pusher_connected' not in result.split('=== Event Timeline ===')[1]


# ─── Navigation summary ─────────────────────────────────────────────────────


def test_navigation_summary_stats():
	events = [
		_make_event('$pageview', _ts(0), {'$pathname': '/'}),
		_make_event('$pageview', _ts(1), {'$pathname': '/spaces'}),
		_make_event('$pageview', _ts(2), {'$pathname': '/spaces/create'}),
		_make_event('$pageview', _ts(5), {'$pathname': '/conversations/abc'}),
		_make_event('conversation_started', _ts(5, 10), {'model': 'gpt-4'}),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert 'Pages visited: 4 unique' in result
	assert 'Feature sections:' in result
	assert 'Navigation style: linear' in result
	assert 'Time to first action:' in result
	assert 'Longest dwell:' in result


def test_backtrack_detected():
	events = [
		_make_event('$pageview', _ts(0), {'$pathname': '/'}),
		_make_event('$pageview', _ts(1), {'$pathname': '/spaces'}),
		_make_event('$pageview', _ts(2), {'$pathname': '/'}),
		_make_event('$pageview', _ts(3), {'$pathname': '/spaces'}),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert '2 backtracks' in result


# ─── Event deduplication ─────────────────────────────────────────────────────


def test_consecutive_events_deduplicated():
	events = [
		_make_event('scroll_down_clicked', _ts(0)),
		_make_event('scroll_down_clicked', _ts(0, 1)),
		_make_event('scroll_down_clicked', _ts(0, 2)),
		_make_event('scroll_down_clicked', _ts(0, 3)),
		_make_event('scroll_down_clicked', _ts(0, 4)),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert '(x5)' in result
	assert result.count('Scrolled down') == 1


# ─── Event compression rules ────────────────────────────────────────────────


def test_pageview_compression():
	events = [_make_event('$pageview', _ts(0), {'$pathname': '/dashboard'})]
	session = _make_session(events)
	result = compress_session(session)
	assert 'Navigated to /dashboard' in result


def test_autocapture_with_text():
	events = [_make_event('$autocapture', _ts(0), {'$el_text': 'Save'})]
	session = _make_session(events)
	result = compress_session(session)
	assert 'Clicked "Save"' in result


def test_autocapture_without_text():
	events = [_make_event('$autocapture', _ts(0), {})]
	session = _make_session(events)
	result = compress_session(session)
	assert 'Interacted with element' in result


def test_conversation_started():
	events = [_make_event('conversation_started', _ts(0), {'model': 'gpt-4', 'withinSpace': True})]
	session = _make_session(events)
	result = compress_session(session)
	assert 'Started conversation (model=gpt-4, space=True)' in result


def test_message_feedback():
	events = [_make_event('message_feedback', _ts(0), {'feedback': 'positive'})]
	session = _make_session(events)
	result = compress_session(session)
	assert 'Gave positive feedback' in result


def test_rageclick():
	events = [
		_make_event('$rageclick', _ts(0)),
		_make_event('$rageclick', _ts(1)),
	]
	session = _make_session(events)
	result = compress_session(session)
	assert 'Rage clicks: 2' in result
	assert 'Rage-clicked' in result


def test_file_events_collapsed():
	events = [
		_make_event('file_uploaded', _ts(0)),
		_make_event('file_pasted', _ts(0, 1)),
		_make_event('file_dropped', _ts(0, 2)),
	]
	session = _make_session(events)
	result = compress_session(session)
	assert result.count('Uploaded file') >= 1


# ─── Metadata header ────────────────────────────────────────────────────────


def test_metadata_header_includes_device_info():
	events = [
		_make_event(
			'$pageview',
			_ts(0),
			{
				'$pathname': '/',
				'$session_entry_pathname': '/home',
				'$session_entry_referring_domain': 'google.com',
				'$browser': 'Chrome',
				'$os': 'Mac OS X',
				'$device_type': 'Desktop',
				'$geoip_city_name': 'London',
				'$geoip_country_name': 'United Kingdom',
				'$browser_language': 'en-GB',
			},
		),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert 'User: user-a' in result
	assert 'Entry page: /home' in result
	assert 'Entry referrer: google.com' in result
	assert 'Chrome' in result
	assert 'London' in result
	assert 'en-GB' in result


def test_person_context_injected():
	events = [_make_event('$pageview', _ts(0), {'$pathname': '/'})]
	session = _make_session(events)
	person = {
		'created_at': '2025-04-15T00:00:00+00:00',
		'initial_referring_domain': 'twitter.com',
	}
	result = compress_session(session, person_context=person)

	assert 'Account age:' in result
	assert 'Initial acquisition: twitter.com' in result


# ─── Web vitals ──────────────────────────────────────────────────────────────


def test_web_vitals_lcp_extracted():
	events = [
		_make_event('$pageview', _ts(0), {'$pathname': '/'}),
		_make_event('$web_vitals', _ts(0, 1), {'$web_vitals_LCP_value': 2400}),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert 'Page load (LCP): 2.4s' in result


# ─── Empty/minimal sessions ─────────────────────────────────────────────────


def test_empty_session():
	session = _make_session([])
	result = compress_session(session)
	assert '=== Session Metadata ===' in result
	assert 'No pageviews recorded.' in result
	assert 'no events after filtering' in result


# ─── Knowledge management signals ───────────────────────────────────────


def test_memory_events_in_timeline():
	events = [
		_make_event('memory_added', _ts(0)),
		_make_event('memory_updated', _ts(1)),
		_make_event('memory_deleted', _ts(2)),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert 'Added a memory' in result
	assert 'Updated a memory' in result
	assert 'Deleted a memory' in result


def test_knowledge_events_in_timeline():
	events = [
		_make_event('knowledge_added', _ts(0)),
		_make_event('knowledge_deleted', _ts(1)),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert 'Added knowledge' in result
	assert 'Deleted knowledge' in result


def test_learning_preferences_in_timeline():
	events = [
		_make_event('learning_preferences_updated', _ts(0)),
		_make_event('memory_preferences_updated', _ts(1)),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert 'Updated learning preferences' in result
	assert 'Updated memory preferences' in result


def test_knowledge_management_cognitive_summary():
	events = [
		_make_event('memory_added', _ts(0)),
		_make_event('memory_added', _ts(1)),
		_make_event('memory_updated', _ts(2)),
		_make_event('knowledge_added', _ts(3)),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert '=== Cognitive & Communication Signals ===' in result
	assert 'Knowledge management actions: 4' in result


# ─── Prompt engineering signals ──────────────────────────────────────────


def test_prompt_engineering_events_in_timeline():
	events = [
		_make_event('prompt_created', _ts(0)),
		_make_event('prompt_selected', _ts(1)),
		_make_event('stored_prompt_used', _ts(2), {'source': 'library'}),
		_make_event('prompts_library_opened', _ts(3)),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert 'Created a saved prompt' in result
	assert 'Selected a saved prompt' in result
	assert 'Used a stored prompt (from library)' in result
	assert 'Opened prompts library' in result


def test_stored_prompt_without_source():
	events = [_make_event('stored_prompt_used', _ts(0))]
	session = _make_session(events)
	result = compress_session(session)

	assert 'Used a stored prompt' in result
	assert '(from' not in result


def test_prompt_engineering_cognitive_summary():
	events = [
		_make_event('prompt_created', _ts(0)),
		_make_event('stored_prompt_used', _ts(1), {'source': 'library'}),
		_make_event('stored_prompt_used', _ts(2), {'source': 'library'}),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert '=== Cognitive & Communication Signals ===' in result
	assert 'Prompt engineering actions: 3' in result


# ─── Feedback depth signals ─────────────────────────────────────────────


def test_feedback_depth_events_in_timeline():
	events = [
		_make_event('message_feedback', _ts(0), {'feedback': 'positive'}),
		_make_event('additional_feedback_started', _ts(1)),
		_make_event('additional_feedback_sent', _ts(2)),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert 'Gave positive feedback' in result
	assert 'Started writing detailed feedback' in result
	assert 'Submitted detailed feedback' in result


def test_feedback_depth_cognitive_summary():
	events = [
		_make_event('message_feedback', _ts(0), {'feedback': 'positive'}),
		_make_event('additional_feedback_started', _ts(1)),
		_make_event('additional_feedback_sent', _ts(2)),
		_make_event('message_feedback', _ts(3), {'feedback': 'negative'}),
		_make_event('additional_feedback_started', _ts(4)),
		_make_event('additional_feedback_cancelled', _ts(5)),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert '=== Cognitive & Communication Signals ===' in result
	assert 'Feedback given: positive: 1, negative: 1' in result
	assert 'Detailed feedback: 1 sent, 1 cancelled (of 2 started)' in result


# ─── Model selection signals ────────────────────────────────────────────


def test_model_select_in_timeline():
	events = [
		_make_event('model_select_changed', _ts(0), {'model_id': 'claude-3.5-sonnet'}),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert 'Switched model to claude-3.5-sonnet' in result


def test_model_selection_cognitive_summary():
	events = [
		_make_event('model_select_changed', _ts(0), {'model_id': 'gpt-4'}),
		_make_event('conversation_started', _ts(1), {'model': 'gpt-4'}),
		_make_event('model_select_changed', _ts(2), {'model_id': 'claude-3.5-sonnet'}),
		_make_event('model_select_changed', _ts(3), {'model_id': 'gpt-4'}),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert '=== Cognitive & Communication Signals ===' in result
	assert 'Model switches: 3' in result
	assert 'gpt-4' in result
	assert 'claude-3.5-sonnet' in result


# ─── Cognitive summary absent when no signals ────────────────────────────


def test_cognitive_summary_absent_when_no_signals():
	events = [
		_make_event('$pageview', _ts(0), {'$pathname': '/home'}),
		_make_event('conversation_started', _ts(1), {'model': 'gpt-4'}),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert '=== Cognitive & Communication Signals ===' not in result


# ─── Combined cognitive signals ─────────────────────────────────────────


def test_combined_cognitive_signals():
	events = [
		_make_event('memory_added', _ts(0)),
		_make_event('prompt_created', _ts(1)),
		_make_event('message_feedback', _ts(2), {'feedback': 'positive'}),
		_make_event('additional_feedback_started', _ts(3)),
		_make_event('additional_feedback_sent', _ts(4)),
		_make_event('model_select_changed', _ts(5), {'model_id': 'gpt-4o'}),
	]
	session = _make_session(events)
	result = compress_session(session)

	assert '=== Cognitive & Communication Signals ===' in result
	assert 'Knowledge management actions: 1' in result
	assert 'Prompt engineering actions: 1' in result
	assert 'Feedback given:' in result
	assert 'Detailed feedback: 1 sent' in result
	assert 'Model switches: 1' in result
