"""Murphy REST API — HTTP interface for programmatic evaluation.

Exposes Murphy's evaluation pipeline as REST endpoints:
  POST /evaluate       — combined explore + plan generation
  POST /analyze        — website analysis (feature discovery)
  POST /generate-plan  — test plan generation from analysis
  POST /execute        — test execution from plan
  GET  /jobs/{job_id}  — job status polling
  GET  /health         — health check

Three modes per endpoint:
  - Synchronous (default): blocks until completion, returns 200 with result.
  - Async + webhook (webhook_url set): returns 202 + job_id, POSTs result to webhook.
  - Async + polling ("async": true): returns 202 + job_id, poll /jobs/{job_id} for result.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from murphy.api.jobs import dispatch, get_job
from murphy.api.request_models import (
	AnalyzeRequest,
	EvaluateRequest,
	ExecuteRequest,
	ExecuteResult,
	GeneratePlanRequest,
)
from murphy.config import (
	JOB_TIMEOUT_ANALYZE,
	JOB_TIMEOUT_EVALUATE,
	JOB_TIMEOUT_EXECUTE,
	JOB_TIMEOUT_GENERATE_PLAN,
	MURPHY_API_HOST,
	MURPHY_API_KEY,
	MURPHY_API_PORT,
	MURPHY_REQUEST_TIMEOUT,
)
from murphy.models import TestPlan

# ─── Auth dependency ──────────────────────────────────────────────────────────


async def _verify_api_key(request: Request) -> None:
	if not MURPHY_API_KEY:
		return  # no key configured = open access
	key = request.headers.get('X-API-Key', '')
	if key != MURPHY_API_KEY:
		raise HTTPException(status_code=401, detail='Invalid or missing API key')


# ─── Core logic (returns result dict or raises) ─────────────────────────────


async def _core_analyze(req: AnalyzeRequest) -> dict[str, Any]:
	"""Run website analysis. Returns serialized WebsiteAnalysis dict."""
	from murphy.core.pipeline import run_analyze

	analysis = await run_analyze(req.url, req.model, provider=req.provider, goal=req.goal)
	return analysis.model_dump()


async def _core_generate_plan(req: GeneratePlanRequest) -> dict[str, Any]:
	"""Generate test plan from analysis. Returns serialized TestPlan dict."""
	from murphy.core.pipeline import run_generate_plan

	test_plan = await run_generate_plan(
		req.url, req.analysis, req.model, provider=req.provider, max_tests=req.max_tests, goal=req.goal
	)
	return test_plan.model_dump()


async def _core_execute(req: ExecuteRequest) -> dict[str, Any]:
	"""Execute tests from plan. Returns serialized ExecuteResult dict."""
	from murphy.core.pipeline import run_execute

	# Resolve test_plan: either from request body or from a completed evaluate job
	test_plan = req.test_plan
	if test_plan is None and req.evaluate_job_id:
		job = get_job(req.evaluate_job_id.strip())
		if not job:
			raise ValueError(f'Evaluate job {req.evaluate_job_id} not found')
		if job.status != 'completed':
			raise ValueError(f'Evaluate job {req.evaluate_job_id} is not completed (status: {job.status})')
		test_plan = TestPlan.model_validate(job.result)
	if test_plan is None:
		raise ValueError('Either test_plan or evaluate_job_id must be provided')

	results, summary = await run_execute(
		req.url,
		test_plan,
		req.model,
		provider=req.provider,
		judge_model=req.judge_model,
		judge_provider=req.judge_provider,
		goal=req.goal,
		max_steps=req.max_steps,
		max_concurrent=req.max_concurrent,
	)
	return ExecuteResult(results=results, summary=summary).model_dump()


async def _core_evaluate(req: EvaluateRequest) -> dict[str, Any]:
	"""Run exploration-first evaluation: explore site → generate test plan."""
	from murphy.core.pipeline import run_evaluate

	test_plan = await run_evaluate(req.url, req.model, provider=req.provider, max_tests=req.max_tests, goal=req.goal)
	return test_plan.model_dump()


# ─── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(
	title='Murphy API',
	description='AI-driven website evaluation — REST API',
	version='0.1.0',
)


@app.get('/health')
async def health() -> dict[str, str]:
	return {'status': 'ok'}


@app.post('/analyze', dependencies=[Depends(_verify_api_key)])
async def analyze(req: AnalyzeRequest) -> JSONResponse:
	return await dispatch(_core_analyze, req, JOB_TIMEOUT_ANALYZE)


@app.post('/generate-plan', dependencies=[Depends(_verify_api_key)])
async def generate_plan(req: GeneratePlanRequest) -> JSONResponse:
	return await dispatch(_core_generate_plan, req, JOB_TIMEOUT_GENERATE_PLAN)


@app.post('/execute', dependencies=[Depends(_verify_api_key)])
async def execute(req: ExecuteRequest) -> JSONResponse:
	return await dispatch(_core_execute, req, JOB_TIMEOUT_EXECUTE)


@app.post('/evaluate', dependencies=[Depends(_verify_api_key)])
async def evaluate(req: EvaluateRequest) -> JSONResponse:
	return await dispatch(_core_evaluate, req, JOB_TIMEOUT_EVALUATE)


@app.get('/jobs/{job_id}', dependencies=[Depends(_verify_api_key)])
async def get_job_status(
	job_id: str,
	poll: int = 0,
	poll_attempt: Annotated[
		int | None,
		Query(description='Client-supplied nonce for agent polling; ignored by Murphy.'),
	] = None,
) -> dict[str, Any]:
	"""Get job status. If poll>0, long-poll: block up to `poll` seconds waiting for completion."""
	job = get_job(job_id.strip())
	if not job:
		raise HTTPException(status_code=404, detail='Job not found')

	if poll > 0 and job.status == 'running':
		wait = min(poll, 150)  # cap at 2.5 minutes
		elapsed = 0
		while elapsed < wait and job.status == 'running':
			await asyncio.sleep(5)
			elapsed += 5

	return job.model_dump()


# ─── Entrypoint ───────────────────────────────────────────────────────────────


def main() -> None:
	"""CLI entrypoint for `murphy-api` script."""
	uvicorn.run(
		'murphy.api.rest:app',
		host=MURPHY_API_HOST,
		port=MURPHY_API_PORT,
		reload=False,
		timeout_keep_alive=MURPHY_REQUEST_TIMEOUT,
	)


if __name__ == '__main__':
	main()
