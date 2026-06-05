"""Tests for shared job storage abstractions."""

from __future__ import annotations

import time

import pytest

from murphy.api.job_store import InMemoryJobStore, JobRecord


@pytest.mark.asyncio
async def test_in_memory_store_persists_payload_and_completed_result():
	store = InMemoryJobStore()
	job = JobRecord.create(kind='evaluate')

	await store.create_job(job, payload={'url': 'https://example.com', 'async': True})
	created = await store.get_job(job.id)

	assert created is not None
	assert created.status == 'pending'
	assert await store.get_payload(job.id) == {'url': 'https://example.com', 'async': True}

	claimed = await store.mark_running(job.id)
	assert claimed is True

	await store.mark_completed(
		job.id,
		result={'plan': {'scenarios': []}},
		summary={'total': 0, 'passed': 0, 'failed': 0, 'pass_rate': 0},
	)

	completed = await store.get_job(job.id)
	assert completed is not None
	assert completed.status == 'completed'
	assert completed.summary == {'total': 0, 'passed': 0, 'failed': 0, 'pass_rate': 0}
	assert await store.get_result(job.id) == {'plan': {'scenarios': []}}


@pytest.mark.asyncio
async def test_mark_running_claims_pending_job_once():
	store = InMemoryJobStore()
	job = JobRecord.create(kind='execute')

	await store.create_job(job, payload={'url': 'https://example.com'})

	assert await store.mark_running(job.id) is True
	assert await store.mark_running(job.id) is False


@pytest.mark.asyncio
async def test_mark_stale_running_jobs_failed_uses_updated_at_cutoff():
	store = InMemoryJobStore()
	job = JobRecord.create(kind='evaluate')
	await store.create_job(job, payload={})
	assert await store.mark_running(job.id) is True

	record = await store.get_job(job.id)
	assert record is not None
	record.updated_at = time.time() - 10_000
	await store.put_job(record)

	failed = await store.mark_stale_running_jobs_failed(max_age_seconds=60)

	assert failed == [job.id]
	stale = await store.get_job(job.id)
	assert stale is not None
	assert stale.status == 'failed'
	assert stale.error == 'worker lost or timed out'
