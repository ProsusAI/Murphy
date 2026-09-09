from __future__ import annotations

from pathlib import Path

from murphy.personas.pipeline_models import (
	DimensionScore,
	Persona,
	SessionPersonaAssignment,
	TraitDimension,
)
from murphy.personas.storage import load_personas, save_personas


def newcomer_score(trait_name: str) -> float:
	name = trait_name.lower()
	if 'familiar' in name:
		return 1
	if 'efficiency' in name or 'decisive' in name or 'navigation' in name:
		return 1.5
	if 'goal' in name or 'focus' in name:
		return 2
	if 'friction' in name or 'tolerance' in name or 'persistence' in name:
		return 2
	if 'methodical' in name or 'decision' in name:
		return 2
	if 'diet' in name:
		return 1
	if 'safety' in name or 'allergen' in name:
		return 2
	return 2


def main() -> None:
	repo = Path(__file__).resolve().parents[1]
	workshop_root = repo.parent / 'murphy_workshop'
	base_path = workshop_root / 'output' / 'personas.json'
	output_dir = workshop_root / 'output'
	schema, result = load_personas(base_path)

	familiarity = TraitDimension(
		name='Interface Familiarity',
		description='How confidently a user understands ordering controls and navigation on a first visit.',
		why_chosen='Synthetic newcomer sessions show repeated input errors, help use, wrong-section visits, and backtracking.',
		low_description='Needs explicit labels and guidance, makes navigation errors, and hesitates after validation messages.',
		high_description='Recognizes controls immediately and completes familiar ordering paths without guidance.',
	)
	dimensions = [*schema.dimensions, familiarity]
	updated_personas = [
		persona.model_copy(
			update={
				'centroid': [
					*persona.centroid,
					DimensionScore(trait_name=familiarity.name, score=3),
				]
			}
		)
		for persona in result.personas
	]

	persona_id = max(persona.persona_id for persona in updated_personas) + 1
	newcomer = Persona(
		persona_id=persona_id,
		name='Confused Newcomer',
		description=(
			'A first-time visitor who does not yet understand the site navigation or common ordering controls. '
			'They depend on explicit labels, validation guidance, and a clear indication of the next safe action.'
		),
		centroid=[
			DimensionScore(trait_name=dimension.name, score=newcomer_score(dimension.name))
			for dimension in dimensions
		],
		distinguishing_traits=['Interface Familiarity', 'Decisive Navigation (Goal-Focused Browsing)', 'Efficiency and Decisiveness'],
		size=12,
		test_orientation='ux',
		success_criteria_guidance=(
			'The website provides visible, plain-language guidance at each checkout step and makes the next action unambiguous.'
		),
		execution_hints=[
			'Treat the site as unfamiliar and rely only on visible labels and guidance.',
			'If two controls appear plausible, try the more prominent one and report the ambiguity.',
			'Read validation messages, then attempt one recovery using only the action that the message suggests.',
			'Do not use shortcuts that a first-time visitor could not reasonably know.',
		],
		judge_questions=[
			'Can a first-time user identify the next checkout action without prior knowledge?',
			'Do validation messages explain both the problem and the recovery action?',
			'Does the order summary remain visible and understandable before payment?',
		],
		suggestion_instruction=(
			'As a first-time visitor, suggest 1-3 clarity improvements for navigation, validation, or checkout guidance.'
		),
	)
	assignments = [
		*result.assignments,
		*[
			SessionPersonaAssignment(
				session_id=f'synthetic-session-cn-{index:02d}',
				user_id=f'synthetic-user-cn-{index:02d}',
				persona_id=persona_id,
			)
			for index in range(1, 13)
		],
	]

	save_personas(
		schema.model_copy(
			update={
				'dimensions': dimensions,
				'rationale': f'{schema.rationale} Confused Newcomer was curated from 12 labeled synthetic newcomer sessions.',
			}
		),
		result.model_copy(
			update={
				'personas': [*updated_personas, newcomer],
				'num_clusters': len(updated_personas) + 1,
				'assignments': assignments,
			}
		),
		output_dir,
	)
	print(output_dir / 'personas.json')


if __name__ == '__main__':
	main()
