"""Automated persona prompt optimization loop.

For each iteration:
  1. Run the persona prompt optimizer against the current eval report.
  2. Show the proposed diff and ask y/N to apply.
  3. Apply changes to DESCRIPTION_INSTRUCTION and EXECUTION_HINTS_INSTRUCTION.
  4. Re-label personas on the same centroids (no PostHog re-fetch).
  5. Re-run Murphy N times with the same test plan.
  6. Re-run the persona similarity eval.
  7. Repeat with the new report.

Usage:
    uv run python scripts/auto_loop.py \\
        --report output/eval_with_embeddings/medium_goal/persona_similarity_report.json \\
        --personas-file output/similarity_run/personas.json \\
        --plan output/eval_with_embeddings/medium_goal/run_1/test_plan.yaml \\
        --url https://work.toqan.ai/ \\
        --output-dir output/auto_loop \\
        --iterations 3 \\
        --runs 5
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def _avg_similarity_from_report(report_path: Path) -> float | None:
	try:
		data = json.loads(report_path.read_text())
		results = data.get('results', [])
		if not results:
			return None
		return sum(r['overall_similarity_score'] for r in results) / len(results)
	except Exception:
		return None


def _run_murphy_batch(
	url: str,
	plan_path: Path,
	iter_dir: Path,
	runs: int,
	no_auth: bool,
) -> bool:
	"""Run Murphy N times, writing to iter_dir/run_1 … run_N. Returns True on success."""
	any_fail = False
	for n in range(1, runs + 1):
		run_dir = iter_dir / f'run_{n}'
		run_dir.mkdir(parents=True, exist_ok=True)
		cmd = [
			sys.executable,
			'-m',
			'murphy.api.cli',
			'--url',
			url,
			'--plan',
			str(plan_path),
			'--personas',
			str(iter_dir / 'personas.json'),
			'--output-dir',
			str(run_dir),
		]
		if no_auth:
			cmd.append('--no-auth')
		print(f'\n=== Murphy run {n}/{runs} → {run_dir} ===\n', flush=True)
		proc = subprocess.run(cmd, cwd=str(_REPO_ROOT))
		if proc.returncode != 0:
			logger.warning('murphy exited %d on run_%d', proc.returncode, n)
			any_fail = True
	return not any_fail


def _run_eval(iter_dir: Path, personas_path: Path, model: str) -> Path | None:
	"""Run eval_persona_similarity.py against iter_dir. Returns report path on success."""
	cmd = [
		sys.executable,
		str(_REPO_ROOT / 'scripts' / 'eval_persona_similarity.py'),
		'--output-dir',
		str(iter_dir),
		'--personas-file',
		str(personas_path),
		'--model',
		model,
	]
	print('\n=== Running persona similarity eval ===\n', flush=True)
	proc = subprocess.run(cmd, cwd=str(_REPO_ROOT))
	if proc.returncode != 0:
		logger.error('eval script exited %d', proc.returncode)
		return None
	report = iter_dir / 'persona_similarity_report.json'
	return report if report.is_file() else None


async def _run_iteration(
	iteration: int,
	report_path: Path,
	personas_path: Path,
	plan_path: Path,
	url: str,
	base_output_dir: Path,
	runs: int,
	llm_model: str,
	threshold: float,
	no_auth: bool,
	auto_yes: bool = False,
) -> tuple[Path, Path] | None:
	"""Run one optimization iteration. Returns (new_report_path, new_personas_path) or None."""
	from browser_use.llm import ChatOpenAI
	from murphy.personas.optimizer import (
		PERSONA_LABELING_PATH,
		apply_optimization,
		optimize_persona_prompts,
		relabel_personas,
	)

	iter_dir = base_output_dir / f'iteration_{iteration}'
	iter_dir.mkdir(parents=True, exist_ok=True)

	print(f'\n{"=" * 50}')
	print(f' ITERATION {iteration}')
	print(f'{"=" * 50}\n')

	llm = ChatOpenAI(model=llm_model)

	result = await optimize_persona_prompts(
		report_path=report_path,
		personas_path=personas_path,
		llm=llm,
		similarity_threshold=threshold,
	)

	print(f'\nAnalyzed {len(result.underperforming_personas)} underperforming persona(s) (avg similarity < {threshold}):')
	for d in result.underperforming_personas:
		print(f'  • {d.persona_name}: {d.avg_similarity:.2f} (worst: {d.worst_dimension}, delta={d.worst_dim_delta:+.2f})')

	print('\nRationale:')
	for line in result.rationale.splitlines():
		print(f'  {line}')

	print('\n--- Proposed diff ---')
	if result.diff:
		print(result.diff)
	else:
		print('(no changes proposed — skipping iteration)')
		return None

	if auto_yes:
		print('\nAuto-applying changes (--yes).')
		answer = 'y'
	else:
		print('\nApply these changes and continue? [y/N] ', end='', flush=True)
		answer = input().strip().lower()
	if answer != 'y':
		print('Skipping iteration.')
		return None

	# Apply changes and reload the module so subsequent iterations see the new constants
	apply_optimization(result.proposed_description_instruction, result.proposed_execution_hints_instruction)
	print(f'Updated {PERSONA_LABELING_PATH}')

	import murphy.personas.persona_labeling as _pl

	importlib.reload(_pl)

	# Re-label personas on same centroids with new LABEL_SYSTEM
	print('\nRe-labeling personas...')
	llm_relabel = ChatOpenAI(model=llm_model)
	await relabel_personas(personas_path, llm_relabel, iter_dir)
	new_personas_path = iter_dir / 'personas.json'
	print(f'Saved relabeled personas to {new_personas_path}')

	# Run Murphy
	_run_murphy_batch(url, plan_path, iter_dir, runs, no_auth)

	# Run eval
	new_report_path = _run_eval(iter_dir, new_personas_path, llm_model)
	if new_report_path is None:
		logger.error('Eval failed for iteration %d', iteration)
		return None

	avg = _avg_similarity_from_report(new_report_path)
	print(f'\nIteration {iteration} complete. Avg similarity: {avg:.3f}' if avg else f'\nIteration {iteration} complete.')

	return new_report_path, new_personas_path


async def _async_main(args: argparse.Namespace) -> int:
	report_path = args.report.resolve()
	personas_path = args.personas_file.resolve()
	plan_path = args.plan.resolve()
	base_output_dir = args.output_dir.resolve()

	for p, label in [(report_path, '--report'), (personas_path, '--personas-file'), (plan_path, '--plan')]:
		if not p.is_file():
			logger.error('%s not found: %s', label, p)
			return 2

	base_output_dir.mkdir(parents=True, exist_ok=True)

	baseline_avg = _avg_similarity_from_report(report_path)
	similarity_history: list[tuple[str, float | None]] = [('baseline', baseline_avg)]

	current_report = report_path
	current_personas = personas_path

	for i in range(1, args.iterations + 1):
		outcome = await _run_iteration(
			iteration=i,
			report_path=current_report,
			personas_path=current_personas,
			plan_path=plan_path,
			url=args.url,
			base_output_dir=base_output_dir,
			runs=args.runs,
			llm_model=args.model,
			threshold=args.threshold,
			no_auth=args.no_auth,
			auto_yes=args.yes,
		)
		if outcome is None:
			print(f'\nStopped at iteration {i}.')
			break
		current_report, current_personas = outcome
		avg = _avg_similarity_from_report(current_report)
		similarity_history.append((f'iteration_{i}', avg))

	# Summary
	print(f'\n{"=" * 50}')
	print(' LOOP SUMMARY')
	print(f'{"=" * 50}')
	prev: float | None = None
	for label, avg in similarity_history:
		if avg is None:
			print(f'  {label}: n/a')
		elif prev is None:
			print(f'  {label}: {avg:.3f}')
		else:
			delta = avg - prev
			sign = '+' if delta >= 0 else ''
			print(f'  {label}: {avg:.3f} ({sign}{delta:.3f})')
		prev = avg

	return 0


def main() -> int:
	parser = argparse.ArgumentParser(
		description='Automated persona prompt optimization loop.',
		formatter_class=argparse.ArgumentDefaultsHelpFormatter,
	)
	parser.add_argument('--report', type=Path, required=True, help='Starting persona_similarity_report.json')
	parser.add_argument('--personas-file', type=Path, required=True, help='Starting personas.json')
	parser.add_argument('--plan', type=Path, required=True, help='Test plan YAML (reused across iterations)')
	parser.add_argument('--url', required=True, help='Target URL for Murphy runs')
	parser.add_argument('--output-dir', type=Path, default=Path('output/auto_loop'), help='Base output directory')
	parser.add_argument('--iterations', type=int, default=3, help='Number of optimization iterations')
	parser.add_argument('--runs', type=int, default=5, help='Murphy runs per iteration')
	parser.add_argument('--model', default='gpt-4o', help='LLM model for optimizer and eval')
	parser.add_argument('--threshold', type=float, default=0.85, help='Similarity threshold for underperformers')
	parser.add_argument('--no-auth', action='store_true', help='Pass --no-auth to Murphy')
	parser.add_argument('--yes', action='store_true', help='Auto-confirm all iterations without prompting')
	args = parser.parse_args()
	return asyncio.run(_async_main(args))


if __name__ == '__main__':
	sys.exit(main())
