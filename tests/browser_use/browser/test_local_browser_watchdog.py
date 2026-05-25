from browser_use.browser.watchdogs.local_browser_watchdog import cdp_ready_timeout


def test_cdp_ready_timeout_defaults_to_180(monkeypatch):
	monkeypatch.delenv('TIMEOUT_BrowserCDPReady', raising=False)

	assert cdp_ready_timeout() == 180.0


def test_cdp_ready_timeout_uses_env_override(monkeypatch):
	monkeypatch.setenv('TIMEOUT_BrowserCDPReady', '45.5')

	assert cdp_ready_timeout() == 45.5


def test_cdp_ready_timeout_ignores_invalid_env_override(monkeypatch):
	monkeypatch.setenv('TIMEOUT_BrowserCDPReady', 'not-a-number')

	assert cdp_ready_timeout() == 180.0
