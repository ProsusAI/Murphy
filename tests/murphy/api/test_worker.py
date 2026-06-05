"""Tests for the one-job worker entrypoint."""

from __future__ import annotations

import pytest

from murphy.api.job_store import InMemoryJobStore, JobRecord
from murphy.api.worker import run_job


@pytest.fixture(autouse=True)
def _disable_worker_process_setup(monkeypatch):
	monkeypatch.setattr('murphy.api.worker._prepare_worker_process', lambda: None)


class FakeRequest:
	def __init__(self, **data):
		self.__dict__.update(data)


@pytest.mark.asyncio
async def test_worker_runs_one_job_and_persists_result(monkeypatch):
	store = InMemoryJobStore()
	job = JobRecord.create(kind='evaluate')
	await store.create_job(job, payload={'url': 'https://example.com', 'async': True})

	async def fake_core(req):
		assert req.url == 'https://example.com'
		return {'scenarios': []}

	monkeypatch.setitem(run_job.CORE_HANDLERS, 'evaluate', (FakeRequest, fake_core, 30))

	await run_job(job.id, store=store)

	completed = await store.get_job(job.id)
	assert completed is not None
	assert completed.status == 'completed'
	assert await store.get_result(job.id) == {'scenarios': []}


@pytest.mark.asyncio
async def test_worker_marks_job_failed_when_core_raises(monkeypatch):
	store = InMemoryJobStore()
	job = JobRecord.create(kind='execute')
	await store.create_job(job, payload={'url': 'https://example.com'})

	async def failing_core(_req):
		raise RuntimeError('browser exploded')

	monkeypatch.setitem(run_job.CORE_HANDLERS, 'execute', (FakeRequest, failing_core, 30))

	await run_job(job.id, store=store)

	failed = await store.get_job(job.id)
	assert failed is not None
	assert failed.status == 'failed'
	assert failed.error is not None
	assert 'RuntimeError: browser exploded' in failed.error
