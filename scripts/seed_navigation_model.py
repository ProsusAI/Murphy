#!/usr/bin/env python3
"""Seed NavigationModel from existing Murphy agent_history logs.

Usage:
    python scripts/seed_navigation_model.py
    python scripts/seed_navigation_model.py --input output/my_runs --output output/navigation_model.json
    python scripts/seed_navigation_model.py --input output/run_a output/run_b --output output/navigation_model.json
    python scripts/seed_navigation_model.py --all-runs
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from murphy.process.model import NavigationModel

_UUID_RE = re.compile(
	r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
	re.IGNORECASE,
)


def normalise_uuid(url: str) -> str:
	return _UUID_RE.sub('{id}', url)


def extract_urls_from_history(history_path: Path) -> list[str]:
	try:
		data = json.loads(history_path.read_text())
	except Exception:
		return []
	raw: list[str] = []
	for step in data.get('history', []):
		url = step.get('state', {}).get('url', '')
		if url and url.startswith('http'):
			raw.append(normalise_uuid(url))
	deduped: list[str] = []
	for url in raw:
		if not deduped or url != deduped[-1]:
			deduped.append(url)
	return deduped


def extract_goal_from_test_plan(run_dir: Path) -> str | None:
	"""Read goal from run_1/test_plan.yaml.

	Tries the 'goal' field first (present in runs after the goal-keyed PBM was added).
	Falls back to joining target_feature values from scenarios (older runs).
	"""
	plan_path = run_dir / 'run_1' / 'test_plan.yaml'
	if not plan_path.exists():
		plan_path = run_dir / 'test_plan.yaml'
	if not plan_path.exists():
		return None
	try:
		import yaml

		data = yaml.safe_load(plan_path.read_text())
		if not isinstance(data, dict):
			return None
		if data.get('goal'):
			return str(data['goal']).strip()
		features = [s.get('target_feature', '') for s in data.get('scenarios', []) if s.get('target_feature')]
		if features:
			return ', '.join(dict.fromkeys(features))
	except Exception:
		pass
	return None


def load_successful_scenario_names(report_path: Path) -> set[str] | None:
	try:
		data = json.loads(report_path.read_text())
		return {r['scenario']['name'] for r in data.get('results', []) if r.get('success')}
	except Exception:
		return None


def seed(input_dirs: list[Path], output_path: Path, all_runs: bool) -> None:
	model = NavigationModel(output_path)
	total_sequences = 0

	for input_dir in input_dirs:
		run_dirs = sorted(input_dir.glob('run_*/'))
		if not run_dirs:
			print(f'No run directories found under {input_dir}, skipping.')
			continue

		for run_dir in run_dirs:
			agent_history_dir = run_dir / 'agent_history'
			if not agent_history_dir.exists():
				continue
			report_path = run_dir / 'evaluation_report.json'
			successful_names: set[str] | None = None
			if not all_runs and report_path.exists():
				successful_names = load_successful_scenario_names(report_path)

			goal = extract_goal_from_test_plan(input_dir)

			for history_file in sorted(agent_history_dir.glob('test_*.json')):
				if successful_names is not None:
					# Filenames are truncated slugs of scenario names, so check whether
					# the stem (minus the test_NN_ prefix) appears inside the full name slug.
					stem_part = re.sub(r'^test_\d+_', '', history_file.stem.lower())
					matched = any(stem_part in name.lower().replace(' ', '_') for name in successful_names)
					if not matched:
						continue
				urls = extract_urls_from_history(history_file)
				if len(urls) < 2:
					continue
				parsed = urlparse(urls[0])
				base_url = f'{parsed.scheme}://{parsed.netloc}'
				model.update(base_url, urls, goal)
				total_sequences += 1

	model.save()
	print(f'Seeded {total_sequences} URL sequences into {output_path}')
	if model._data:
		sample_base = next(iter(model._data))
		sample_goal = next(iter(model._data[sample_base]))
		hints = model.get_hints(sample_base, sample_goal)
		print(f'Hints for {sample_base} / goal="{sample_goal}": {hints}')
	else:
		print('Warning: model is empty — no sequences were added.')


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		'--input',
		type=Path,
		nargs='+',
		default=[Path('output/eval_with_embeddings/medium_goal_v3')],
		help='One or more run directories to seed from',
	)
	parser.add_argument('--output', type=Path, default=Path('output/navigation_model.json'))
	parser.add_argument('--all-runs', action='store_true')
	args = parser.parse_args()
	seed(args.input, args.output, args.all_runs)


if __name__ == '__main__':
	main()
