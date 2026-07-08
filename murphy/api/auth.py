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

"""Murphy — auth detection and manual login helpers."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession
	from browser_use.llm import BaseChatModel

logger = logging.getLogger(__name__)


async def detect_auth_required(browser_session: BrowserSession, llm: BaseChatModel, url: str) -> bool:
	"""Navigate to URL and use a passive LLM call to detect if login is required."""
	logger.info('\n%s', '=' * 60)
	logger.info('Checking if %s requires login...', url)
	logger.info('%s\n', '=' * 60)

	await browser_session.navigate_to(url)
	await asyncio.sleep(2)  # let the page settle

	current_url, title, body = await _get_page_text(browser_session)
	is_content = await _llm_classify_page(llm, current_url, title, body, mode='auth_detect')
	auth_required = not is_content

	if auth_required:
		logger.info('Login gate detected — authentication required.')
	else:
		logger.info('Public/usable content detected — no login needed.')

	return auth_required


async def _get_page_text(browser_session: BrowserSession) -> tuple[str, str, str]:
	"""Read page title, URL, and truncated body text via CDP — completely passive, no side effects."""
	try:
		current_url = await browser_session.get_current_page_url()
	except Exception:
		current_url = ''

	cdp_session = await browser_session.get_or_create_cdp_session()
	try:
		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': 'document.title + "\\n" + document.body.innerText.substring(0, 2000)',
				'returnByValue': True,
			},
			session_id=cdp_session.session_id,
		)
		text = result.get('result', {}).get('value', '') if result else ''
	except Exception:
		text = ''

	title = text.split('\n', 1)[0] if text else ''
	body = text.split('\n', 1)[1] if '\n' in text else ''
	return current_url, title, body


async def _llm_classify_page(llm: BaseChatModel, url: str, title: str, body: str, *, mode: str = 'auth_detect') -> bool:
	"""Use a single LLM call (no agent) to classify page content.

	Returns True if the page looks like authenticated/usable content.
	Returns False if it looks like a login gate.
	"""
	from browser_use.llm.messages import UserMessage

	prompt = (
		f'You are classifying a web page. Current URL: {url}\nPage title: {title}\n\nPage text (first 2000 chars):\n{body}\n\n'
	)

	if mode == 'auth_detect':
		prompt += (
			'Question: Is this a login/sign-in page, welcome gate, or SSO redirect that blocks '
			'access to the main content? Or is this usable content (dashboard, app, articles, '
			'marketing site, product page, documentation)?\n\n'
			'Reply with exactly one word: LOGIN or CONTENT'
		)
	else:  # mode == "login_poll"
		prompt += (
			'Question: Has the user successfully logged in? Is this authenticated content '
			'(dashboard, app UI, user profile, main application) or is it still a login form, '
			'sign-in page, SSO flow, 2FA prompt, or pre-login screen?\n\n'
			'Reply with exactly one word: AUTHENTICATED or LOGIN'
		)

	response = await llm.ainvoke([UserMessage(content=prompt)])
	answer = response.completion.strip().upper() if isinstance(response.completion, str) else ''

	if mode == 'auth_detect':
		return 'CONTENT' in answer
	else:
		return 'AUTHENTICATED' in answer


async def wait_for_manual_login(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	url: str,
	*,
	already_navigated: bool = False,
) -> None:
	"""Wait for the user to log in manually, then wait for explicit confirmation to proceed."""
	logger.info('\n%s', '=' * 60)
	logger.info('Manual login')
	logger.info('%s\n', '=' * 60)

	if not already_navigated:
		await browser_session.navigate_to(url)

	print('>>> Log in manually in the browser window.')
	print(">>> When you're done, press Enter or type 'continue' to proceed.\n")

	# Block on user input — run in executor so asyncio loop isn't blocked
	loop = asyncio.get_event_loop()
	await loop.run_in_executor(None, lambda: input('  Press Enter to continue...  '))
