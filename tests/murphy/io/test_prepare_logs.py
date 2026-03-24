"""Tests for murphy.io.prepare_logs — eval dataset export."""

import json
from pathlib import Path

from murphy.core.summary import build_summary
from murphy.io.prepare_logs import (
	apply_redactions,
	build_eval_run_row,
	collect_eval_dataset_rows,
	discover_run_dirs,
	extract_agent_done,
	main,
	redact_text,
)
from murphy.models import (
	EvaluationReport,
	JudgeVerdict,
	WebsiteAnalysis,
)
from murphy.models import (
	TestResult as ResultModel,
)
from murphy.models import (
	TestScenario as ScenarioModel,
)


def _analysis() -> WebsiteAnalysis:
	return WebsiteAnalysis(
		site_name='https://example.com',
		category='uncategorized',
		description='test',
		key_pages=[],
		features=[],
		identified_user_flows=[],
	)


def _scenario(**kwargs) -> ScenarioModel:
	base = dict(
		name='Scenario A',
		description='desc',
		priority='high',
		feature_category='navigation',
		target_feature='nav',
		test_persona='happy_path',
		steps_description='Do the thing',
		success_criteria='It works',
	)
	base.update(kwargs)
	return ScenarioModel.model_validate(base)


def _verdict(**kwargs) -> JudgeVerdict:
	base = dict(
		reasoning='Because.',
		verdict=True,
		failure_reason='',
		impossible_task=False,
		reached_captcha=False,
		failure_category=None,
	)
	base.update(kwargs)
	return JudgeVerdict.model_validate(base)


def _done_action(
	success: bool = True,
	reason: str = 'agent says ok',
	**data_extras,
) -> dict:
	data = {
		'success': success,
		'reason': reason,
		'process_evaluation': 'proc',
		'logical_evaluation': 'log',
		'usability_evaluation': 'ux',
		'validation_evidence': 'evidence',
	}
	data.update(data_extras)
	return {'done': {'success': success, 'data': data}}


def _result(**kwargs) -> ResultModel:
	base = dict(
		scenario=_scenario(),
		success=True,
		judgement=_verdict(),
		actions=[
			{'click': {'index': 1}},
			_done_action(success=True, reason='Agent done reason'),
		],
		errors=[None, None],
		duration=3.5,
		failure_category=None,
		pages_visited=['https://example.com/path'],
		screenshot_paths=[],
		form_fills=[],
		missing_signals=[],
	)
	base.update(kwargs)
	return ResultModel.model_validate(base)


def _write_report(path: Path, results: list[ResultModel]) -> None:
	summary = build_summary(results)
	report = EvaluationReport(
		url='https://example.com',
		timestamp='2026-01-01T00:00:00+00:00',
		analysis=_analysis(),
		results=results,
		summary=summary,
	)
	path.write_text(report.model_dump_json(indent=2), encoding='utf-8')


def test_discover_run_dirs_numeric_sort(tmp_path: Path) -> None:
	(tmp_path / 'run_10').mkdir()
	(tmp_path / 'run_2').mkdir()
	(tmp_path / 'run_1').mkdir()
	(tmp_path / 'other').mkdir()
	found = discover_run_dirs(tmp_path)
	assert [i for i, _ in found] == [1, 2, 10]


def test_extract_agent_done_reads_last_done() -> None:
	actions = [{'navigate': {'url': 'https://x', 'new_tab': False}}, _done_action(success=False, reason='nope')]
	parsed = extract_agent_done(actions)
	assert parsed is not None
	assert parsed['success'] is False
	assert parsed['reason'] == 'nope'


def test_build_eval_run_row_schema_and_verdict_agreement(tmp_path: Path) -> None:
	run_dir = tmp_path / 'run_1'
	run_dir.mkdir()
	ah = run_dir / 'agent_history'
	ah.mkdir()
	(ah / 'test_01_slug.json').write_text('{}', encoding='utf-8')
	shot = run_dir / 'screenshots' / 't1' / 's.png'
	shot.parent.mkdir(parents=True)
	shot.write_bytes(b'x')

	r1 = _result(
		scenario=_scenario(name='N1', test_persona='edge_case', priority='medium'),
		success=False,
		failure_category='website_issue',
		judgement=_verdict(impossible_task=True, verdict=False, reasoning='judge says no'),
		screenshot_paths=[str(shot.resolve())],
	)
	_write_report(run_dir / 'evaluation_report.json', [r1])
	report = EvaluationReport.model_validate_json((run_dir / 'evaluation_report.json').read_text(encoding='utf-8'))
	row = build_eval_run_row(
		'eval_x',
		1,
		run_dir,
		tmp_path,
		report,
		1,
		report.results[0],
		max_narrative_chars=500,
	)
	assert row['eval_id'] == 'eval_x'
	assert row['run_id'] == 'run_1'
	assert row['scenario_index'] == 1
	assert row['success_criteria'] == 'It works'
	assert row['steps_description'] == 'Do the thing'
	assert row['agent_self_verdict'] is True
	assert row['judge_verdict'] is False
	assert row['verdict_agreement'] is False
	assert row['step_count'] == 2
	assert row['duration_s'] == 3.5
	assert row['failure_category'] == 'website_issue'
	assert row['impossible_task'] is True
	assert row['agent_history_path'] == 'run_1/agent_history/test_01_slug.json'
	assert row['screenshot_paths'] and 'run_1/screenshots' in row['screenshot_paths'][0].replace('\\', '/')


def test_crash_row_no_agent_no_judge(tmp_path: Path) -> None:
	run_dir = tmp_path / 'run_1'
	run_dir.mkdir()
	r1 = _result(
		judgement=None,
		success=None,
		actions=[],
		errors=['Boom'],
	)
	_write_report(run_dir / 'evaluation_report.json', [r1])
	report = EvaluationReport.model_validate_json((run_dir / 'evaluation_report.json').read_text(encoding='utf-8'))
	row = build_eval_run_row(
		'e',
		1,
		run_dir,
		tmp_path,
		report,
		1,
		report.results[0],
		max_narrative_chars=100,
	)
	assert row['agent_self_verdict'] is None
	assert row['judge_verdict'] is None
	assert row['verdict_agreement'] is None
	assert row['impossible_task'] is False


def test_collect_eval_dataset_rows_single_file(tmp_path: Path) -> None:
	for idx in (2, 1):
		rd = tmp_path / f'run_{idx}'
		rd.mkdir()
		results = [
			_result(scenario=_scenario(name=f'S1-run{idx}')),
			_result(
				scenario=_scenario(name=f'S2-run{idx}', test_persona='explorer'),
				success=False,
				failure_category='test_limitation',
				judgement=_verdict(verdict=False, failure_reason='x'),
				actions=[_done_action(success=False, reason='agent fail')],
			),
		]
		_write_report(rd / 'evaluation_report.json', results)
		ah = rd / 'agent_history'
		ah.mkdir()
		(ah / 'test_01_x.json').write_text('{}', encoding='utf-8')
		(ah / 'test_02_y.json').write_text('{}', encoding='utf-8')

	rows = collect_eval_dataset_rows(tmp_path, 'eval_test_1', max_narrative_chars=200)
	assert len(rows) == 4
	assert rows[0]['run_index'] == 1
	assert rows[2]['run_index'] == 2
	assert rows[1]['judge_verdict'] is False
	assert rows[1]['agent_self_verdict'] is False
	assert rows[1]['verdict_agreement'] is True
	assert 'eval_plan_path' not in rows[0]
	assert rows[0]['agent_history_path'] == 'run_1/agent_history/test_01_x.json'


def test_redact_text_email_and_term() -> None:
	s = 'Contact user@example.com at ACME Corp'
	out = redact_text(s, ['ACME Corp'])
	assert '[REDACTED_EMAIL]' in out
	assert '[REDACTED_ORG]' in out


def test_apply_redactions_form_fills() -> None:
	row = {
		'judge_reasoning': 'x',
		'form_fills': [{'text': 'secret@corp.io', 'index': 1}],
		'errors': ['fail user@x.co'],
	}
	out = apply_redactions(row, [])
	assert '[REDACTED_EMAIL]' in out['form_fills'][0]['text']
	assert '[REDACTED_EMAIL]' in out['errors'][0]


def test_main_single_out_jsonl(tmp_path: Path) -> None:
	rd = tmp_path / 'run_1'
	rd.mkdir()
	_write_report(rd / 'evaluation_report.json', [_result()])
	out_file = tmp_path / 'dataset.jsonl'
	rc = main(
		[
			'--output-root',
			str(tmp_path),
			'--eval-id',
			'my_eval',
			'--format',
			'jsonl',
			'--out',
			str(out_file),
			'--max-narrative-chars',
			'0',
		]
	)
	assert rc == 0
	lines = out_file.read_text(encoding='utf-8').strip().splitlines()
	assert len(lines) == 1
	data = json.loads(lines[0])
	assert data['eval_id'] == 'my_eval'
	assert data['step_count'] == 2
	assert 'judge_verdict' in data


def test_main_redact_term_cli(tmp_path: Path) -> None:
	rd = tmp_path / 'run_1'
	rd.mkdir()
	r = _result()
	r = r.model_copy(
		update={
			'judgement': _verdict(reasoning='ACMETEST is mentioned'),
		}
	)
	_write_report(rd / 'evaluation_report.json', [r])
	out_file = tmp_path / 'out.jsonl'
	rc = main(
		[
			'--output-root',
			str(tmp_path),
			'--out',
			str(out_file),
			'--redact-term',
			'ACMETEST',
		]
	)
	assert rc == 0
	data = json.loads(out_file.read_text(encoding='utf-8').strip().splitlines()[0])
	assert 'ACMETEST' not in data['judge_reasoning']
	assert '[REDACTED_ORG]' in data['judge_reasoning']
