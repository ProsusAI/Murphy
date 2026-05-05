"""Evaluate how closely Murphy mimics the behavior of discovered user personas.

For each Murphy test that used a discovered persona, this script:
  1. Loads the agent_history trace from the output directory.
  2. Converts it to a behavioral timeline (same format as real PostHog sessions).
  3. Scores it with score_session() against the trait schema.
  4. Compares the scores to the persona centroid (real-user average for that cluster).
  5. Writes persona_similarity_report.json and persona_similarity_report.md.

The persona centroid is the mean trait score of all real PostHog sessions in that
cluster, so comparing Murphy against it is comparing against real users (in aggregate).

Usage (single run):
    uv run python scripts/eval_persona_similarity.py \\
        --output-dir murphy/output \\
        --personas-file output/personas.json

Usage (batch runs in run_1/, run_2/, ...):
    uv run python scripts/eval_persona_similarity.py \\
        --output-dir murphy/output \\
        --personas-file output/personas.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

_RUN_DIR_RE = re.compile(r'^run_(\d+)$')


# ── Helpers ───────────────────────────────────────────────────────────────────


def _discover_run_dirs(output_dir: Path) -> list[tuple[int, Path]]:
	"""Return (run_index, run_dir) pairs sorted by run_index."""
	runs: list[tuple[int, Path]] = []
	for p in output_dir.iterdir():
		if not p.is_dir():
			continue
		m = _RUN_DIR_RE.fullmatch(p.name)
		if m:
			runs.append((int(m.group(1)), p))
	return sorted(runs, key=lambda x: x[0])


def _resolve_agent_history(run_dir: Path, scenario_index: int) -> Path | None:
	"""Find the agent_history file for scenario N inside run_dir."""
	adir = run_dir / 'agent_history'
	if not adir.is_dir():
		return None
	matches = sorted(adir.glob(f'test_{scenario_index:02d}_*.json'))
	return matches[0] if matches else None


def _similarity_label(score: float) -> str:
	if score >= 0.85:
		return 'HIGH'
	if score >= 0.70:
		return 'MEDIUM'
	return 'LOW'


# ── Main ──────────────────────────────────────────────────────────────────────


async def _async_main(args: argparse.Namespace) -> int:
	from browser_use.llm import ChatOpenAI
	from murphy.eval.models import SimilarityReport
	from murphy.eval.similarity import evaluate_similarity
	from murphy.models import EvaluationReport
	from murphy.personas.bridge import lookup_persona_by_slug
	from murphy.personas.storage import load_personas

	output_dir = args.output_dir.resolve()
	personas_path = args.personas_file.resolve()

	if not personas_path.is_file():
		logger.error('Personas file not found: %s', personas_path)
		return 2

	schema, persona_result = load_personas(personas_path)
	logger.info('Loaded %d personas from %s', len(persona_result.personas), personas_path)

	llm = ChatOpenAI(model=args.model)

	# Support both single-run (evaluation_report.json at root) and
	# batch-run (run_1/, run_2/, ... subdirs) layouts.
	if (output_dir / 'evaluation_report.json').is_file():
		run_dirs: list[tuple[int, Path]] = [(1, output_dir)]
	else:
		run_dirs = _discover_run_dirs(output_dir)
		if not run_dirs:
			logger.error('No evaluation_report.json found in %s or its run_* subdirs', output_dir)
			return 2

	similarity_results = []

	for _run_idx, run_dir in run_dirs:
		report_path = run_dir / 'evaluation_report.json'
		if not report_path.is_file():
			logger.warning('Skipping %s: no evaluation_report.json', run_dir.name)
			continue

		report = EvaluationReport.model_validate_json(report_path.read_text(encoding='utf-8'))
		logger.info('Processing %s (%d scenarios)', run_dir.name, len(report.results))

		for scenario_idx, result in enumerate(report.results, start=1):
			persona_slug = result.scenario.test_persona
			persona = lookup_persona_by_slug(persona_slug, persona_result)
			if persona is None:
				# Predefined persona (happy_path, etc.) — not scoreable against centroid
				logger.debug('Skipping predefined persona: %s', persona_slug)
				continue

			history_path = _resolve_agent_history(run_dir, scenario_idx)
			if history_path is None:
				logger.warning(
					'No agent history for scenario %d (%s) in %s',
					scenario_idx,
					result.scenario.name,
					run_dir.name,
				)
				continue

			logger.info('Evaluating similarity: "%s" (persona=%s)', result.scenario.name, persona_slug)
			try:
				similarity = await evaluate_similarity(
					persona=persona,
					schema=schema,
					history_path=history_path,
					scenario_name=result.scenario.name,
					scenario_steps=result.scenario.steps_description,
					llm=llm,
				)
				similarity_results.append(similarity)
			except Exception:
				logger.exception('Failed similarity eval for "%s"', result.scenario.name)

	if not similarity_results:
		logger.warning('No discovered-persona tests found. Run Murphy with --personas to use discovered personas.')
		return 0

	from murphy.eval.similarity import generate_key_takeaways

	report_obj = SimilarityReport(
		personas_file=str(personas_path),
		output_dir=str(output_dir),
		timestamp=datetime.now().isoformat(timespec='seconds'),
		results=similarity_results,
	)
	report_obj.key_takeaways = await generate_key_takeaways(report_obj, llm)

	# Write JSON
	json_path = output_dir / 'persona_similarity_report.json'
	json_path.write_text(report_obj.model_dump_json(indent=2), encoding='utf-8')
	logger.info('Wrote %s', json_path)

	# Write markdown
	md_path = output_dir / 'persona_similarity_report.md'
	from murphy.eval.runner import build_markdown_report

	md_path.write_text(build_markdown_report(json.loads(report_obj.model_dump_json())), encoding='utf-8')
	logger.info('Wrote %s', md_path)

	# Print summary
	total = len(similarity_results)
	avg_similarity = sum(r.overall_similarity_score for r in similarity_results) / total
	print(f'\nEvaluated {total} test(s).')
	print(f'Average similarity: {avg_similarity:.2f} ({_similarity_label(avg_similarity)})')
	print(f'Report: {md_path}')
	return 0


def main() -> int:
	parser = argparse.ArgumentParser(
		description='Evaluate how closely Murphy mimics discovered user personas.',
		formatter_class=argparse.ArgumentDefaultsHelpFormatter,
	)
	parser.add_argument(
		'--output-dir',
		type=Path,
		default=Path('murphy/output'),
		help='Murphy output directory (single run or parent of run_1/, run_2/, ...)',
	)
	parser.add_argument(
		'--personas-file',
		type=Path,
		default=Path('output/personas.json'),
		help='Path to personas.json produced by the discovery pipeline',
	)
	parser.add_argument(
		'--model',
		default='gpt-4o-mini',
		help='LLM model for behavioral scoring',
	)
	args = parser.parse_args()
	return asyncio.run(_async_main(args))


if __name__ == '__main__':
	sys.exit(main())
