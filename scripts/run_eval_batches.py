"""Run Murphy multiple times with the same frozen eval plan.

Each invocation uses ``--output-dir <output-root>/run_<n>/``. Before each run, the
plan file is copied into that directory as ``eval_test_1.yaml`` so the folder is
self-contained (plan + ``agent_history/``, ``screenshots/``, evaluation reports).

Usage (from repo root)::

    uv run python scripts/run_eval_batches.py
    uv run python scripts/run_eval_batches.py --runs 5
    uv run python scripts/run_eval_batches.py -- --no-auth --parallel 2

Extra arguments after ``--`` are forwarded to ``murphy`` unchanged.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(_REPO_ROOT))


def _split_batch_and_murphy(argv: list[str]) -> tuple[list[str], list[str]]:
	if '--' in argv:
		i = argv.index('--')
		return argv[:i], argv[i + 1 :]
	return argv, []


def main() -> int:
	batch_argv, murphy_argv = _split_batch_and_murphy(sys.argv[1:])
	default_plan = _REPO_ROOT / 'murphy' / 'output' / 'eval_test_1.yaml'
	default_root = _REPO_ROOT / 'murphy' / 'output'

	parser = argparse.ArgumentParser(
		description=(
			'Run Murphy N times with the same eval plan. Each run writes to '
			'<output-root>/run_<n>/ (including a copy of the plan as eval_test_1.yaml).'
		),
	)
	parser.add_argument(
		'--plan',
		type=Path,
		default=default_plan,
		help=f'Source eval plan YAML (default: {default_plan})',
	)
	parser.add_argument(
		'--output-root',
		type=Path,
		default=default_root,
		help=f'Parent directory for run_1, run_2, … (default: {default_root})',
	)
	parser.add_argument('--runs', type=int, default=10, metavar='N', help='Number of runs (default: 10)')
	parser.add_argument('--url', help='Override target URL (default: read from plan file)')
	parser.add_argument(
		'--continue-on-fail',
		action='store_true',
		help='Continue after a non-zero murphy exit (still exits 1 at the end if any run failed)',
	)
	args = parser.parse_args(batch_argv)

	plan_src = args.plan.resolve()
	if not plan_src.is_file():
		print(f'ERROR: plan not found: {plan_src}', file=sys.stderr)
		return 2

	from murphy.io.test_plan_io import load_test_plan

	url, _ = load_test_plan(plan_src)
	if args.url:
		url = args.url

	output_root = args.output_root.resolve()
	output_root.mkdir(parents=True, exist_ok=True)

	snapshot_name = plan_src.name
	any_fail = False
	for n in range(1, args.runs + 1):
		run_dir = output_root / f'run_{n}'
		run_dir.mkdir(parents=True, exist_ok=True)
		plan_snapshot = run_dir / snapshot_name
		shutil.copy2(plan_src, plan_snapshot)

		cmd = [
			sys.executable,
			'-m',
			'murphy.api.cli',
			'--url',
			url,
			'--plan',
			str(plan_snapshot),
			'--output-dir',
			str(run_dir),
			*murphy_argv,
		]
		print(f'\n=== Eval run {n}/{args.runs} -> {run_dir} ===\n', flush=True)
		proc = subprocess.run(cmd, cwd=str(_REPO_ROOT))
		if proc.returncode != 0:
			any_fail = True
			print(f'WARNING: murphy exited with code {proc.returncode} (run_{n})', file=sys.stderr)
			if not args.continue_on_fail:
				return proc.returncode

	return 1 if any_fail else 0


if __name__ == '__main__':
	sys.exit(main())
