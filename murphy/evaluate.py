# Copyright © 2026 MIH AI B.V.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Murphy evaluate — public API facade.

Single import point for Murphy's pipeline functions. All logic lives in
focused modules under murphy.core.*; this file re-exports them for convenience.

Usage:
	from murphy.evaluate import analyze_website, generate_tests, execute_tests
"""

from murphy.core.analysis import analyze_website
from murphy.core.execution import execute_tests, execute_tests_with_session
from murphy.core.generation import explore_and_generate_plan, generate_tests
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
	'write_reports_and_print',
]
