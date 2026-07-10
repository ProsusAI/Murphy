"""Tests for REST API endpoints using FastAPI TestClient — no real LLM/browser calls."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from murphy.api.jobs import Job, _jobs
from murphy.api.request_models import EvaluateRequest, ExecuteRequest, GeneratePlanRequest
from murphy.api.rest import _core_evaluate, _core_execute, _core_generate_plan, app
from murphy.models import ReportSummary, TestPlan


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


def test_get_job_strips_whitespace(client, monkeypatch):
	monkeypatch.setattr('murphy.api.rest.MURPHY_API_KEY', '')
	job = Job(id='my-job', status='completed', result={})
	_jobs['my-job'] = job

	resp = client.get('/jobs/ my-job ')
	assert resp.status_code == 200


def _analysis_dict() -> dict:
	return {
		'site_name': 'Example',
		'category': 'saas',
		'description': 'An example site',
		'key_pages': [],
		'features': [],
		'identified_user_flows': [],
	}


@pytest.mark.asyncio
async def test_core_generate_plan_propagates_lite():
	with patch('murphy.core.pipeline.run_generate_plan', new_callable=AsyncMock) as run_generate_plan:
		run_generate_plan.return_value = TestPlan(scenarios=[])
		req = GeneratePlanRequest(url='https://example.com', analysis=_analysis_dict(), lite=True)  # type: ignore[arg-type]

		await _core_generate_plan(req)

	run_generate_plan.assert_awaited_once()
	assert run_generate_plan.call_args.kwargs['lite'] is True


@pytest.mark.asyncio
async def test_core_execute_propagates_lite():
	with patch('murphy.core.pipeline.run_execute', new_callable=AsyncMock) as run_execute:
		run_execute.return_value = ([], ReportSummary(total=0, passed=0, failed=0, pass_rate=0.0, by_priority={}))
		req = ExecuteRequest(url='https://example.com', test_plan=TestPlan(scenarios=[]), lite=True)  # type: ignore[call-arg]

		await _core_execute(req)

	run_execute.assert_awaited_once()
	assert run_execute.call_args.kwargs['lite'] is True


@pytest.mark.asyncio
async def test_core_evaluate_propagates_lite():
	with patch('murphy.core.pipeline.run_evaluate', new_callable=AsyncMock) as run_evaluate:
		run_evaluate.return_value = TestPlan(scenarios=[])
		req = EvaluateRequest(url='https://example.com', goal='Test agent creation flow', lite=True)  # type: ignore[call-arg]

		await _core_evaluate(req)

	run_evaluate.assert_awaited_once()
	assert run_evaluate.call_args.kwargs['lite'] is True
