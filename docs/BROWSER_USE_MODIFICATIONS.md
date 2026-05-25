# Vendored: browser-use

- **Upstream**: https://github.com/browser-use/browser-use
- **Based on**: upstream snapshot from ~November 2024 (vendored in commit 68201df6)
- **License**: MIT (see LICENSE in this directory)

## Local Modifications

1. **DOM watchdog toast capture** (`browser_use/browser/watchdogs/dom_watchdog.py`) — JavaScript observer that captures toast/snackbar notifications and surfaces them in browser state for test assertions.

2. **Toast messages in browser state** (`browser_use/browser/views.py`) — Added `toast_messages` field to `BrowserStateSummary`.

3. **Disabled-element safety checks** (`browser_use/browser/watchdogs/default_action_watchdog.py`) — Live CDP query (`_is_element_disabled_live()`) to prevent clicking disabled elements during multi-action sequences.

4. **Agent loop force-done** (`browser_use/agent/service.py`) — `_force_done_on_severe_loop()` method that terminates the agent when repetition >= 15 or stagnation >= 8.

5. **Escalated repetition warnings** (`browser_use/agent/views.py`) — More aggressive warning messages for detected loops.

6. **Scaled page-emptiness warnings** (`browser_use/agent/prompts.py`) — Warnings scale back after step 3 to reduce noise.

7. **CDP connection health check** (`browser_use/browser/session.py`) — Added `is_cdp_connected` property to expose CDP WebSocket state.

8. **Default headless mode** (`browser_use/browser/profile.py`) — Changed default `headless` from `None` to `True`.

9. **Custom Murphy tests** (`tests/browser_use/test_ai_step.py`, `tests/browser_use/test_rerun_ai_summary.py`) — Tests for `_execute_ai_step()` and `_generate_rerun_summary()` agent methods added for Murphy. These use mocked LLMs and mocked browser state (no real browser launch).

10. **Linting fixes** (`browser_use/agent/prompts.py`, `browser_use/agent/service.py`, `browser_use/code_use/service.py`) — Assigned unused expression results to underscore-prefixed variables to satisfy pyright `reportUnusedExpression`. Also excluded `browser_use/mcp/` and `browser_use/skill_cli/` from pyright checking (optional dependencies not installed).

11. **LLM retry loop for transient errors** (`browser_use/agent/service.py`, `browser_use/agent/views.py`) — `get_model_output()` now retries up to `llm_retry_max_attempts` (default 3) with linear backoff on `ModelRateLimitError` / `ModelProviderError` before attempting a fallback LLM switch. New `llm_retry_max_attempts` setting added to `AgentSettings`.

12. **Increased max completion tokens** (`browser_use/llm/openai/chat.py`) — Doubled `max_completion_tokens` from 4096 to 8192 to reduce truncated structured outputs.

13. **Broader empty-response detection** (`browser_use/llm/openai/chat.py`) — Changed empty-content check from `is None` to falsy (`not content`) to also catch empty strings; updated error message and status code to 502 (provider-side issue).

14. **Configurable local CDP readiness timeout** (`browser_use/browser/watchdogs/local_browser_watchdog.py`) — Added `TIMEOUT_BrowserCDPReady` with a 180-second default so slower containerized Chromium startups can wait longer for `/json/version` without modifying the event-level browser start timeouts.

## Syncing with Upstream

```bash
bin/vendor-diff.sh              # diff local browser_use against upstream HEAD
bin/vendor-diff.sh v0.X.Y       # diff against a specific upstream tag
```
