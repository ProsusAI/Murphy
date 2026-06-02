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


async def auto_login(
	browser_session: BrowserSession,
	llm: BaseChatModel,
	url: str,
	username: str,
	password: str,
	*,
	already_navigated: bool = False,
	max_steps: int = 15,
) -> None:
	"""Automatically log in using the provided credentials via the browser agent."""
	from browser_use import Agent

	logger.info('\n%s', '=' * 60)
	logger.info('Auto-login with provided credentials')
	logger.info('%s\n', '=' * 60)

	if not already_navigated:
		await browser_session.navigate_to(url)
		await asyncio.sleep(2)

	task = (
		f'You are on a login page. Log in with these credentials:\n'
		f'- Username/Email: {username}\n'
		f'- Password: {password}\n\n'
		f'Steps:\n'
		f'1. Find the login/sign-in form\n'
		f'2. Fill in the username/email field\n'
		f'3. Fill in the password field — you MUST type the exact password shown above, character for character\n'
		f'4. Click the login/sign-in/submit button\n'
		f'5. Wait for the page to load after submission\n'
		f'6. If there are any SSO redirects or intermediate pages, follow them\n'
	)

	# Add a logging filter to mask the password in all log output
	class _PasswordFilter(logging.Filter):
		def filter(self, record: logging.LogRecord) -> bool:
			if isinstance(record.msg, str):
				record.msg = record.msg.replace(password, '********')
			return True

	password_filter = _PasswordFilter()
	logging.getLogger().addFilter(password_filter)

	agent = Agent(
		task=task,
		llm=llm,
		browser_session=browser_session,
		max_actions_per_step=3,
	)
	await agent.run(max_steps=max_steps)

	# Verify login succeeded
	await asyncio.sleep(2)
	current_url, title, body = await _get_page_text(browser_session)
	is_authenticated = await _llm_classify_page(llm, current_url, title, body, mode='login_poll')

	# Remove the password filter
	logging.getLogger().removeFilter(password_filter)

	if is_authenticated:
		logger.info('Auto-login successful.')
	else:
		logger.warning('Auto-login may have failed — page does not appear authenticated. Continuing anyway.')


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
