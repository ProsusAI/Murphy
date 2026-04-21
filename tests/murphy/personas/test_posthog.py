"""Tests for the PostHog ingestion client."""

import json

import pytest
from pytest_httpserver import HTTPServer

from murphy.personas.posthog_client import PostHogAPIError, PostHogClient

API_KEY = 'phx_test_key_123'
PROJECT_ID = '12345'


@pytest.fixture
def posthog_server(httpserver: HTTPServer):
	return httpserver


@pytest.fixture
async def client(posthog_server: HTTPServer):
	c = PostHogClient(
		api_key=API_KEY,
		project_id=PROJECT_ID,
		host=posthog_server.url_for(''),
	)
	async with c as ctx:
		yield ctx


# ─── Auth & URL construction ─────────────────────────────────────────────────


async def test_query_sends_auth_header(client: PostHogClient, posthog_server: HTTPServer):
	posthog_server.expect_request(
		f'/api/projects/{PROJECT_ID}/query/',
		method='POST',
	).respond_with_json({'columns': [], 'results': [], 'hasMore': False})

	await client.query('SELECT 1')

	req = posthog_server.log[0][0]
	assert req.headers['Authorization'] == f'Bearer {API_KEY}'


async def test_query_posts_hogql_payload(client: PostHogClient, posthog_server: HTTPServer):
	posthog_server.expect_request(
		f'/api/projects/{PROJECT_ID}/query/',
		method='POST',
	).respond_with_json({'columns': ['one'], 'results': [[1]], 'hasMore': False})

	result = await client.query('SELECT 1')

	req = posthog_server.log[0][0]
	body = json.loads(req.data)
	assert body['query']['kind'] == 'HogQLQuery'
	assert body['query']['query'] == 'SELECT 1'
	assert 'limit' not in body['query']
	assert result['columns'] == ['one']
	assert result['results'] == [[1]]


# ─── fetch_events ────────────────────────────────────────────────────────────


async def test_fetch_events_returns_dicts(client: PostHogClient, posthog_server: HTTPServer):
	posthog_server.expect_request(
		f'/api/projects/{PROJECT_ID}/query/',
		method='POST',
	).respond_with_json(
		{
			'columns': ['uuid', 'event', 'distinct_id', 'session_id', 'timestamp', 'properties'],
			'results': [
				['evt-1', '$pageview', 'user-a', 'sess-1', '2025-06-01T00:00:00Z', {'$current_url': '/home'}],
				['evt-2', '$autocapture', 'user-b', 'sess-2', '2025-06-01T01:00:00Z', {'$element_tag': 'button'}],
			],
			'hasMore': False,
		}
	)

	events = await client.fetch_events(limit=100)

	assert len(events) == 2
	assert events[0]['event'] == '$pageview'
	assert events[0]['distinct_id'] == 'user-a'
	assert events[0]['session_id'] == 'sess-1'
	assert events[1]['properties'] == {'$element_tag': 'button'}


async def test_fetch_events_builds_filters(client: PostHogClient, posthog_server: HTTPServer):
	posthog_server.expect_request(
		f'/api/projects/{PROJECT_ID}/query/',
		method='POST',
	).respond_with_json({'columns': [], 'results': [], 'hasMore': False})

	await client.fetch_events(
		event_types=['$pageview', '$autocapture'],
		after='2025-01-01',
		distinct_id='user-x',
	)

	body = json.loads(posthog_server.log[0][0].data)
	hogql = body['query']['query']
	assert "event IN ('$pageview', '$autocapture')" in hogql
	assert "timestamp > '2025-01-01'" in hogql
	assert "distinct_id = 'user-x'" in hogql


# ─── fetch_persons ────────────────────────────────────────────────────────────


async def test_fetch_persons_returns_dicts(client: PostHogClient, posthog_server: HTTPServer):
	posthog_server.expect_request(
		f'/api/projects/{PROJECT_ID}/query/',
		method='POST',
	).respond_with_json(
		{
			'columns': ['id', 'properties', 'created_at'],
			'results': [
				['p-1', {'email': 'a@b.com'}, '2025-01-01T00:00:00Z'],
			],
			'hasMore': False,
		}
	)

	persons = await client.fetch_persons()

	assert len(persons) == 1
	assert persons[0]['id'] == 'p-1'
	assert persons[0]['properties']['email'] == 'a@b.com'


async def test_fetch_persons_with_filter(client: PostHogClient, posthog_server: HTTPServer):
	posthog_server.expect_request(
		f'/api/projects/{PROJECT_ID}/query/',
		method='POST',
	).respond_with_json({'columns': [], 'results': [], 'hasMore': False})

	await client.fetch_persons(properties_filter='properties.email IS NOT NULL')

	body = json.loads(posthog_server.log[0][0].data)
	hogql = body['query']['query']
	assert 'properties.email IS NOT NULL' in hogql


# ─── fetch_cohorts ────────────────────────────────────────────────────────────


async def test_fetch_cohorts_returns_list(client: PostHogClient, posthog_server: HTTPServer):
	posthog_server.expect_request(
		f'/api/projects/{PROJECT_ID}/cohorts/',
		method='GET',
	).respond_with_json(
		{
			'results': [
				{'id': 1, 'name': 'Power Users', 'count': 42},
				{'id': 2, 'name': 'Churned', 'count': 10},
			],
		}
	)

	cohorts = await client.fetch_cohorts()

	assert len(cohorts) == 2
	assert cohorts[0]['name'] == 'Power Users'
	assert cohorts[1]['count'] == 10


# ─── fetch_cohort_persons ─────────────────────────────────────────────────────


async def test_fetch_cohort_persons(client: PostHogClient, posthog_server: HTTPServer):
	posthog_server.expect_request(
		f'/api/projects/{PROJECT_ID}/cohorts/1/persons/',
		method='GET',
	).respond_with_json(
		{
			'results': [
				{'id': 'p-1', 'distinct_ids': ['user-a'], 'properties': {}},
			],
		}
	)

	persons = await client.fetch_cohort_persons(1)

	assert len(persons) == 1
	assert persons[0]['id'] == 'p-1'


# ─── sample_user_sessions ─────────────────────────────────────────────────


async def test_sample_user_sessions(client: PostHogClient, posthog_server: HTTPServer):
	query_url = f'/api/projects/{PROJECT_ID}/query/'

	# Query 1: sessions above event threshold
	posthog_server.expect_ordered_request(query_url, method='POST').respond_with_json(
		{
			'columns': ['distinct_id', 'session_id', 'session_start', 'session_end', 'event_count'],
			'results': [
				['user-a', 'sess-1', '2025-06-01T10:00:00Z', '2025-06-01T10:05:00Z', 3],
				['user-a', 'sess-2', '2025-05-30T08:00:00Z', '2025-05-30T08:02:00Z', 2],
				['user-b', 'sess-3', '2025-06-01T12:00:00Z', '2025-06-01T12:10:00Z', 4],
			],
			'hasMore': False,
		}
	)
	# Query 2: events for sessions
	posthog_server.expect_ordered_request(query_url, method='POST').respond_with_json(
		{
			'columns': ['session_id', 'event', 'distinct_id', 'timestamp', 'properties'],
			'results': [
				['sess-1', '$pageview', 'user-a', '2025-06-01T10:00:00Z', {}],
				['sess-1', '$autocapture', 'user-a', '2025-06-01T10:01:00Z', {}],
				['sess-1', '$pageview', 'user-a', '2025-06-01T10:03:00Z', {}],
				['sess-2', '$pageview', 'user-a', '2025-05-30T08:00:00Z', {}],
				['sess-2', '$autocapture', 'user-a', '2025-05-30T08:01:00Z', {}],
				['sess-3', '$pageview', 'user-b', '2025-06-01T12:00:00Z', {}],
				['sess-3', '$autocapture', 'user-b', '2025-06-01T12:05:00Z', {}],
				['sess-3', '$pageview', 'user-b', '2025-06-01T12:08:00Z', {}],
				['sess-3', '$autocapture', 'user-b', '2025-06-01T12:09:00Z', {}],
			],
			'hasMore': False,
		}
	)

	result = await client.sample_user_sessions(num_sessions=5, min_events=1)

	assert set(result.keys()) == {'user-a', 'user-b'}
	assert len(result['user-a']) == 2
	assert len(result['user-b']) == 1
	assert result['user-a'][0]['session_id'] == 'sess-1'
	assert len(result['user-a'][0]['events']) == 3
	assert len(result['user-a'][1]['events']) == 2
	assert result['user-b'][0]['session_id'] == 'sess-3'
	assert len(result['user-b'][0]['events']) == 4
	assert result['user-a'][0]['session_start'] == '2025-06-01T10:00:00Z'


async def test_sample_user_sessions_empty(client: PostHogClient, posthog_server: HTTPServer):
	posthog_server.expect_request(
		f'/api/projects/{PROJECT_ID}/query/',
		method='POST',
	).respond_with_json(
		{
			'columns': ['distinct_id', 'session_id', 'session_start', 'session_end', 'event_count'],
			'results': [],
			'hasMore': False,
		}
	)

	result = await client.sample_user_sessions(num_sessions=5, min_events=1)

	assert result == {}


# ─── Error handling ───────────────────────────────────────────────────────────


async def test_query_raises_on_error(client: PostHogClient, posthog_server: HTTPServer):
	posthog_server.expect_request(
		f'/api/projects/{PROJECT_ID}/query/',
		method='POST',
	).respond_with_json({'error': 'bad query'}, status=400)

	with pytest.raises(PostHogAPIError) as exc_info:
		await client.query('SELECT bad')

	assert exc_info.value.status_code == 400
	assert 'bad query' in exc_info.value.detail


async def test_cohorts_raises_on_error(client: PostHogClient, posthog_server: HTTPServer):
	posthog_server.expect_request(
		f'/api/projects/{PROJECT_ID}/cohorts/',
		method='GET',
	).respond_with_json({'detail': 'unauthorized'}, status=401)

	with pytest.raises(PostHogAPIError) as exc_info:
		await client.fetch_cohorts()

	assert exc_info.value.status_code == 401


# ─── Context manager ─────────────────────────────────────────────────────────


async def test_client_requires_context_manager():
	c = PostHogClient(api_key=API_KEY, project_id=PROJECT_ID, host='http://localhost')
	with pytest.raises(RuntimeError, match='async context manager'):
		await c.query('SELECT 1')


def test_client_requires_api_key(monkeypatch):
	monkeypatch.setattr('murphy.personas.posthog_client.POSTHOG_API_KEY', '')
	with pytest.raises(ValueError, match='API key'):
		PostHogClient(api_key='', project_id=PROJECT_ID)


def test_client_requires_project_id(monkeypatch):
	monkeypatch.setattr('murphy.personas.posthog_client.POSTHOG_PROJECT_ID', '')
	with pytest.raises(ValueError, match='project ID'):
		PostHogClient(api_key=API_KEY, project_id='')
