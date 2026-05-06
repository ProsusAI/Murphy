"""Persona prompt optimizer — reads the similarity eval report and proposes rewrites.

Aggregates per-persona eval data, then calls the LLM to propose improved text for
DESCRIPTION_INSTRUCTION and EXECUTION_HINTS_INSTRUCTION in LABEL_SYSTEM.
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from browser_use.llm import ChatOpenAI, SystemMessage, UserMessage
from murphy.eval.models import SimilarityReport
from murphy.personas.pipeline_models import Persona
from murphy.personas.storage import load_personas, save_personas

logger = logging.getLogger(__name__)

PERSONA_LABELING_PATH = Path(__file__).resolve().parent / 'persona_labeling.py'


def apply_optimization(
	description: str,
	hints: str,
	path: Path = PERSONA_LABELING_PATH,
) -> None:
	"""Rewrite DESCRIPTION_INSTRUCTION and EXECUTION_HINTS_INSTRUCTION in persona_labeling.py."""
	source = path.read_text()
	source = re.sub(
		r'DESCRIPTION_INSTRUCTION\s*=\s*\(.*?\)',
		f'DESCRIPTION_INSTRUCTION = {repr(description)}',
		source,
		flags=re.DOTALL,
	)
	source = re.sub(
		r'EXECUTION_HINTS_INSTRUCTION\s*=\s*\(.*?\)',
		f'EXECUTION_HINTS_INSTRUCTION = {repr(hints)}',
		source,
		flags=re.DOTALL,
	)
	path.write_text(source)


async def relabel_personas(
	personas_path: Path,
	llm: ChatOpenAI,
	output_dir: Path,
) -> Path:
	"""Re-run labeling on the same centroids with the current LABEL_SYSTEM.

	Preserves persona names (keeping slugs stable for test plan compatibility),
	centroid scores, centroid_embedding, size, and assignments.
	Only description and execution_hints are updated.
	Returns the path to the new personas.json.
	"""
	from murphy.personas.persona_labeling import label_personas

	schema, old_result = load_personas(personas_path)

	dim_names = [d.name for d in schema.dimensions]
	k = len(old_result.personas)
	centroids = np.zeros((k, len(dim_names)))
	cluster_sizes: list[int] = []
	for p in sorted(old_result.personas, key=lambda x: x.persona_id):
		scores_dict = {d.trait_name: float(d.score) for d in p.centroid}
		for j, name in enumerate(dim_names):
			centroids[p.persona_id, j] = scores_dict.get(name, 3.0)
		cluster_sizes.append(p.size)

	labels = await label_personas(llm, schema, centroids, cluster_sizes)

	label_map = {desc.persona_id: desc for desc in labels.personas}
	new_personas = []
	for old_p in old_result.personas:
		desc = label_map.get(old_p.persona_id)
		if desc:
			new_p = old_p.model_copy(
				update={
					'description': desc.description,
					'execution_hints': desc.execution_hints,
				}
			)
		else:
			new_p = old_p
		new_personas.append(new_p)

	new_result = old_result.model_copy(update={'personas': new_personas})
	output_dir.mkdir(parents=True, exist_ok=True)
	return save_personas(schema, new_result, output_dir)


_OPTIMIZER_SYSTEM = """\
You are a prompt engineer improving instructions that guide an LLM to generate
persona definitions for a browser testing agent called Murphy.

Murphy reads two fields per persona during test execution:
1. `description` — a character sketch of who this user is
2. `execution_hints` — behavioral instructions that tell Murphy HOW to act

Your task: rewrite the two instructions in LABEL_SYSTEM that generate these fields,
so the generated descriptions and hints make Murphy's behavior measurably closer
to the real-user trait centroid as measured by eval scores.

Constraints:
- description instruction: keep to 1-2 lines
- execution_hints instruction: keep to 3-5 lines with one concrete example hint
- Do not rename fields or change format
- Be MORE specific than the current instructions, not less
- Ground every change in the gap evidence provided"""


@dataclass
class PersonaDiagnostics:
	persona_name: str
	avg_similarity: float
	worst_dimension: str
	worst_dim_delta: float
	biggest_gaps: list[str] = field(default_factory=list)
	scoring_reasonings: list[str] = field(default_factory=list)
	current_description: str = ''
	current_execution_hints: list[str] = field(default_factory=list)


@dataclass
class OptimizationResult:
	current_description_instruction: str
	current_execution_hints_instruction: str
	proposed_description_instruction: str
	proposed_execution_hints_instruction: str
	rationale: str
	diff: str
	underperforming_personas: list[PersonaDiagnostics] = field(default_factory=list)


class PromptProposal(BaseModel):
	proposed_description_instruction: str
	proposed_execution_hints_instruction: str
	rationale: str


def _build_user_prompt(
	diagnostics: list[PersonaDiagnostics],
	description_instruction: str,
	execution_hints_instruction: str,
	threshold: float,
) -> str:
	lines: list[str] = []
	lines.append(f'Current DESCRIPTION_INSTRUCTION:\n{description_instruction}\n')
	lines.append(f'Current EXECUTION_HINTS_INSTRUCTION:\n{execution_hints_instruction}\n')
	lines.append(f'The following {len(diagnostics)} persona(s) are underperforming (avg similarity < {threshold}):\n')
	for d in diagnostics:
		lines.append(f'--- {d.persona_name} (avg_similarity={d.avg_similarity:.2f}) ---')
		lines.append(f'Worst dimension: {d.worst_dimension} (delta={d.worst_dim_delta:+.2f})')
		lines.append(f'Current description: {d.current_description}')
		lines.append('Current execution_hints:')
		for hint in d.current_execution_hints:
			lines.append(f'  - {hint}')
		if d.biggest_gaps:
			lines.append('Biggest gaps:')
			for gap in d.biggest_gaps:
				lines.append(f'  • {gap}')
		if d.scoring_reasonings:
			reasoning = d.scoring_reasonings[0][:300]
			lines.append(f'Scoring reasoning (truncated): {reasoning}')
		lines.append('')
	return '\n'.join(lines)


async def optimize_persona_prompts(
	report_path: Path,
	personas_path: Path,
	llm: ChatOpenAI,
	similarity_threshold: float = 0.85,
) -> OptimizationResult:
	"""Analyze eval report and propose improved LABEL_SYSTEM instructions."""
	from murphy.personas.persona_labeling import DESCRIPTION_INSTRUCTION, EXECUTION_HINTS_INSTRUCTION

	report = SimilarityReport.model_validate_json(report_path.read_text())
	_, persona_result = load_personas(personas_path)

	persona_map: dict[str, Persona] = {p.name: p for p in persona_result.personas}

	grouped: dict[str, list] = {}
	for r in report.results:
		grouped.setdefault(r.persona_name, []).append(r)

	all_diags: list[PersonaDiagnostics] = []
	for persona_name, results in grouped.items():
		avg_sim = sum(r.overall_similarity_score for r in results) / len(results)

		dim_deltas: dict[str, list[float]] = {}
		for r in results:
			for dim in r.dimensions:
				dim_deltas.setdefault(dim.trait_name, []).append(dim.delta)

		worst_dim = ''
		worst_delta = 0.0
		for dim_name, deltas in dim_deltas.items():
			mean_abs = sum(abs(d) for d in deltas) / len(deltas)
			if mean_abs > abs(worst_delta):
				worst_dim = dim_name
				worst_delta = sum(deltas) / len(deltas)

		biggest_gaps = [r.rationale.biggest_gap for r in results if r.rationale and r.rationale.biggest_gap][:3]

		scoring_reasonings = [r.scoring_reasoning for r in results if r.scoring_reasoning][:3]

		persona = persona_map.get(persona_name)
		current_description = persona.description if persona else ''
		current_hints = persona.execution_hints if persona else []

		all_diags.append(
			PersonaDiagnostics(
				persona_name=persona_name,
				avg_similarity=avg_sim,
				worst_dimension=worst_dim,
				worst_dim_delta=worst_delta,
				biggest_gaps=biggest_gaps,
				scoring_reasonings=scoring_reasonings,
				current_description=current_description,
				current_execution_hints=current_hints,
			)
		)

	underperformers = [d for d in all_diags if d.avg_similarity < similarity_threshold]
	if not underperformers:
		underperformers = sorted(all_diags, key=lambda d: d.avg_similarity)[:3]
		logger.info('No personas below threshold; using bottom %d by similarity', len(underperformers))

	logger.info('Optimizing based on %d underperforming persona(s)', len(underperformers))

	user_prompt = _build_user_prompt(
		underperformers,
		DESCRIPTION_INSTRUCTION,
		EXECUTION_HINTS_INSTRUCTION,
		similarity_threshold,
	)

	messages = [
		SystemMessage(content=_OPTIMIZER_SYSTEM),
		UserMessage(content=user_prompt),
	]

	response = await llm.ainvoke(messages=messages, output_format=PromptProposal)
	proposal: PromptProposal = response.completion

	current_text = DESCRIPTION_INSTRUCTION + '\n\n' + EXECUTION_HINTS_INSTRUCTION
	proposed_text = proposal.proposed_description_instruction + '\n\n' + proposal.proposed_execution_hints_instruction

	diff = '\n'.join(
		difflib.unified_diff(
			current_text.splitlines(),
			proposed_text.splitlines(),
			fromfile='persona_labeling.py (current)',
			tofile='persona_labeling.py (proposed)',
			lineterm='',
		)
	)

	return OptimizationResult(
		current_description_instruction=DESCRIPTION_INSTRUCTION,
		current_execution_hints_instruction=EXECUTION_HINTS_INSTRUCTION,
		proposed_description_instruction=proposal.proposed_description_instruction,
		proposed_execution_hints_instruction=proposal.proposed_execution_hints_instruction,
		rationale=proposal.rationale,
		diff=diff,
		underperforming_personas=underperformers,
	)
