"""Propose rewrites to LABEL_SYSTEM instructions based on the persona similarity eval report.

Reads persona_similarity_report.json, identifies underperforming personas, and uses
an LLM to suggest improved text for DESCRIPTION_INSTRUCTION and EXECUTION_HINTS_INSTRUCTION.
Prints the rationale and a unified diff to stdout, then prompts y/n to apply the changes.

Usage:
    uv run python scripts/optimize_persona_prompts.py \\
        --report output/eval_with_embeddings/medium_goal/persona_similarity_report.json \\
        --personas-file output/similarity_run/personas.json
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


async def _async_main(args: argparse.Namespace) -> int:
	from browser_use.llm import ChatOpenAI
	from murphy.personas.optimizer import optimize_persona_prompts

	report_path = args.report.resolve()
	personas_path = args.personas_file.resolve()

	if not report_path.is_file():
		logger.error('Report not found: %s', report_path)
		return 2
	if not personas_path.is_file():
		logger.error('Personas file not found: %s', personas_path)
		return 2

	llm = ChatOpenAI(model=args.model)

	result = await optimize_persona_prompts(
		report_path=report_path,
		personas_path=personas_path,
		llm=llm,
		similarity_threshold=args.threshold,
	)

	print('\n=== Persona Prompt Optimization Proposal ===\n')
	print(f'Analyzed {len(result.underperforming_personas)} underperforming persona(s) (avg similarity < {args.threshold}):')
	for d in result.underperforming_personas:
		print(f'  • {d.persona_name}: {d.avg_similarity:.2f} (worst: {d.worst_dimension}, delta={d.worst_dim_delta:+.2f})')

	print('\nRationale:')
	for line in result.rationale.splitlines():
		print(f'  {line}')

	print('\n--- Proposed diff ---')
	if result.diff:
		print(result.diff)
	else:
		print('(no changes proposed)')

	if not result.diff:
		return 0

	print('\nApply these changes to persona_labeling.py? [y/N] ', end='', flush=True)
	answer = input().strip().lower()
	if answer == 'y':
		from murphy.personas.optimizer import PERSONA_LABELING_PATH, apply_optimization

		apply_optimization(result.proposed_description_instruction, result.proposed_execution_hints_instruction)
		print(f'Updated {PERSONA_LABELING_PATH}')
	else:
		print('No changes applied.')
	return 0


def main() -> int:
	parser = argparse.ArgumentParser(
		description='Propose rewrites to LABEL_SYSTEM based on persona similarity eval.',
		formatter_class=argparse.ArgumentDefaultsHelpFormatter,
	)
	parser.add_argument(
		'--report',
		type=Path,
		required=True,
		help='Path to persona_similarity_report.json',
	)
	parser.add_argument(
		'--personas-file',
		type=Path,
		required=True,
		help='Path to personas.json produced by the discovery pipeline',
	)
	parser.add_argument(
		'--model',
		default='gpt-4o',
		help='LLM model for optimization',
	)
	parser.add_argument(
		'--threshold',
		type=float,
		default=0.85,
		help='Similarity threshold; personas below this are treated as underperforming',
	)
	args = parser.parse_args()
	return asyncio.run(_async_main(args))


if __name__ == '__main__':
	sys.exit(main())
