"""Murphy evaluate — public API facade.

Single import point for Murphy's pipeline functions. All logic lives in
focused modules under murphy.core.*; this file re-exports them for convenience.

Usage:
	from murphy.evaluate import analyze_website, generate_tests, execute_tests
"""

from murphy.core.analysis import analyze_website
from murphy.core.execution import execute_tests, execute_tests_with_session
from murphy.core.generation import explore_and_generate_plan, generate_tests, make_lite_plan
from murphy.core.summary import build_summary, classify_failure, generate_executive_summary, write_reports_and_print

__all__ = [
	'analyze_website',
	'build_summary',
	'classify_failure',
	'execute_tests',
	'execute_tests_with_session',
	'explore_and_generate_plan',
	'generate_executive_summary',
	'generate_tests',
	'make_lite_plan',
	'write_reports_and_print',
]
