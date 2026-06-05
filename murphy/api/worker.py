"""One-job worker entrypoint for Murphy async jobs."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import traceback
from typing import Any

import httpx

from murphy.api.job_store import JobStore, get_job_store
from murphy.api.request_models import AnalyzeRequest, EvaluateRequest, ExecuteRequest, GeneratePlanRequest
from murphy.config import (
	JOB_TIMEOUT_ANALYZE,
	JOB_TIMEOUT_EVALUATE,
	JOB_TIMEOUT_EXECUTE,
	JOB_TIMEOUT_GENERATE_PLAN,
	MURPHY_JOB_TIMEOUT_OVERRIDE,
)

logger = logging.getLogger('murphy.api.worker')

WEBHOOK_MAX_RETRIES = 2
WEBHOOK_RETRY_DELAY = 2.0


def _effective_timeout(timeout: int | float) -> int | float:
	if MURPHY_JOB_TIMEOUT_OVERRIDE is not None:
		return int(MURPHY_JOB_TIMEOUT_OVERRIDE)
	return timeout


async def _deliver_webhook(webhook_url: str, payload: dict[str, Any]) -> None:
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
				logger.warning('Webhook attempt %d failed for %s: %s', attempt, webhook_url, exc)
				await asyncio.sleep(delay)
				delay *= 2
			else:
				logger.error('Webhook delivery failed after %d attempts for %s: %s', attempt, webhook_url, exc)


async def _core_analyze(req: AnalyzeRequest) -> dict[str, Any]:
	from murphy.api.rest import _core_analyze as core

	return await core(req)


async def _core_generate_plan(req: GeneratePlanRequest) -> dict[str, Any]:
	from murphy.api.rest import _core_generate_plan as core

	return await core(req)


async def _core_execute(req: ExecuteRequest) -> dict[str, Any]:
	from murphy.api.rest import _core_execute as core

	return await core(req)


async def _core_evaluate(req: EvaluateRequest) -> dict[str, Any]:
	from murphy.api.rest import _core_evaluate as core

	return await core(req)


CORE_HANDLERS: dict[str, tuple[type[Any], Any, int]] = {
	'analyze': (AnalyzeRequest, _core_analyze, JOB_TIMEOUT_ANALYZE),
	'generate-plan': (GeneratePlanRequest, _core_generate_plan, JOB_TIMEOUT_GENERATE_PLAN),
	'execute': (ExecuteRequest, _core_execute, JOB_TIMEOUT_EXECUTE),
	'evaluate': (EvaluateRequest, _core_evaluate, JOB_TIMEOUT_EVALUATE),
}


def _prepare_worker_process() -> None:
	from murphy.browser.cleanup import kill_stale_browser
	from murphy.browser.patches import apply as apply_patches

	apply_patches()
	kill_stale_browser()


def _build_request(request_model: type[Any], payload: dict[str, Any]) -> Any:
	if hasattr(request_model, 'model_validate'):
		return request_model.model_validate(payload)
	return request_model(**payload)


def _summary_from_result(result: Any) -> dict[str, Any] | None:
	if isinstance(result, dict) and isinstance(result.get('summary'), dict):
		return result['summary']
	return None


async def run_job(job_id: str, store: JobStore | None = None) -> None:
	_prepare_worker_process()
	store = store or get_job_store()
	job = await store.get_job(job_id)
	if job is None:
		raise ValueError(f'Job {job_id} not found')

	claimed = await store.mark_running(job_id)
	if not claimed:
		logger.info('Job %s was already claimed; skipping', job_id)
		return

	try:
		payload = await store.get_payload(job_id)
		request_model, core_fn, timeout = run_job.CORE_HANDLERS[job.kind]
		req = _build_request(request_model, payload)
		result = await asyncio.wait_for(core_fn(req), timeout=_effective_timeout(timeout))
		await store.mark_completed(job_id, result=result, summary=_summary_from_result(result))
		completed = await store.get_job(job_id)
		if completed and completed.webhook_url:
			await _deliver_webhook(
				completed.webhook_url,
				{
					'job_id': completed.id,
					'status': completed.status,
					'result': result,
					'error': completed.error,
				},
			)
	except Exception as exc:
		tb = traceback.format_exc()
		logger.error('Job %s failed: %s\n%s', job_id, exc, tb)
		await store.mark_failed(job_id, f'{type(exc).__name__}: {exc}')
		failed = await store.get_job(job_id)
		if failed and failed.webhook_url:
			await _deliver_webhook(
				failed.webhook_url,
				{
					'job_id': failed.id,
					'status': failed.status,
					'result': None,
					'error': failed.error,
				},
			)


run_job.CORE_HANDLERS = CORE_HANDLERS  # type: ignore[attr-defined]


def main() -> None:
	parser = argparse.ArgumentParser(description='Run one Murphy job from shared storage.')
	parser.add_argument('--job-id', default=os.environ.get('MURPHY_JOB_ID'))
	args = parser.parse_args()
	if not args.job_id:
		raise SystemExit('MURPHY_JOB_ID or --job-id is required')
	asyncio.run(run_job(args.job_id))


if __name__ == '__main__':
	main()
