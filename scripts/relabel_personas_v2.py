"""Re-run persona labeling with the current LABEL_SYSTEM and save as personas_v3.json.

Generates one LLM call per persona to avoid quality degradation from long batched outputs.
Regenerates ALL LLM fields: description, distinguishing_traits, test_orientation,
success_criteria_guidance, execution_hints, judge_questions.
Keeps algorithmic fields: persona_id, name, centroid, size, centroid_embedding.
"""

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

from browser_use.llm import ChatOpenAI, SystemMessage, UserMessage
from murphy.personas.persona_labeling import (
	LABEL_SYSTEM,
	_format_clusters,
	_format_schema_for_labeling,
)
from murphy.personas.pipeline_models import Persona, PersonaDescription
from murphy.personas.storage import load_personas


async def label_single_persona(
	llm: ChatOpenAI,
	schema,
	centroid_row: np.ndarray,
	cluster_size: int,
	persona_id: int,
	max_retries: int = 3,
) -> PersonaDescription:
	"""Label a single persona cluster with one dedicated LLM call."""
	schema_block = _format_schema_for_labeling(schema)
	cluster_block = _format_clusters(schema, centroid_row[np.newaxis, :], [cluster_size])
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

	last_exc: Exception | None = None
	for attempt in range(1, max_retries + 1):
		try:
			response = await llm.ainvoke(messages=messages, output_format=PersonaDescription)
			desc: PersonaDescription = response.completion
			desc = desc.model_copy(update={'persona_id': persona_id})
			return desc
		except Exception as exc:
			last_exc = exc
			print(f'  attempt {attempt}/{max_retries} failed: {exc}')

	raise last_exc  # type: ignore[misc]


async def main(personas_path: Path, output_path: Path, model: str = 'gpt-4o') -> None:
	schema, old_result = load_personas(personas_path)
	llm = ChatOpenAI(model=model)

	dim_names = [d.name for d in schema.dimensions]
	k = len(old_result.personas)
	centroids = np.zeros((k, len(dim_names)))
	cluster_sizes: list[int] = []
	for p in sorted(old_result.personas, key=lambda x: x.persona_id):
		scores_dict = {d.trait_name: float(d.score) for d in p.centroid}
		for j, name in enumerate(dim_names):
			centroids[p.persona_id, j] = scores_dict.get(name, 3.0)
		cluster_sizes.append(p.size)

	print(f'Re-labeling {k} personas one at a time (all LLM fields)...')
	new_personas: list[Persona] = []
	for old_p in sorted(old_result.personas, key=lambda x: x.persona_id):
		pid = old_p.persona_id
		desc = await label_single_persona(llm, schema, centroids[pid], cluster_sizes[pid], pid)
		# Replace LLM-invented name in description with the original persona name
		description = desc.description.replace(f'The {desc.name}', f'The {old_p.name}', 1)
		new_p = old_p.model_copy(
			update={
				'description': description,
				'distinguishing_traits': desc.distinguishing_traits,
				'test_orientation': desc.test_orientation,
				'success_criteria_guidance': desc.success_criteria_guidance,
				'execution_hints': desc.execution_hints,
				'judge_questions': desc.judge_questions,
			}
		)
		print(f'  [{old_p.name}] → {description[:80]}...')
		new_personas.append(new_p)

	new_result = old_result.model_copy(update={'personas': new_personas})
	payload = {'schema': schema.model_dump(), 'result': new_result.model_dump()}
	output_path.write_text(json.dumps(payload, indent=2))
	print(f'\nSaved to {output_path}')


if __name__ == '__main__':
	personas_path = Path('output/similarity_run/personas.json')
	output_path = Path('output/similarity_run/personas_v3.json')
	asyncio.run(main(personas_path, output_path))
