"""Tests for custom browser action helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from murphy.browser.actions import MAX_LITE_EVIDENCE_CAPTURES, _domain_from_url, register_lite_evidence_action

# ─── _domain_from_url ────────────────────────────────────────────────────────


def test_domain_from_url_standard():
	assert _domain_from_url('https://example.com/page') == 'example.com'


def test_domain_from_url_with_port():
	assert _domain_from_url('http://localhost:3000/api') == 'localhost'


def test_domain_from_url_subdomain():
	assert _domain_from_url('https://sub.domain.example.com/path') == 'sub.domain.example.com'


def test_domain_from_url_no_scheme():
	"""If no scheme, urlparse can't extract hostname — returns the input."""
	result = _domain_from_url('example.com')
	assert result == 'example.com'


def test_domain_from_url_ip():
	assert _domain_from_url('http://192.168.1.1:8080/test') == '192.168.1.1'


@pytest.mark.asyncio
async def test_lite_evidence_action_captures_current_viewport(tmp_path):
	registered_actions = {}
	tools = MagicMock()

	def register(*, description):
		assert 'current visible browser viewport' in description

		def decorator(func):
			registered_actions[func.__name__] = func
			return func

		return decorator

	tools.action.side_effect = register
	session = MagicMock()
	session.take_screenshot = AsyncMock()
	captured_paths: dict[str, str] = {}

	register_lite_evidence_action(tools, session, tmp_path, captured_paths)
	result = await registered_actions['capture_flaw_evidence']('Basket obscures the primary action.')

	assert 'evidence_01' in result.extracted_content
	assert captured_paths['evidence_01'].endswith('evidence_01.png')
	session.take_screenshot.assert_awaited_once_with(path=captured_paths['evidence_01'])


@pytest.mark.asyncio
async def test_lite_evidence_action_limits_capture_count(tmp_path):
	registered_actions = {}
	tools = MagicMock()

	def register(*, description):
		def decorator(func):
			registered_actions[func.__name__] = func
			return func

		return decorator

	tools.action.side_effect = register
	session = MagicMock()
	session.take_screenshot = AsyncMock()
	captured_paths = {
		f'evidence_{index:02d}': str(tmp_path / f'evidence_{index:02d}.png')
		for index in range(1, MAX_LITE_EVIDENCE_CAPTURES + 1)
	}

	register_lite_evidence_action(tools, session, tmp_path, captured_paths)
	result = await registered_actions['capture_flaw_evidence']('Duplicate blocked page.')

	assert 'limit reached' in result.extracted_content
	assert len(captured_paths) == MAX_LITE_EVIDENCE_CAPTURES
	session.take_screenshot.assert_not_awaited()
