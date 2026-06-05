"""Tests for REST API endpoints using FastAPI TestClient — no real LLM/browser calls."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from murphy.api.job_store import InMemoryJobStore, JobRecord, set_job_store_for_tests
from murphy.api.rest import _core_execute, app


@pytest.fixture(autouse=True)
def _clean_job_store():
	set_job_store_for_tests(InMemoryJobStore())
	yield
	set_job_store_for_tests(None)


@pytest.fixture
def client():
	return TestClient(app)


# ─── Health ──────────────────────────────────────────────────────────────────


def test_health(client):
	resp = client.get('/health')
	assert resp.status_code == 200
	assert resp.json() == {'status': 'ok'}


def test_lifespan_runs_browser_startup_cleanup_once(monkeypatch):
	from murphy.browser import cleanup, patches

	calls: list[str] = []
	monkeypatch.setattr(patches, 'apply', lambda: calls.append('patches'))
	monkeypatch.setattr(cleanup, 'kill_stale_browser', lambda: calls.append('cleanup'))

	with TestClient(app) as client:
		assert client.get('/health').status_code == 200
		assert client.get('/health').status_code == 200

	assert calls == ['patches', 'cleanup']


# ─── Auth ────────────────────────────────────────────────────────────────────


def test_auth_no_key_configured(client, monkeypatch):
	"""When MURPHY_API_KEY is empty, all requests pass auth."""
	monkeypatch.setattr('murphy.api.rest.MURPHY_API_KEY', '')
	resp = client.get('/health')
	assert resp.status_code == 200


def test_auth_rejects_missing_key(client, monkeypatch):
	"""When MURPHY_API_KEY is set, requests without key get 401."""
	monkeypatch.setattr('murphy.api.rest.MURPHY_API_KEY', 'secret-key-123')
	# /health doesn't have auth dependency, so test on /jobs endpoint
	resp = client.get('/jobs/nonexistent')
	assert resp.status_code == 401


def test_auth_rejects_wrong_key(client, monkeypatch):
	monkeypatch.setattr('murphy.api.rest.MURPHY_API_KEY', 'secret-key-123')
	resp = client.get('/jobs/nonexistent', headers={'X-API-Key': 'wrong-key'})
	assert resp.status_code == 401


def test_auth_accepts_correct_key(client, monkeypatch):
	monkeypatch.setattr('murphy.api.rest.MURPHY_API_KEY', 'secret-key-123')
	# Job doesn't exist, but auth should pass → 404 not 401
	resp = client.get('/jobs/nonexistent', headers={'X-API-Key': 'secret-key-123'})
	assert resp.status_code == 404


# ─── Job status ──────────────────────────────────────────────────────────────


def test_get_job_not_found(client, monkeypatch):
	monkeypatch.setattr('murphy.api.rest.MURPHY_API_KEY', '')
	resp = client.get('/jobs/nonexistent')
	assert resp.status_code == 404


def test_get_job_found(client, monkeypatch):
	monkeypatch.setattr('murphy.api.rest.MURPHY_API_KEY', '')
	store = InMemoryJobStore()
	set_job_store_for_tests(store)
	job = JobRecord(id='test-job-1', kind='evaluate')
	asyncio.run(store.create_job(job, payload={}))
	asyncio.run(store.mark_completed('test-job-1', result={'data': 42}))

	resp = client.get('/jobs/test-job-1')
	assert resp.status_code == 200
	data = resp.json()
	assert data['id'] == 'test-job-1'
	assert data['status'] == 'completed'
	assert data['result'] == {'data': 42}


def test_get_job_running(client, monkeypatch):
	monkeypatch.setattr('murphy.api.rest.MURPHY_API_KEY', '')
	store = InMemoryJobStore()
	set_job_store_for_tests(store)
	job = JobRecord(id='running-job', kind='evaluate')
	asyncio.run(store.create_job(job, payload={}))
	asyncio.run(store.mark_running('running-job'))

	resp = client.get('/jobs/running-job')
	assert resp.status_code == 200
	assert resp.json()['status'] == 'running'


def test_get_job_accepts_poll_attempt_nonce(client, monkeypatch):
	monkeypatch.setattr('murphy.api.rest.MURPHY_API_KEY', '')
	store = InMemoryJobStore()
	set_job_store_for_tests(store)
	job = JobRecord(id='nonce-job', kind='evaluate')
	asyncio.run(store.create_job(job, payload={}))
	asyncio.run(store.mark_completed('nonce-job', result={'data': 42}))

	resp = client.get('/jobs/nonce-job?poll_attempt=1')
	assert resp.status_code == 200
	data = resp.json()
	assert data['id'] == 'nonce-job'
	assert data['status'] == 'completed'
	assert data['result'] == {'data': 42}
	assert data['error'] is None
	assert data['finished_at'] is not None


def test_get_job_openapi_exposes_poll_attempt(client):
	schema = client.get('/openapi.json').json()
	parameters = schema['paths']['/jobs/{job_id}']['get']['parameters']

	assert any(param['name'] == 'poll_attempt' and param['in'] == 'query' for param in parameters)


def test_get_job_strips_whitespace(client, monkeypatch):
	monkeypatch.setattr('murphy.api.rest.MURPHY_API_KEY', '')
	store = InMemoryJobStore()
	set_job_store_for_tests(store)
	job = JobRecord(id='my-job', kind='evaluate')
	asyncio.run(store.create_job(job, payload={}))
	asyncio.run(store.mark_completed('my-job', result={}))

	resp = client.get('/jobs/ my-job ')
	assert resp.status_code == 200


@pytest.mark.asyncio
async def test_execute_with_evaluate_job_id_reads_shared_result(monkeypatch):
	from murphy.api.request_models import ExecuteRequest

	store = InMemoryJobStore()
	set_job_store_for_tests(store)
	evaluate_job = JobRecord(id='evaluate-job', kind='evaluate')
	test_plan = {
		'scenarios': [
			{
				'name': 'happy path',
				'description': 'View the menu',
				'priority': 'critical',
				'feature_category': 'navigation',
				'target_feature': 'menu',
				'test_persona': 'happy_path',
				'steps_description': 'Open the menu',
				'success_criteria': 'Menu is visible',
			}
		]
	}
	await store.create_job(evaluate_job, payload={})
	await store.mark_completed('evaluate-job', result=test_plan)
	seen = {}

	async def fake_run_execute(url, plan, model, **_kwargs):
		seen['url'] = url
		seen['plan'] = plan
		return [], {'total': 0, 'passed': 0, 'failed': 0, 'pass_rate': 0, 'by_priority': {}}

	monkeypatch.setattr('murphy.core.pipeline.run_execute', fake_run_execute)

	req = ExecuteRequest.model_validate({'url': 'https://example.com', 'evaluate_job_id': 'evaluate-job'})
	result = await _core_execute(req)

	assert seen['url'] == 'https://example.com'
	assert seen['plan'].model_dump() == test_plan
	assert result['summary']['total'] == 0
