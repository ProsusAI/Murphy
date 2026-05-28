"""Tests for REST API request/response models."""

import json

import pytest
from pydantic import ValidationError

from murphy.api.request_models import (
	AnalyzeRequest,
	EvaluateRequest,
	ExecuteRequest,
	ExecuteResult,
	GeneratePlanRequest,
	JobResponse,
	_parse_json_string,
)
from murphy.models import (
	ReportSummary,
	TestResult,
	TestScenario,
)

# ─── _parse_json_string ──────────────────────────────────────────────────────


def test_parse_json_string_dict_passthrough():
	d = {'key': 'value'}
	assert _parse_json_string(d) == d


def test_parse_json_string_list_passthrough():
	lst = [1, 2, 3]
	assert _parse_json_string(lst) == lst


def test_parse_json_string_parses_string():
	s = '{"key": "value"}'
	assert _parse_json_string(s) == {'key': 'value'}


def test_parse_json_string_invalid_json_raises():
	with pytest.raises(json.JSONDecodeError):
		_parse_json_string('not json')


def test_parse_json_string_none_passthrough():
	assert _parse_json_string(None) is None


def test_parse_json_string_int_passthrough():
	assert _parse_json_string(42) == 42


# ─── AnalyzeRequest ──────────────────────────────────────────────────────────


def test_analyze_request_minimal():
	r = AnalyzeRequest(url='https://example.com')  # type: ignore[call-arg]
	assert r.url == 'https://example.com'
	assert r.category is None
	assert r.goal is None
	assert r.async_mode is False
	assert r.webhook_url is None


def test_analyze_request_full():
	r = AnalyzeRequest(  # type: ignore[call-arg]
		url='https://example.com',
		category='saas',
		goal='test checkout',
		model='gpt-5',
		webhook_url='https://hooks.example.com',
		async_mode=True,  # type: ignore[call-arg]
	)
	assert r.category == 'saas'
	assert r.goal == 'test checkout'
	assert r.model == 'gpt-5'
	assert r.async_mode is True


def test_analyze_request_missing_url():
	with pytest.raises(ValidationError):
		AnalyzeRequest()  # type: ignore[call-arg]


# ─── EvaluateRequest ─────────────────────────────────────────────────────────


def test_evaluate_request_defaults():
	r = EvaluateRequest(url='https://example.com')  # type: ignore[call-arg]
	assert r.max_tests == 8
	assert r.async_mode is False


# ─── ExecuteRequest ──────────────────────────────────────────────────────────


def test_execute_request_defaults():
	r = ExecuteRequest(url='https://example.com')  # type: ignore[call-arg]
	assert r.test_plan is None
	assert r.evaluate_job_id is None
	assert r.max_steps == 15
	assert r.max_concurrent == 3


def test_execute_request_with_json_string_test_plan():
	"""test_plan field accepts JSON string via BeforeValidator."""
	plan_dict = {
		'scenarios': [
			{
				'name': 'Test search',
				'description': 'Test the search feature',
				'priority': 'high',
				'feature_category': 'search',
				'target_feature': 'Search bar',
				'test_persona': 'happy_path',
				'steps_description': '1. Click search\n2. Type query',
				'success_criteria': 'Results appear',
			}
		]
	}
	r = ExecuteRequest(url='https://example.com', test_plan=json.dumps(plan_dict))  # type: ignore[arg-type]
	assert r.test_plan is not None
	assert len(r.test_plan.scenarios) == 1
	assert r.test_plan.scenarios[0].name == 'Test search'


# ─── GeneratePlanRequest ─────────────────────────────────────────────────────


def _make_analysis_dict() -> dict:
	return {
		'site_name': 'Example',
		'category': 'saas',
		'description': 'An example site',
		'key_pages': [
			{
				'url': 'https://example.com',
				'title': 'Home',
				'purpose': 'Landing page',
				'page_type': 'homepage',
				'interactive_elements': [],
			}
		],
		'features': [
			{
				'name': 'Search',
				'category': 'search',
				'description': 'Search feature',
				'page_url': 'https://example.com',
				'elements': ['search bar'],
				'testability': 'testable',
				'importance': 'core',
			}
		],
		'identified_user_flows': ['Browse -> Search'],
	}


def test_generate_plan_request_with_dict_analysis():
	r = GeneratePlanRequest(url='https://example.com', analysis=_make_analysis_dict())  # type: ignore[arg-type]
	assert r.analysis.site_name == 'Example'


def test_generate_plan_request_with_json_string_analysis():
	r = GeneratePlanRequest(url='https://example.com', analysis=json.dumps(_make_analysis_dict()))  # type: ignore[arg-type]
	assert r.analysis.site_name == 'Example'


# ─── JobResponse ──────────────────────────────────────────────────────────────


def test_job_response():
	r = JobResponse(job_id='abc-123', status='running')
	assert r.job_id == 'abc-123'
	assert r.status == 'running'


# ─── ExecuteResult ────────────────────────────────────────────────────────────


def test_execute_result():
	scenario = TestScenario(
		name='Test',
		description='Desc',
		priority='high',
		feature_category='search',
		target_feature='Search',
		test_persona='happy_path',
		steps_description='1. Do something',
		success_criteria='Works',
	)
	result = TestResult(
		scenario=scenario,
		success=True,
		judgement=None,
		actions=[],
		errors=[],
		duration=1.0,
	)
	summary = ReportSummary(total=1, passed=1, failed=0, pass_rate=100.0, by_priority={})
	er = ExecuteResult(results=[result], summary=summary)
	assert len(er.results) == 1
	assert er.summary.pass_rate == 100.0
