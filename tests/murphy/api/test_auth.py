"""Tests for auth helpers with mocked LLM and browser session."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from murphy.api.auth import _llm_classify_page, _wait_for_detected_login


def _make_mock_llm(answer: str) -> AsyncMock:
	"""Create a mock LLM that returns a string response."""
	llm = AsyncMock()
	response = MagicMock()
	response.completion = answer
	llm.ainvoke.return_value = response
	return llm


# ─── _llm_classify_page ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_classify_page_auth_detect_content():
	llm = _make_mock_llm('CONTENT')
	result = await _llm_classify_page(llm, 'https://example.com', 'Dashboard', 'Welcome to your dashboard', mode='auth_detect')
	assert result is True


@pytest.mark.asyncio
async def test_classify_page_auth_detect_login():
	llm = _make_mock_llm('LOGIN')
	result = await _llm_classify_page(llm, 'https://example.com/login', 'Sign In', 'Enter your credentials', mode='auth_detect')
	assert result is False


@pytest.mark.asyncio
async def test_classify_page_login_poll_authenticated():
	llm = _make_mock_llm('AUTHENTICATED')
	result = await _llm_classify_page(llm, 'https://example.com', 'App', 'Dashboard content', mode='login_poll')
	assert result is True


@pytest.mark.asyncio
async def test_classify_page_login_poll_still_login():
	llm = _make_mock_llm('LOGIN')
	result = await _llm_classify_page(llm, 'https://example.com/login', 'Sign In', 'Enter password', mode='login_poll')
	assert result is False


@pytest.mark.asyncio
async def test_classify_page_case_insensitive():
	"""LLM might return lowercase — should still work via .upper()."""
	llm = _make_mock_llm('content')
	result = await _llm_classify_page(llm, 'https://example.com', 'Home', 'Page body', mode='auth_detect')
	assert result is True


@pytest.mark.asyncio
async def test_classify_page_non_string_completion():
	"""If completion is not a string, should return False gracefully."""
	llm = AsyncMock()
	response = MagicMock()
	response.completion = None  # Not a string
	llm.ainvoke.return_value = response

	result = await _llm_classify_page(llm, 'https://example.com', 'Page', 'Body', mode='auth_detect')
	assert result is False


@pytest.mark.asyncio
async def test_classify_page_rejects_not_authenticated_text():
	llm = _make_mock_llm('NOT_AUTHENTICATED')

	result = await _llm_classify_page(llm, 'https://example.com', 'Home', 'Public content', mode='login_poll')

	assert result is False


@pytest.mark.asyncio
async def test_wait_for_detected_login_requires_two_consecutive_matches():
	llm = _make_mock_llm('LOGIN')
	llm.ainvoke.side_effect = [
		MagicMock(completion='LOGIN'),
		MagicMock(completion='AUTHENTICATED'),
		MagicMock(completion='AUTHENTICATED'),
	]

	with patch(
		'murphy.api.auth._get_page_text',
		new=AsyncMock(return_value=('https://example.com/account', 'Account', 'Signed in as user')),
	) as get_page_text:
		await _wait_for_detected_login(MagicMock(), llm, timeout_seconds=1, poll_seconds=0)

	assert get_page_text.await_count == 3
