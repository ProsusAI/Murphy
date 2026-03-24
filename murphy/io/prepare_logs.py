"""Export multi-run Murphy outputs to a single flat eval dataset (JSONL or CSV).

Scans ``--output-root`` for ``run_<n>/`` directories, reads each
``evaluation_report.json``, and emits one line per (run × scenario).

Optional redaction masks emails and configurable organization/company terms
before writing.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TextIO

from murphy.models import EvaluationReport, TestResult

_RUN_DIR_RE = re.compile(r'^run_(\d+)$')
_EMAIL_RE = re.compile(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b')


def discover_run_dirs(output_root: Path) -> list[tuple[int, Path]]:
	"""Return ``(run_index, run_dir)`` sorted by ``run_index`` ascending."""
	runs: list[tuple[int, Path]] = []
	if not output_root.is_dir():
		return runs
	for p in output_root.iterdir():
		if not p.is_dir():
			continue
		m = _RUN_DIR_RE.fullmatch(p.name)
		if m:
			runs.append((int(m.group(1)), p))
	runs.sort(key=lambda x: x[0])
	return runs


def _relative_under_root(path: Path | str, output_root: Path) -> str:
	"""Return path relative to ``output_root`` when possible."""
	p = Path(path).resolve()
	root = output_root.resolve()
	try:
		return str(p.relative_to(root))
	except ValueError:
		return str(p)


def _truncate(s: str | None, max_len: int) -> str:
	if max_len <= 0 or not s:
		return ''
	if len(s) <= max_len:
		return s
	return s[: max_len - 3] + '...'


def load_redact_terms_file(path: Path) -> list[str]:
	lines = path.read_text(encoding='utf-8').splitlines()
	return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith('#')]


def normalize_redact_terms(cli_terms: list[str], file_path: Path | None) -> list[str]:
	terms = list(cli_terms)
	if file_path is not None and file_path.is_file():
		terms.extend(load_redact_terms_file(file_path))
	# Longest first so "Foo Bar" replaces before "Foo"
	unique = sorted({t for t in terms if t}, key=len, reverse=True)
	return unique


def redact_text(s: str, terms: list[str]) -> str:
	if not s:
		return s
	out = _EMAIL_RE.sub('[REDACTED_EMAIL]', s)
	for term in terms:
		out = re.sub(re.escape(term), '[REDACTED_ORG]', out, flags=re.IGNORECASE)
	return out


def extract_agent_done(actions: list[dict[str, Any]]) -> dict[str, Any] | None:
	"""Parse the last structured ``done`` action from serialized ``actions``."""
	for action in reversed(actions):
		if not isinstance(action, dict) or 'done' not in action:
			continue
		done = action['done']
		if not isinstance(done, dict):
			continue
		data = done.get('data')
		if isinstance(data, dict):
			return {
				'success': data.get('success', done.get('success')),
				'reason': data.get('reason') or '',
				'process_evaluation': data.get('process_evaluation') or '',
				'logical_evaluation': data.get('logical_evaluation') or '',
				'usability_evaluation': data.get('usability_evaluation') or '',
				'validation_evidence': data.get('validation_evidence') or '',
			}
		# done without nested data
		if 'success' in done:
			return {
				'success': done.get('success'),
				'reason': str(done.get('reason', '') or ''),
				'process_evaluation': '',
				'logical_evaluation': '',
				'usability_evaluation': '',
				'validation_evidence': '',
			}
	return None


def _resolve_agent_history_path(run_dir: Path, scenario_index: int) -> str | None:
	adir = run_dir / 'agent_history'
	if not adir.is_dir():
		return None
	matches = sorted(adir.glob(f'test_{scenario_index:02d}_*.json'))
	if matches:
		return str(matches[0].resolve())
	return None


def _feedback_quality_dict(result: TestResult) -> dict[str, Any] | None:
	if result.judgement is None or result.judgement.feedback_quality is None:
		return None
	return result.judgement.feedback_quality.model_dump(mode='json')


def build_eval_run_row(
	eval_id: str,
	run_index: int,
	run_dir: Path,
	output_root: Path,
	report: EvaluationReport,
	scenario_index: int,
	result: TestResult,
	*,
	max_narrative_chars: int,
) -> dict[str, Any]:
	"""Build one eval dataset row (JSON-serializable), new schema."""
	output_root = output_root.resolve()
	sc = result.scenario
	agent = extract_agent_done(result.actions)

	agent_verdict: bool | None
	if agent is None or agent.get('success') is None:
		agent_verdict = None
	else:
		agent_verdict = bool(agent['success'])

	judge_verdict: bool | None
	if result.judgement is None:
		judge_verdict = None
	else:
		judge_verdict = bool(result.judgement.verdict)

	if judge_verdict is None or agent_verdict is None:
		verdict_agreement: bool | None = None
	else:
		verdict_agreement = agent_verdict == judge_verdict

	hist_rel = _resolve_agent_history_path(run_dir, scenario_index)
	agent_history_path = _relative_under_root(hist_rel, output_root) if hist_rel else None

	screens: list[str] = []
	for p in result.screenshot_paths:
		if p:
			screens.append(_relative_under_root(p, output_root))

	row: dict[str, Any] = {
		'eval_id': eval_id,
		'run_id': f'run_{run_index}',
		'run_index': run_index,
		'scenario_index': scenario_index,
		'scenario_name': sc.name,
		'target_url': report.url,
		'test_persona': sc.test_persona,
		'priority': sc.priority,
		'feature_category': sc.feature_category,
		'target_feature': sc.target_feature,
		'success_criteria': sc.success_criteria,
		'steps_description': sc.steps_description,
		'step_count': len(result.actions),
		'duration_s': float(result.duration),
		'pages_visited': list(result.pages_visited),
		'form_fills': [dict(x) for x in result.form_fills],
		'errors': list(result.errors),
		'agent_self_verdict': agent_verdict,
		'agent_reason': _truncate(agent['reason'], max_narrative_chars) if agent else '',
		'agent_process_evaluation': _truncate((agent or {}).get('process_evaluation') or '', max_narrative_chars),
		'agent_logical_evaluation': _truncate((agent or {}).get('logical_evaluation') or '', max_narrative_chars),
		'agent_usability_evaluation': _truncate((agent or {}).get('usability_evaluation') or '', max_narrative_chars),
		'agent_validation_evidence': _truncate((agent or {}).get('validation_evidence') or '', max_narrative_chars),
		'judge_verdict': judge_verdict,
		'judge_reasoning': '',
		'judge_failure_reason': '',
		'failure_category': result.failure_category,
		'impossible_task': bool(result.judgement.impossible_task) if result.judgement is not None else False,
		'feedback_quality': _feedback_quality_dict(result),
		'missing_signals': list(result.missing_signals),
		'verdict_agreement': verdict_agreement,
		'report_timestamp': report.timestamp,
		'agent_history_path': agent_history_path,
		'screenshot_paths': screens,
	}

	if result.judgement is not None:
		row['judge_reasoning'] = _truncate(result.judgement.reasoning, max_narrative_chars)
		row['judge_failure_reason'] = _truncate(result.judgement.failure_reason, max_narrative_chars)

	return row


def apply_redactions(row: dict[str, Any], terms: list[str]) -> dict[str, Any]:
	"""Deep copy row and redact sensitive strings (emails + custom terms)."""
	out = copy.deepcopy(row)

	def rt(s: str) -> str:
		return redact_text(s, terms)

	for key in (
		'target_url',
		'success_criteria',
		'steps_description',
		'agent_reason',
		'agent_process_evaluation',
		'agent_logical_evaluation',
		'agent_usability_evaluation',
		'agent_validation_evidence',
		'judge_reasoning',
		'judge_failure_reason',
	):
		if key in out and isinstance(out[key], str):
			out[key] = rt(out[key])

	if isinstance(out.get('pages_visited'), list):
		out['pages_visited'] = [rt(x) if isinstance(x, str) else x for x in out['pages_visited']]

	if isinstance(out.get('errors'), list):
		new_err: list[str | None] = []
		for e in out['errors']:
			if isinstance(e, str):
				new_err.append(rt(e))
			else:
				new_err.append(e)
		out['errors'] = new_err

	if isinstance(out.get('missing_signals'), list):
		out['missing_signals'] = [rt(x) if isinstance(x, str) else x for x in out['missing_signals']]

	if isinstance(out.get('form_fills'), list):
		for item in out['form_fills']:
			if isinstance(item, dict):
				for fk, fv in list(item.items()):
					if isinstance(fv, str):
						item[fk] = rt(fv)

	return out


def collect_eval_dataset_rows(
	output_root: Path,
	eval_id: str,
	*,
	max_narrative_chars: int = 4096,
	redact_terms: list[str] | None = None,
	redact_terms_file: Path | None = None,
) -> list[dict[str, Any]]:
	"""Load all ``run_*`` reports and return one row per (run × scenario)."""
	output_root = output_root.resolve()
	terms = normalize_redact_terms(list(redact_terms or []), redact_terms_file)
	rows: list[dict[str, Any]] = []
	for run_index, run_dir in discover_run_dirs(output_root):
		report_path = run_dir / 'evaluation_report.json'
		if not report_path.is_file():
			print(f'WARNING: skipping {run_dir.name}: no evaluation_report.json', file=sys.stderr)
			continue
		report = EvaluationReport.model_validate_json(report_path.read_text(encoding='utf-8'))
		for i, result in enumerate(report.results, start=1):
			row = build_eval_run_row(
				eval_id,
				run_index,
				run_dir,
				output_root,
				report,
				i,
				result,
				max_narrative_chars=max_narrative_chars,
			)
			rows.append(apply_redactions(row, terms))
	return rows


def _jsonl_write(rows: Iterable[dict[str, Any]], f: TextIO) -> None:
	for row in rows:
		f.write(json.dumps(row, ensure_ascii=False) + '\n')


def _csv_fieldnames(rows: list[dict[str, Any]]) -> list[str]:
	if not rows:
		return []
	preferred = [
		'eval_id',
		'run_id',
		'run_index',
		'scenario_index',
		'scenario_name',
		'target_url',
		'test_persona',
		'priority',
		'feature_category',
		'target_feature',
		'success_criteria',
		'steps_description',
		'step_count',
		'duration_s',
		'pages_visited',
		'form_fills',
		'errors',
		'agent_self_verdict',
		'agent_reason',
		'agent_process_evaluation',
		'agent_logical_evaluation',
		'agent_usability_evaluation',
		'agent_validation_evidence',
		'judge_verdict',
		'judge_reasoning',
		'judge_failure_reason',
		'failure_category',
		'impossible_task',
		'feedback_quality',
		'missing_signals',
		'verdict_agreement',
		'report_timestamp',
		'agent_history_path',
		'screenshot_paths',
	]
	seen = set()
	order: list[str] = []
	for k in preferred:
		if k in rows[0]:
			order.append(k)
			seen.add(k)
	for k in rows[0]:
		if k not in seen:
			order.append(k)
	return order


def _flatten_csv_value(v: Any) -> str:
	if v is None:
		return ''
	if isinstance(v, bool):
		return 'true' if v else 'false'
	if isinstance(v, (dict, list)):
		return json.dumps(v, ensure_ascii=False)
	return str(v)


def _csv_write(rows: list[dict[str, Any]], f: TextIO) -> None:
	if not rows:
		return
	fieldnames = _csv_fieldnames(rows)
	w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
	w.writeheader()
	for row in rows:
		flat = {k: _flatten_csv_value(row.get(k)) for k in fieldnames}
		w.writerow(flat)


def _write_output(path: Path, fmt: str, rows: list[dict[str, Any]]) -> None:
	with open(path, 'w', encoding='utf-8', newline='') as stream:
		if fmt == 'jsonl':
			_jsonl_write(rows, stream)
		else:
			_csv_write(rows, stream)


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(
		description='Export run_*/evaluation_report.json to a single eval dataset (JSONL or CSV).',
	)
	parser.add_argument(
		'--output-root',
		type=Path,
		default=Path('murphy/output'),
		help='Directory containing run_1, run_2, … (default: murphy/output)',
	)
	parser.add_argument(
		'--eval-id',
		default='eval_test_1',
		help='Stable id for this eval suite (default: eval_test_1)',
	)
	parser.add_argument(
		'--format',
		choices=('jsonl', 'csv'),
		default='jsonl',
		help='Output format (default: jsonl)',
	)
	parser.add_argument(
		'--out',
		type=Path,
		default=None,
		help='Output file path (default: <output-root>/eval_run_rows.<ext>)',
	)
	parser.add_argument(
		'--out-rows',
		type=Path,
		default=None,
		help=argparse.SUPPRESS,
	)
	parser.add_argument(
		'--max-narrative-chars',
		type=int,
		default=4096,
		help='Max length for judge/agent narrative fields (0 = empty those fields; default: 4096)',
	)
	parser.add_argument(
		'--redact-term',
		action='append',
		default=[],
		metavar='TEXT',
		help='Extra term to redact as [REDACTED_ORG] (repeatable); case-insensitive substring',
	)
	parser.add_argument(
		'--redact-terms-file',
		type=Path,
		default=None,
		help='File with one redaction term per line (# comments allowed)',
	)
	args = parser.parse_args(argv)

	output_root = args.output_root
	ext = 'jsonl' if args.format == 'jsonl' else 'csv'
	out_path = args.out or args.out_rows or (output_root / f'eval_run_rows.{ext}')

	rows = collect_eval_dataset_rows(
		output_root,
		args.eval_id,
		max_narrative_chars=args.max_narrative_chars,
		redact_terms=args.redact_term,
		redact_terms_file=args.redact_terms_file,
	)

	if not rows:
		# No valid runs — check if any run dirs existed
		if not discover_run_dirs(output_root.resolve()):
			print(f'ERROR: no run_* directories under {output_root.resolve()}', file=sys.stderr)
		else:
			print(
				f'ERROR: no evaluation_report.json found under run_* in {output_root.resolve()}',
				file=sys.stderr,
			)
		return 2

	output_root.mkdir(parents=True, exist_ok=True)
	out_path.parent.mkdir(parents=True, exist_ok=True)
	_write_output(out_path, args.format, rows)
	print(f'Wrote {len(rows)} row(s) to {out_path.resolve()}', file=sys.stderr)
	return 0


if __name__ == '__main__':
	raise SystemExit(main())
