"""Evaluate how faithfully Murphy mimics the behavior of discovered user personas.

For each Murphy test that used a discovered persona, this script:
  1. Loads the agent_history trace from the output directory.
  2. Converts it to a behavioral timeline (same format as real PostHog sessions).
  3. Scores it with score_session() against the trait schema.
  4. Compares the scores to the persona centroid (real-user average for that cluster).
  5. Writes persona_fidelity_report.json and persona_fidelity_report.md.

Usage (single run):
    uv run python scripts/eval_persona_fidelity.py \\
        --output-dir murphy/output \\
        --personas-file output/personas.json

Usage (batch runs in run_1/, run_2/, ...):
    uv run python scripts/eval_persona_fidelity.py \\
        --output-dir murphy/output \\
        --personas-file output/personas.json
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
	from murphy.eval.runner import _fidelity_label, run_fidelity_eval, write_fidelity_reports
	from murphy.personas.storage import load_personas

	output_dir = args.output_dir.resolve()
	personas_path = args.personas_file.resolve()

	if not personas_path.is_file():
		logger.error('Personas file not found: %s', personas_path)
		return 2

	schema, persona_result = load_personas(personas_path)
	logger.info('Loaded %d personas from %s', len(persona_result.personas), personas_path)

	llm = ChatOpenAI(model=args.model)

	report = await run_fidelity_eval(output_dir, schema, persona_result, llm)

	if report is None:
		logger.warning('No discovered-persona tests found. Run Murphy with --personas to use discovered personas.')
		return 0

	report.personas_file = str(personas_path)
	json_path, md_path = write_fidelity_reports(report, output_dir)
	logger.info('Wrote %s', json_path)
	logger.info('Wrote %s', md_path)

	total = len(report.results)
	avg = sum(r.overall_fidelity_score for r in report.results) / total
	print(f'\nEvaluated {total} test(s).')
	print(f'Average fidelity: {avg:.2f} ({_fidelity_label(avg)})')
	print(f'Report: {md_path}')
	return 0


def main() -> int:
	parser = argparse.ArgumentParser(
		description='Evaluate how faithfully Murphy mimics discovered user personas.',
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
		default='gpt-5-mini',
		help='LLM model for behavioral scoring',
	)
	args = parser.parse_args()
	return asyncio.run(_async_main(args))


if __name__ == '__main__':
	sys.exit(main())
