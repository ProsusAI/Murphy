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

"""Murphy — website analysis (Phase 1 of evaluation)."""

import logging

from browser_use import Agent
from browser_use.browser.session import BrowserSession
from browser_use.llm import BaseChatModel
from murphy.models import WebsiteAnalysis
from murphy.prompts import build_analysis_prompt

logger = logging.getLogger(__name__)


async def analyze_website(
	url: str,
	llm: BaseChatModel,
	category: str | None = None,
	goal: str | None = None,
	browser_session: BrowserSession | None = None,
) -> WebsiteAnalysis:
	"""Analyze a website to discover features and pages.

	When browser_session is None, creates a temporary agent (unauthenticated).
	When provided, reuses the session (authenticated).
	"""
	logger.info('\n%s', '=' * 60)
	logger.info('Analyzing %s', url)
	logger.info('%s\n', '=' * 60)

	is_authenticated = browser_session is not None
	task_prompt = build_analysis_prompt(url, category, goal, is_authenticated)

	agent_kwargs: dict = {
		'task': task_prompt,
		'llm': llm,
		'output_model_schema': WebsiteAnalysis,
		'max_actions_per_step': 3,
	}
	if browser_session is not None:
		agent_kwargs['browser_session'] = browser_session

	agent = Agent(**agent_kwargs)
	history = await agent.run(max_steps=30)

	result = history.final_result()
	if not result:
		raise RuntimeError(
			'Analysis agent returned no result — the browser agent could not extract structured data from the page.'
		)

	analysis = WebsiteAnalysis.model_validate_json(result)
	logger.info('\nAnalysis complete: %s (%s)', analysis.site_name, analysis.category)
	logger.info('  Pages found: %d', len(analysis.key_pages))
	logger.info('  Features found: %d', len(analysis.features))
	logger.info('  User flows: %d', len(analysis.identified_user_flows))
	return analysis
