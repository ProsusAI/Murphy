"""Tests for REST API endpoints using FastAPI TestClient — no real LLM/browser calls."""

import pytest
from fastapi.testclient import TestClient

from murphy.api.jobs import Job, _jobs
from murphy.api.rest import app


@pytest.fixture(autouse=True)
def _clean_job_store():
	_jobs.clear()
	yield
	_jobs.clear()


@pytest.fixture
def client():
	return TestClient(app)


# ─── Health ──────────────────────────────────────────────────────────────────


def test_health(client):
	resp = client.get('/health')
	assert resp.status_code == 200
	assert resp.json() == {'status': 'ok'}


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
	job = Job(id='test-job-1', status='completed', result={'data': 42})
	_jobs['test-job-1'] = job

	resp = client.get('/jobs/test-job-1')
	assert resp.status_code == 200
	data = resp.json()
	assert data['id'] == 'test-job-1'
	assert data['status'] == 'completed'
	assert data['result'] == {'data': 42}


def test_get_job_running(client, monkeypatch):
	monkeypatch.setattr('murphy.api.rest.MURPHY_API_KEY', '')
	job = Job(id='running-job', status='running')
	_jobs['running-job'] = job

	resp = client.get('/jobs/running-job')
	assert resp.status_code == 200
	assert resp.json()['status'] == 'running'


def test_get_job_accepts_poll_attempt_nonce(client, monkeypatch):
	monkeypatch.setattr('murphy.api.rest.MURPHY_API_KEY', '')
	job = Job(id='nonce-job', status='completed', result={'data': 42})
	_jobs['nonce-job'] = job

	resp = client.get('/jobs/nonce-job?poll_attempt=1')
	assert resp.status_code == 200
	assert resp.json() == {
		'id': 'nonce-job',
		'status': 'completed',
		'result': {'data': 42},
		'error': None,
		'finished_at': None,
	}


def test_get_job_openapi_exposes_poll_attempt(client):
	schema = client.get('/openapi.json').json()
	parameters = schema['paths']['/jobs/{job_id}']['get']['parameters']

	assert any(param['name'] == 'poll_attempt' and param['in'] == 'query' for param in parameters)


def test_get_job_strips_whitespace(client, monkeypatch):
	monkeypatch.setattr('murphy.api.rest.MURPHY_API_KEY', '')
	job = Job(id='my-job', status='completed', result={})
	_jobs['my-job'] = job

	resp = client.get('/jobs/ my-job ')
	assert resp.status_code == 200
