from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from murphy.browser.session_utils import enforce_single_tab


@pytest.mark.asyncio
async def test_enforce_single_tab_preserves_and_focuses_current_target():
	first = SimpleNamespace(target_id='first')
	second = SimpleNamespace(target_id='second')
	session = MagicMock()
	session.get_page_targets.return_value = [first, second]
	session.get_focused_target.return_value = first
	session.close_page = AsyncMock()
	session.get_or_create_cdp_session = AsyncMock()

	await enforce_single_tab(session, 'https://example.com')

	session.close_page.assert_awaited_once_with('second')
	session.get_or_create_cdp_session.assert_awaited_once_with(target_id='first', focus=True)


@pytest.mark.asyncio
async def test_enforce_single_tab_focuses_last_target_when_focus_is_missing():
	first = SimpleNamespace(target_id='first')
	second = SimpleNamespace(target_id='second')
	session = MagicMock()
	session.get_page_targets.return_value = [first, second]
	session.get_focused_target.return_value = None
	session.close_page = AsyncMock()
	session.get_or_create_cdp_session = AsyncMock()

	await enforce_single_tab(session, 'https://example.com')

	assert session.close_page.await_args_list == [call('first')]
	session.get_or_create_cdp_session.assert_awaited_once_with(target_id='second', focus=True)


@pytest.mark.asyncio
async def test_enforce_single_tab_creates_page_when_none_exist():
	session = MagicMock()
	session.get_page_targets.return_value = []
	session.navigate_to = AsyncMock()

	await enforce_single_tab(session, 'https://example.com')

	session.navigate_to.assert_awaited_once_with('https://example.com', new_tab=True)
