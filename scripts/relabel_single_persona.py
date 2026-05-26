"""Regenerate LLM fields for a single persona by id, in-place."""

import asyncio
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

load_dotenv()

import numpy as np
from murphy.personas.persona_labeling import (
	LABEL_SYSTEM,
	_format_clusters,
	_format_schema_for_labeling,
)
from murphy.personas.pipeline_models import PersonaDescription
from murphy.personas.storage import load_personas

from browser_use.llm import ChatOpenAI, SystemMessage, UserMessage


async def relabel_one(personas_path: Path, persona_id: int, model: str = 'gpt-4o') -> None:
	schema, result = load_personas(personas_path)
	llm = ChatOpenAI(model=model)

	persona = next((p for p in result.personas if p.persona_id == persona_id), None)
	if persona is None:
		print(f'No persona with id={persona_id}')
		return

	dim_names = [d.name for d in schema.dimensions]
	centroid_row = np.array([next((float(d.score) for d in persona.centroid if d.trait_name == name), 3.0) for name in dim_names])

	schema_block = _format_schema_for_labeling(schema)
	cluster_block = _format_clusters(schema, centroid_row[np.newaxis, :], [persona.size])
	cluster_block = cluster_block.replace('Cluster 0', f'Cluster {persona_id}')

	messages = [
		SystemMessage(content=LABEL_SYSTEM),
		UserMessage(
			content=(
				f'Name and describe the following 1 persona cluster.\n\n'
				f'=== Trait Dimensions ===\n{schema_block}\n\n'
				f'=== Clusters ===\n{cluster_block}'
			)
		),
	]

	response = await llm.ainvoke(messages=messages, output_format=PersonaDescription)
	desc: PersonaDescription = response.completion

	print(f'Old description: {persona.description}')
	print(f'New description: {desc.description}')

	updated = persona.model_copy(
		update={
			'description': desc.description,
			'distinguishing_traits': desc.distinguishing_traits,
			'test_orientation': desc.test_orientation,
			'success_criteria_guidance': desc.success_criteria_guidance,
			'execution_hints': desc.execution_hints,
			'judge_questions': desc.judge_questions,
		}
	)

	new_personas = [updated if p.persona_id == persona_id else p for p in result.personas]
	new_result = result.model_copy(update={'personas': new_personas})
	payload = {'schema': schema.model_dump(), 'result': new_result.model_dump()}
	personas_path.write_text(json.dumps(payload, indent=2))
	print(f'\nSaved to {personas_path}')


if __name__ == '__main__':
	personas_path = Path('output/restaurant_personas_2/personas.json')
	persona_id = int(sys.argv[1]) if len(sys.argv) > 1 else 7
	asyncio.run(relabel_one(personas_path, persona_id))
