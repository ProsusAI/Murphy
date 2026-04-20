"""Orchestrate the persona similarity eval for a single Murphy output directory.

Used by both the CLI (--eval-similarity flag) and the standalone
scripts/eval_persona_similarity.py runner.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from browser_use.llm import ChatOpenAI
from murphy.eval.models import PersonaSimilarityResult, SimilarityReport
from murphy.eval.similarity import evaluate_similarity
from murphy.models import EvaluationReport
from murphy.personas.bridge import lookup_persona_by_slug
from murphy.personas.pipeline_models import PersonaResult, TraitSchema

logger = logging.getLogger(__name__)

_RUN_DIR_RE = re.compile(r'^run_(\d+)$')


# ── File helpers ──────────────────────────────────────────────────────────────


def discover_run_dirs(output_dir: Path) -> list[tuple[int, Path]]:
	"""Return (run_index, run_dir) pairs sorted by run_index."""
	runs: list[tuple[int, Path]] = []
	for p in output_dir.iterdir():
		if not p.is_dir():
			continue
		m = _RUN_DIR_RE.fullmatch(p.name)
		if m:
			runs.append((int(m.group(1)), p))
	return sorted(runs, key=lambda x: x[0])


def resolve_agent_history(run_dir: Path, scenario_index: int) -> Path | None:
	adir = run_dir / 'agent_history'
	if not adir.is_dir():
		return None
	matches = sorted(adir.glob(f'test_{scenario_index:02d}_*.json'))
	return matches[0] if matches else None


# ── Markdown ──────────────────────────────────────────────────────────────────


def _similarity_label(score: float) -> str:
	if score >= 0.85:
		return 'HIGH'
	if score >= 0.70:
		return 'MEDIUM'
	return 'LOW'


def build_markdown_report(report_data: dict[str, Any]) -> str:
	lines: list[str] = []
	lines.append('# Persona Similarity Report')
	lines.append(f'Generated: {report_data["timestamp"]}')
	lines.append(f'Personas file: {report_data["personas_file"]}')
	lines.append(f'Output dir: {report_data["output_dir"]}')
	lines.append('')

	results: list[dict[str, Any]] = report_data.get('results', [])
	if not results:
		lines.append('No discovered-persona tests found.')
		lines.append('')
		lines.append(
			'Make sure you ran Murphy with `--personas <path>` so that test scenarios are assigned to discovered personas.'
		)
		return '\n'.join(lines)

	by_persona: dict[str, list[float]] = defaultdict(list)
	for r in results:
		by_persona[r['persona_name']].append(r['overall_similarity_score'])

	lines.append('## Summary')
	lines.append('')
	lines.append('| Persona | Tests | Avg Similarity | Rating |')
	lines.append('|---------|-------|---------------|--------|')
	for persona_name, scores in sorted(by_persona.items()):
		avg = sum(scores) / len(scores)
		lines.append(f'| {persona_name} | {len(scores)} | {avg:.2f} | {_similarity_label(avg)} |')
	lines.append('')

	lines.append('## Detailed Results')
	lines.append('')
	for r in results:
		overall = r['overall_similarity_score']
		label = _similarity_label(overall)
		lines.append(f'### {r["test_scenario_name"]}')
		lines.append(f'**Persona:** `{r["persona_slug"]}`  |  **Overall similarity:** {overall:.2f} ({label})')
		lines.append('')
		lines.append('| Trait Dimension | Murphy | Real Users | Delta |')
		lines.append('|----------------|--------|-----------|-------|')
		for dim in r['dimensions']:
			delta = dim['delta']
			sign = '+' if delta >= 0 else ''
			lines.append(f'| {dim["trait_name"]} | {dim["murphy_score"]:.1f} | {dim["persona_score"]:.1f} | {sign}{delta:.1f} |')
		lines.append('')
		reasoning = r.get('scoring_reasoning', '').strip()
		if reasoning:
			lines.append(f'**Scoring rationale:** {reasoning}')
			lines.append('')

	return '\n'.join(lines)


# ── Orchestrator ──────────────────────────────────────────────────────────────


async def run_similarity_eval(
	output_dir: Path,
	schema: TraitSchema,
	persona_result: PersonaResult,
	llm: ChatOpenAI,
) -> SimilarityReport | None:
	"""Evaluate persona similarity for all discovered-persona tests in output_dir.

	Supports both single-run layout (evaluation_report.json at root) and
	batch-run layout (run_1/, run_2/, ... subdirs).

	Returns the SimilarityReport, or None if no matching tests were found.
	"""
	if (output_dir / 'evaluation_report.json').is_file():
		run_dirs: list[tuple[int, Path]] = [(1, output_dir)]
	else:
		run_dirs = discover_run_dirs(output_dir)
		if not run_dirs:
			logger.warning('No evaluation_report.json found in %s or its run_* subdirs', output_dir)
			return None

	similarity_results: list[PersonaSimilarityResult] = []

	for _run_idx, run_dir in run_dirs:
		report_path = run_dir / 'evaluation_report.json'
		if not report_path.is_file():
			logger.warning('Skipping %s: no evaluation_report.json', run_dir.name)
			continue

		report = EvaluationReport.model_validate_json(report_path.read_text(encoding='utf-8'))
		logger.info('Scoring similarity for %s (%d scenarios)', run_dir.name, len(report.results))

		for scenario_idx, result in enumerate(report.results, start=1):
			persona_slug = result.scenario.test_persona
			persona = lookup_persona_by_slug(persona_slug, persona_result)
			if persona is None:
				continue

			history_path = resolve_agent_history(run_dir, scenario_idx)
			if history_path is None:
				logger.warning('No agent history for scenario %d (%s)', scenario_idx, result.scenario.name)
				continue

			logger.info('  Evaluating "%s" (persona=%s)', result.scenario.name, persona_slug)
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
				logger.exception('Similarity eval failed for "%s"', result.scenario.name)

	if not similarity_results:
		return None

	return SimilarityReport(
		personas_file='',  # caller can set this
		output_dir=str(output_dir),
		timestamp=datetime.now().isoformat(timespec='seconds'),
		results=similarity_results,
	)


def write_similarity_reports(report: SimilarityReport, output_dir: Path) -> tuple[Path, Path]:
	"""Write persona_similarity_report.json and .md to output_dir. Returns (json_path, md_path)."""
	json_path = output_dir / 'persona_similarity_report.json'
	json_path.write_text(report.model_dump_json(indent=2), encoding='utf-8')

	md_path = output_dir / 'persona_similarity_report.md'
	md_path.write_text(build_markdown_report(json.loads(report.model_dump_json())), encoding='utf-8')
	return json_path, md_path
