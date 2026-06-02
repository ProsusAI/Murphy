"""Tests for job store and dispatch helpers."""

import asyncio
import time

import pytest

import murphy.api.jobs as jobs
from murphy.api.jobs import (
	JOB_TTL_SECONDS,
	Job,
	_effective_timeout,
	_evict_expired_jobs,
	_execute_with_semaphore,
	_jobs,
	_run_sync,
	get_job,
)


@pytest.fixture(autouse=True)
def _clean_job_store(monkeypatch):
	"""Clear global job state before/after each test."""
	_jobs.clear()
	monkeypatch.setattr(jobs, '_active_job_count', 0, raising=False)
	monkeypatch.setattr(jobs, '_cleanup_lock', asyncio.Lock(), raising=False)
	monkeypatch.setattr('murphy.browser.cleanup.kill_stale_browser', lambda: None)
	yield
	_jobs.clear()
	monkeypatch.setattr(jobs, '_active_job_count', 0, raising=False)


# ─── Job model ────────────────────────────────────────────────────────────────


def test_job_defaults():
	job = Job()
	assert job.status == 'running'
	assert job.result is None
	assert job.error is None
	assert job.finished_at is None
	assert job.id  # uuid7str generates a non-empty id


def test_job_custom_fields():
	job = Job(id='test-123', status='completed', result={'key': 'val'})
	assert job.id == 'test-123'
	assert job.status == 'completed'
	assert job.result == {'key': 'val'}


# ─── get_job ──────────────────────────────────────────────────────────────────


def test_get_job_found():
	job = Job(id='abc')
	_jobs['abc'] = job
	assert get_job('abc') is job


def test_get_job_not_found():
	assert get_job('nonexistent') is None


# ─── _evict_expired_jobs ─────────────────────────────────────────────────────


def test_evict_expired_jobs_removes_old():
	job = Job(id='old', status='completed', finished_at=time.monotonic() - JOB_TTL_SECONDS - 10)
	_jobs['old'] = job
	_evict_expired_jobs()
	assert 'old' not in _jobs


def test_evict_expired_jobs_keeps_recent():
	job = Job(id='recent', status='completed', finished_at=time.monotonic())
	_jobs['recent'] = job
	_evict_expired_jobs()
	assert 'recent' in _jobs


def test_evict_expired_jobs_keeps_running():
	job = Job(id='running', status='running', finished_at=None)
	_jobs['running'] = job
	_evict_expired_jobs()
	assert 'running' in _jobs


# ─── _effective_timeout ──────────────────────────────────────────────────────


def test_effective_timeout_no_override(monkeypatch):
	monkeypatch.setattr('murphy.api.jobs.MURPHY_JOB_TIMEOUT_OVERRIDE', None)
	assert _effective_timeout(300) == 300


def test_effective_timeout_with_override(monkeypatch):
	monkeypatch.setattr('murphy.api.jobs.MURPHY_JOB_TIMEOUT_OVERRIDE', '600')
	assert _effective_timeout(300) == 600


# ─── _execute_with_semaphore ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_with_semaphore_success(monkeypatch):
	monkeypatch.setattr('murphy.api.jobs.MURPHY_JOB_TIMEOUT_OVERRIDE', None)

	async def core_fn(req):
		return {'status': 'ok'}

	job = Job(id='test')
	await _execute_with_semaphore(job, core_fn, {}, timeout=30)
	assert job.status == 'completed'
	assert job.result == {'status': 'ok'}
	assert job.finished_at is not None


@pytest.mark.asyncio
async def test_execute_with_semaphore_runs_cleanup_before_first_job(monkeypatch):
	events: list[str] = []
	monkeypatch.setattr('murphy.api.jobs.MURPHY_JOB_TIMEOUT_OVERRIDE', None)
	monkeypatch.setattr('murphy.browser.cleanup.kill_stale_browser', lambda: events.append('cleanup'))

	async def core_fn(req):
		events.append('core')
		assert jobs._active_job_count == 1
		return {'status': 'ok'}

	job = Job(id='first-job')
	await _execute_with_semaphore(job, core_fn, {}, timeout=30)

	assert events == ['cleanup', 'core']
	assert job.status == 'completed'
	assert jobs._active_job_count == 0


@pytest.mark.asyncio
async def test_execute_with_semaphore_skips_cleanup_when_another_job_active(monkeypatch):
	events: list[str] = []
	monkeypatch.setattr('murphy.api.jobs.MURPHY_JOB_TIMEOUT_OVERRIDE', None)
	monkeypatch.setattr(jobs, '_active_job_count', 1)
	monkeypatch.setattr('murphy.browser.cleanup.kill_stale_browser', lambda: events.append('cleanup'))

	async def core_fn(req):
		events.append('core')
		assert jobs._active_job_count == 2
		return {'status': 'ok'}

	job = Job(id='overlap-job')
	await _execute_with_semaphore(job, core_fn, {}, timeout=30)

	assert events == ['core']
	assert job.status == 'completed'
	assert jobs._active_job_count == 1


@pytest.mark.asyncio
async def test_execute_with_semaphore_decrements_active_count_on_exception(monkeypatch):
	monkeypatch.setattr('murphy.api.jobs.MURPHY_JOB_TIMEOUT_OVERRIDE', None)
	monkeypatch.setattr('murphy.browser.cleanup.kill_stale_browser', lambda: None)

	async def failing_fn(req):
		assert jobs._active_job_count == 1
		raise ValueError('boom')

	job = Job(id='active-count-failure')
	await _execute_with_semaphore(job, failing_fn, {}, timeout=30)

	assert job.status == 'failed'
	assert jobs._active_job_count == 0


@pytest.mark.asyncio
async def test_execute_with_semaphore_timeout(monkeypatch):
	monkeypatch.setattr('murphy.api.jobs.MURPHY_JOB_TIMEOUT_OVERRIDE', None)

	async def slow_fn(req):
		assert jobs._active_job_count == 1
		await asyncio.sleep(10)

	job = Job(id='slow')
	await _execute_with_semaphore(job, slow_fn, {}, timeout=0.1)
	assert job.status == 'failed'
	assert job.error is not None and 'timed out' in job.error
	assert jobs._active_job_count == 0


@pytest.mark.asyncio
async def test_execute_with_semaphore_preserves_inner_timeout(monkeypatch):
	monkeypatch.setattr('murphy.api.jobs.MURPHY_JOB_TIMEOUT_OVERRIDE', None)

	async def browser_start_fn(req):
		raise TimeoutError('Browser did not start within 180 seconds')

	job = Job(id='browser-timeout')
	await _execute_with_semaphore(job, browser_start_fn, {}, timeout=1800)
	assert job.status == 'failed'
	assert job.error == 'TimeoutError: Browser did not start within 180 seconds'


@pytest.mark.asyncio
async def test_execute_with_semaphore_exception(monkeypatch):
	monkeypatch.setattr('murphy.api.jobs.MURPHY_JOB_TIMEOUT_OVERRIDE', None)

	async def failing_fn(req):
		raise ValueError('something went wrong')

	job = Job(id='fail')
	await _execute_with_semaphore(job, failing_fn, {}, timeout=30)
	assert job.status == 'failed'
	assert job.error is not None and 'ValueError' in job.error
	assert 'something went wrong' in job.error


# ─── _run_sync ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_sync_success(monkeypatch):
	monkeypatch.setattr('murphy.api.jobs.MURPHY_JOB_TIMEOUT_OVERRIDE', None)

	async def core_fn(req):
		return {'data': 42}

	resp = await _run_sync(core_fn, {}, timeout=30)
	assert resp.status_code == 200


@pytest.mark.asyncio
async def test_run_sync_failure(monkeypatch):
	monkeypatch.setattr('murphy.api.jobs.MURPHY_JOB_TIMEOUT_OVERRIDE', None)

	async def failing_fn(req):
		raise RuntimeError('boom')

	resp = await _run_sync(failing_fn, {}, timeout=30)
	assert resp.status_code == 500
