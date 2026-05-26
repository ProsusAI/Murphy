#!/usr/bin/env python3
"""Seed NavigationModel from existing Murphy agent_history logs.

Usage:
    python scripts/seed_navigation_model.py
    python scripts/seed_navigation_model.py --input output/eval_with_embeddings --output output/navigation_model.json
    python scripts/seed_navigation_model.py --all-runs   # include failed runs too
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Add repo root to path so murphy package is importable without install
sys.path.insert(0, str(Path(__file__).parent.parent))

from murphy.process.model import NavigationModel

# Matches UUIDs (8-4-4-4-12 hex) anywhere in a URL path segment
_UUID_RE = re.compile(
	r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
	re.IGNORECASE,
)


def normalise_uuid(url: str) -> str:
	"""Replace all UUIDs in a URL with the literal placeholder ``{id}``."""
	return _UUID_RE.sub('{id}', url)


def extract_urls_from_history(history_path: Path) -> list[str]:
	"""Return the ordered, deduplicated URL sequence from one agent_history file."""
	try:
		data = json.loads(history_path.read_text())
	except Exception:
		return []

	raw: list[str] = []
	for step in data.get('history', []):
		url = step.get('state', {}).get('url', '')
		if url and url.startswith('http'):
			raw.append(normalise_uuid(url))

	# Deduplicate consecutive duplicates (same page reloaded / minor fragment change)
	deduped: list[str] = []
	for url in raw:
		if not deduped or url != deduped[-1]:
			deduped.append(url)
	return deduped


def load_successful_scenario_names(report_path: Path) -> set[str] | None:
	"""Return the set of *successful* scenario names from an evaluation_report.json.

	Returns None if the report cannot be parsed (caller should fall back to all runs).
	"""
	try:
		data = json.loads(report_path.read_text())
		return {r['scenario']['name'] for r in data.get('results', []) if r.get('success')}
	except Exception:
		return None


def _iter_history_dirs(input_dir: Path, all_runs: bool):
	"""Yield (agent_history_dir, successful_names_or_None) pairs.

	Supports two layouts:
	  - Flat:  input_dir/agent_history/test_*.json  (single run)
	  - Multi: input_dir/run_N/agent_history/test_*.json
	"""
	flat_history = input_dir / 'agent_history'
	if flat_history.exists():
		report_path = input_dir / 'evaluation_report.json'
		successful_names: set[str] | None = None
		if not all_runs and report_path.exists():
			successful_names = load_successful_scenario_names(report_path)
		yield flat_history, successful_names
		return

	run_dirs = sorted(input_dir.glob('run_*/'))
	if not run_dirs:
		print(f'No agent_history directory or run_N subdirectories found under {input_dir}')
		sys.exit(1)

	for run_dir in run_dirs:
		agent_history_dir = run_dir / 'agent_history'
		if not agent_history_dir.exists():
			continue
		report_path = run_dir / 'evaluation_report.json'
		successful_names = None
		if not all_runs and report_path.exists():
			successful_names = load_successful_scenario_names(report_path)
		yield agent_history_dir, successful_names


def seed(input_dir: Path, output_path: Path, all_runs: bool) -> None:
	model = NavigationModel(output_path)
	total_sequences = 0

	for agent_history_dir, successful_names in _iter_history_dirs(input_dir, all_runs):
		for history_file in sorted(agent_history_dir.glob('test_*.json')):
			if successful_names is not None:
				stem = history_file.stem
				matched = any(name.lower().replace(' ', '_') in stem.lower() for name in successful_names)
				if not matched:
					continue

			urls = extract_urls_from_history(history_file)
			if len(urls) < 2:
				continue

			from urllib.parse import urlparse

			parsed = urlparse(urls[0])
			base_url = f'{parsed.scheme}://{parsed.netloc}'

			model.update(base_url, urls)
			total_sequences += 1

	model.save()
	print(f'Seeded {total_sequences} URL sequences into {output_path}')

	if model._data:
		sample_base = next(iter(model._data))
		hints = model.get_hints(sample_base)
		print(f'Hints for {sample_base}: {hints}')
	else:
		print('Warning: model is empty — no sequences were added.')


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		'--input',
		type=Path,
		default=Path('output/eval_with_embeddings/medium_goal_v3'),
		help='Root directory containing run_N sub-directories',
	)
	parser.add_argument(
		'--output',
		type=Path,
		default=Path('output/navigation_model.json'),
		help='Path to write navigation_model.json',
	)
	parser.add_argument(
		'--all-runs',
		action='store_true',
		help='Include failed runs (default: successful runs only, fallback to all if no report)',
	)
	args = parser.parse_args()
	seed(args.input, args.output, args.all_runs)


if __name__ == '__main__':
	main()
