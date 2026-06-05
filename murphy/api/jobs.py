"""Murphy REST API — job store, dispatch, and execution wrappers."""

from __future__ import annotations

import asyncio
import logging
import os
import time
import traceback
from typing import Any, Literal

import httpx
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from uuid_extensions import uuid7str

from murphy.api.job_store import JobRecord, get_job_store
from murphy.api.request_models import JobResponse
from murphy.config import (
	MURPHY_JOB_TIMEOUT_OVERRIDE,
	MURPHY_MAX_CONCURRENT_JOBS,
	SEMAPHORE_ACQUIRE_TIMEOUT,
)

logger = logging.getLogger('murphy.api')

# ─── Job store ────────────────────────────────────────────────────────────────

JOB_TTL_SECONDS = 3600  # Completed/failed jobs are evicted after 1 hour
WEBHOOK_MAX_RETRIES = 2
WEBHOOK_RETRY_DELAY = 2.0  # seconds (doubles each retry)


class Job(BaseModel):
	id: str = Field(default_factory=uuid7str)
	status: Literal['running', 'completed', 'failed'] = 'running'
	result: Any = None
	error: str | None = None
	finished_at: float | None = None


_jobs: dict[str, Job] = {}


def _evict_expired_jobs() -> None:
	"""Remove completed/failed jobs older than JOB_TTL_SECONDS."""
	now = time.monotonic()
	expired = [jid for jid, job in _jobs.items() if job.finished_at is not None and (now - job.finished_at) > JOB_TTL_SECONDS]
	for jid in expired:
		del _jobs[jid]


# Semaphore to limit concurrent browser jobs
_job_semaphore = asyncio.Semaphore(MURPHY_MAX_CONCURRENT_JOBS)
_active_job_count = 0
_cleanup_lock = asyncio.Lock()


def get_job(job_id: str) -> Job | None:
	"""Look up a job by ID."""
	return _jobs.get(job_id)


def _effective_timeout(timeout: int | float) -> int | float:
	"""Return the override timeout if set, otherwise the per-endpoint value."""
	if MURPHY_JOB_TIMEOUT_OVERRIDE is not None:
		return int(MURPHY_JOB_TIMEOUT_OVERRIDE)
	return timeout


# ─── Webhook delivery ─────────────────────────────────────────────────────────


async def _deliver_webhook(webhook_url: str, payload: dict[str, Any]) -> None:
	"""POST job result to the webhook URL with exponential backoff retry."""
	delay = WEBHOOK_RETRY_DELAY
	for attempt in range(1, WEBHOOK_MAX_RETRIES + 2):
		try:
			async with httpx.AsyncClient(timeout=30) as client:
				resp = await client.post(webhook_url, json=payload)
				resp.raise_for_status()
				logger.info('Webhook delivered to %s: %s', webhook_url, resp.status_code)
				return
		except Exception as exc:
			if attempt <= WEBHOOK_MAX_RETRIES:
				logger.warning(
					'Webhook attempt %d/%d failed for %s: %s — retrying in %.0fs',
					attempt,
					WEBHOOK_MAX_RETRIES + 1,
					webhook_url,
					exc,
					delay,
				)
				await asyncio.sleep(delay)
				delay *= 2
			else:
				logger.error('Webhook delivery failed after %d attempts for %s: %s', attempt, webhook_url, exc)


# ─── Core execution with semaphore ───────────────────────────────────────────


async def _acquire_semaphore() -> bool:
	"""Acquire the job semaphore with timeout. Returns True on success."""
	try:
		await asyncio.wait_for(_job_semaphore.acquire(), timeout=SEMAPHORE_ACQUIRE_TIMEOUT)
		return True
	except TimeoutError:
		return False


async def _enter_job_execution() -> None:
	"""Run stale browser cleanup before the first active job, then mark this job active."""
	global _active_job_count
	async with _cleanup_lock:
		if _active_job_count == 0:
			from murphy.browser.cleanup import kill_stale_browser

			kill_stale_browser()
		_active_job_count += 1


async def _exit_job_execution() -> None:
	"""Mark a job inactive while preserving a valid active-job count."""
	global _active_job_count
	async with _cleanup_lock:
		_active_job_count = max(0, _active_job_count - 1)


async def _execute_with_semaphore(job: Job, core_fn: Any, req: Any, timeout: int | float) -> None:
	"""Run core_fn under semaphore, update job status on completion/failure."""
	task: asyncio.Task[Any] | None = None
	entered = False
	try:
		await _enter_job_execution()
		entered = True
		effective = _effective_timeout(timeout)
		task = asyncio.create_task(core_fn(req))
		job.result = await asyncio.wait_for(task, timeout=effective)
		job.status = 'completed'
	except TimeoutError as exc:
		if task is not None and task.done() and not task.cancelled():
			tb = traceback.format_exc()
			logger.error('Job %s failed: %s\n%s', job.id, exc, tb)
			job.status = 'failed'
			job.error = f'{type(exc).__name__}: {exc}'
		else:
			logger.error('Job %s timed out after %ds', job.id, _effective_timeout(timeout))
			job.status = 'failed'
			job.error = f'Job timed out after {_effective_timeout(timeout)}s'
	except Exception as exc:
		tb = traceback.format_exc()
		logger.error('Job %s failed: %s\n%s', job.id, exc, tb)
		job.status = 'failed'
		job.error = f'{type(exc).__name__}: {exc}'
	finally:
		if entered:
			await _exit_job_execution()
		job.finished_at = time.monotonic()
		_job_semaphore.release()


_BUSY_ERROR = f'All {MURPHY_MAX_CONCURRENT_JOBS} job slots busy — try again later'


# ─── Background job wrapper (async mode with webhook) ───────────────────────


async def _run_job_async(
	job: Job,
	core_fn: Any,
	req: Any,
	webhook_url: str,
	timeout: int,
) -> None:
	"""Run core function as a background job, update job store, deliver webhook."""
	if not await _acquire_semaphore():
		job.status = 'failed'
		job.error = _BUSY_ERROR
		job.finished_at = time.monotonic()
		await _deliver_webhook(webhook_url, job.model_dump())
		return

	await _execute_with_semaphore(job, core_fn, req, timeout)
	await _deliver_webhook(
		webhook_url,
		{
			'job_id': job.id,
			'status': job.status,
			'result': job.result,
			'error': job.error,
		},
	)


# ─── Background job wrapper (async mode without webhook) ─────────────────────


async def _run_job_no_webhook(
	job: Job,
	core_fn: Any,
	req: Any,
	timeout: int,
) -> None:
	"""Run core function as a background job, update job store. No webhook delivery."""
	if not await _acquire_semaphore():
		job.status = 'failed'
		job.error = _BUSY_ERROR
		job.finished_at = time.monotonic()
		return

	await _execute_with_semaphore(job, core_fn, req, timeout)


# ─── Sync mode helper ───────────────────────────────────────────────────────


async def _run_sync(core_fn: Any, req: Any, timeout: int) -> JSONResponse:
	"""Run core function synchronously (blocking), return 200 with result or 500 on error."""
	if not await _acquire_semaphore():
		return JSONResponse(content={'status': 'failed', 'error': _BUSY_ERROR}, status_code=503)

	# Create a temporary job to reuse shared execution logic
	job = Job(id='sync')
	await _execute_with_semaphore(job, core_fn, req, timeout)

	if job.status == 'completed':
		return JSONResponse(content={'status': 'completed', 'result': job.result}, status_code=200)
	status_code = 504 if 'timed out' in (job.error or '') else 500
	return JSONResponse(content={'status': 'failed', 'error': job.error}, status_code=status_code)


# ─── Dispatch helper ─────────────────────────────────────────────────────────


def _request_payload(req: Any) -> dict[str, Any]:
	"""Return a JSON-safe request payload for worker execution."""
	try:
		return req.model_dump(mode='json', by_alias=True)
	except TypeError:
		return req.model_dump(by_alias=True)
	except AttributeError:
		return dict(req)


async def launch_worker_task(job_id: str) -> None:
	"""Launch a one-job worker task, falling back to local execution in dev/test."""
	cluster = os.environ.get('MURPHY_ECS_CLUSTER')
	task_definition = os.environ.get('MURPHY_WORKER_TASK_DEFINITION')
	container_name = os.environ.get('MURPHY_WORKER_CONTAINER_NAME')
	subnets = [s for s in os.environ.get('MURPHY_PRIVATE_SUBNETS', '').split(',') if s]
	security_groups = [s for s in os.environ.get('MURPHY_ECS_SECURITY_GROUPS', '').split(',') if s]

	if not (cluster and task_definition and container_name and subnets and security_groups):
		from murphy.api.worker import run_job

		asyncio.create_task(run_job(job_id))
		return

	import boto3

	client = boto3.client('ecs', region_name=os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION'))
	resp = client.run_task(
		cluster=cluster,
		taskDefinition=task_definition,
		launchType='FARGATE',
		networkConfiguration={
			'awsvpcConfiguration': {
				'subnets': subnets,
				'securityGroups': security_groups,
				'assignPublicIp': 'DISABLED',
			}
		},
		overrides={
			'containerOverrides': [
				{
					'name': container_name,
					'environment': [{'name': 'MURPHY_JOB_ID', 'value': job_id}],
				}
			]
		},
	)
	failures = resp.get('failures') or []
	if failures:
		raise RuntimeError(f'ECS RunTask failed: {failures}')


async def dispatch(kind: str, core_fn: Any, req: Any, timeout: int) -> JSONResponse:
	"""Route request to sync, async+webhook, or async+poll mode."""
	_evict_expired_jobs()

	if req.webhook_url:
		store = get_job_store()
		job = await store.create_job(
			JobRecord.create(kind=kind, webhook_url=req.webhook_url, ttl_seconds=JOB_TTL_SECONDS),
			payload=_request_payload(req),
		)
		try:
			await launch_worker_task(job.id)
		except Exception as exc:
			await store.mark_failed(job.id, f'{type(exc).__name__}: {exc}')
			return JSONResponse(content={'status': 'failed', 'error': str(exc)}, status_code=500)
		return JSONResponse(
			content=JobResponse(job_id=job.id, status='running').model_dump(),
			status_code=202,
		)
	elif req.async_mode:
		store = get_job_store()
		job = await store.create_job(
			JobRecord.create(kind=kind, ttl_seconds=JOB_TTL_SECONDS),
			payload=_request_payload(req),
		)
		try:
			await launch_worker_task(job.id)
		except Exception as exc:
			await store.mark_failed(job.id, f'{type(exc).__name__}: {exc}')
			return JSONResponse(content={'status': 'failed', 'error': str(exc)}, status_code=500)
		return JSONResponse(
			content=JobResponse(job_id=job.id, status='running').model_dump(),
			status_code=202,
		)
	else:
		return await _run_sync(core_fn, req, timeout)
