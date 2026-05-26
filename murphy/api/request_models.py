"""Murphy REST API — request and response models."""

from __future__ import annotations

import json
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from murphy.models import ReportSummary, TestPlan, TestResult, WebsiteAnalysis


def _parse_json_string(v: Any) -> Any:
	"""Accept both a dict/object and a JSON string, parsing the string if needed."""
	if isinstance(v, str):
		return json.loads(v)
	return v


class AnalyzeRequest(BaseModel):
	model_config = ConfigDict(populate_by_name=True)

	url: str
	category: str | None = None
	goal: str | None = None
	provider: str = 'openai'
	model: str = 'gpt-5-mini'
	webhook_url: str | None = None
	async_mode: bool = Field(False, alias='async')


class GeneratePlanRequest(BaseModel):
	model_config = ConfigDict(populate_by_name=True)

	url: str
	analysis: Annotated[WebsiteAnalysis, BeforeValidator(_parse_json_string)]
	max_tests: int = 8
	goal: str | None = None
	lite: bool = False
	provider: str = 'openai'
	model: str = 'gpt-5-mini'
	webhook_url: str | None = None
	async_mode: bool = Field(False, alias='async')


class ExecuteRequest(BaseModel):
	model_config = ConfigDict(populate_by_name=True)

	url: str
	test_plan: Annotated[TestPlan, BeforeValidator(_parse_json_string)] | None = None
	evaluate_job_id: str | None = None
	goal: str | None = None
	provider: str = 'openai'
	model: str = 'gpt-5-mini'
	judge_provider: str | None = None
	judge_model: str | None = None
	max_steps: int = 15
	max_concurrent: int = 3
	lite: bool = False
	webhook_url: str | None = None
	async_mode: bool = Field(False, alias='async')


class EvaluateRequest(BaseModel):
	model_config = ConfigDict(populate_by_name=True)

	url: str
	goal: str | None = None
	max_tests: int = 8
	lite: bool = False
	provider: str = 'openai'
	model: str = 'gpt-5-mini'
	judge_provider: str | None = None
	judge_model: str | None = None
	async_mode: bool = Field(False, alias='async')
	webhook_url: str | None = None


class JobResponse(BaseModel):
	job_id: str
	status: str


class ExecuteResult(BaseModel):
	results: list[TestResult]
	summary: ReportSummary
