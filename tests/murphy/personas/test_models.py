"""Tests for canonical analytics models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from murphy.personas.models import AnalyticsEvent, AnalyticsSession

# ─── AnalyticsEvent ───────────────────────────────────────────────────────────


def test_event_minimal():
	evt = AnalyticsEvent(
		event_id='e1',
		event_name='$pageview',
		user_id='user-a',
		timestamp=datetime(2025, 6, 1, tzinfo=timezone.utc),
	)
	assert evt.event_id == 'e1'
	assert evt.session_id is None
	assert evt.properties == {}
	assert evt.source == ''
	assert evt.raw is None


def test_event_full():
	evt = AnalyticsEvent(
		event_id='e2',
		event_name='click',
		user_id='user-b',
		session_id='sess-1',
		timestamp=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
		properties={'$current_url': '/home'},
		source='posthog',
		raw={'uuid': 'e2', 'event': 'click'},
	)
	assert evt.session_id == 'sess-1'
	assert evt.properties['$current_url'] == '/home'
	assert evt.source == 'posthog'
	assert evt.raw is not None


def test_event_roundtrip():
	evt = AnalyticsEvent(
		event_id='e1',
		event_name='$pageview',
		user_id='user-a',
		timestamp=datetime(2025, 6, 1, tzinfo=timezone.utc),
		source='posthog',
	)
	rebuilt = AnalyticsEvent.model_validate(evt.model_dump())
	assert rebuilt == evt


def test_event_rejects_extra_fields():
	with pytest.raises(ValidationError):
		AnalyticsEvent.model_validate(
			{
				'event_id': 'e1',
				'event_name': '$pageview',
				'user_id': 'user-a',
				'timestamp': datetime(2025, 6, 1, tzinfo=timezone.utc),
				'bogus': 'nope',
			}
		)


def test_event_requires_fields():
	with pytest.raises(ValidationError):
		AnalyticsEvent.model_validate({'event_id': 'e1'})


# ─── AnalyticsSession ────────────────────────────────────────────────────────


def test_session_minimal():
	sess = AnalyticsSession(
		session_id='s1',
		user_id='user-a',
		started_at=datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
		ended_at=datetime(2025, 6, 1, 10, 5, tzinfo=timezone.utc),
		event_count=3,
	)
	assert sess.events == []
	assert sess.source == ''


def test_session_with_events():
	evt = AnalyticsEvent(
		event_id='e1',
		event_name='$pageview',
		user_id='user-a',
		session_id='s1',
		timestamp=datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
		source='posthog',
	)
	sess = AnalyticsSession(
		session_id='s1',
		user_id='user-a',
		started_at=datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
		ended_at=datetime(2025, 6, 1, 10, 5, tzinfo=timezone.utc),
		event_count=1,
		events=[evt],
		source='posthog',
	)
	assert len(sess.events) == 1
	assert sess.events[0].event_name == '$pageview'


def test_session_roundtrip():
	sess = AnalyticsSession(
		session_id='s1',
		user_id='user-a',
		started_at=datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
		ended_at=datetime(2025, 6, 1, 10, 5, tzinfo=timezone.utc),
		event_count=0,
		source='posthog',
	)
	rebuilt = AnalyticsSession.model_validate(sess.model_dump())
	assert rebuilt == sess


def test_session_rejects_extra_fields():
	with pytest.raises(ValidationError):
		AnalyticsSession.model_validate(
			{
				'session_id': 's1',
				'user_id': 'user-a',
				'started_at': datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc),
				'ended_at': datetime(2025, 6, 1, 10, 5, tzinfo=timezone.utc),
				'event_count': 0,
				'bogus': 'nope',
			}
		)
