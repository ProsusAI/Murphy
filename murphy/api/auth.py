"""Murphy — auth detection and manual login helpers."""

from __future__ import annotations

import asyncio
import logging
import os
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
			'Question: Does this page contain clear evidence that the user is signed in, such as '
			'an account name, profile controls, order history, or a logout action? Public content '
			'without account-specific evidence is not authenticated. A login form, SSO flow, 2FA '
			'prompt, or pre-login screen is also not authenticated.\n\n'
			'Reply with exactly one word: AUTHENTICATED or LOGIN'
		)

	response = await llm.ainvoke([UserMessage(content=prompt)])
	answer = response.completion.strip().upper() if isinstance(response.completion, str) else ''

	if mode == 'auth_detect':
		return answer == 'CONTENT'
	else:
		return answer == 'AUTHENTICATED'


async def _wait_for_detected_login(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	*,
	timeout_seconds: float,
	poll_seconds: float = 5,
) -> None:
	loop = asyncio.get_running_loop()
	deadline = loop.time() + timeout_seconds
	consecutive_authenticated = 0

	while loop.time() < deadline:
		current_url, title, body = await _get_page_text(browser_session)
		is_authenticated = await _llm_classify_page(llm, current_url, title, body, mode='login_poll')
		consecutive_authenticated = consecutive_authenticated + 1 if is_authenticated else 0
		if consecutive_authenticated >= 2:
			logger.info('Authenticated page detected. Continuing automatically.')
			return
		await asyncio.sleep(poll_seconds)

	raise TimeoutError(f'Authentication was not detected within {timeout_seconds:.0f} seconds.')


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
	if os.getenv('MURPHY_AUTO_AUTH', '').lower()[:1] in 'ty1':
		timeout_seconds = float(os.getenv('MURPHY_AUTH_TIMEOUT_SECONDS', '300'))
		print('>>> Murphy will continue automatically after it detects the signed-in state.\n')
		await _wait_for_detected_login(
			browser_session,
			llm,
			timeout_seconds=timeout_seconds,
		)
		return

	print(">>> When you're done, press Enter or type 'continue' to proceed.\n")

	# Block on user input — run in executor so asyncio loop isn't blocked
	loop = asyncio.get_event_loop()
	await loop.run_in_executor(None, lambda: input('  Press Enter to continue...  '))
