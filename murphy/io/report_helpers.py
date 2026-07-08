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

"""Report generation — shared helpers and utilities."""

from __future__ import annotations

from dataclasses import dataclass, field

from murphy.models import PERSONA_REGISTRY, TestResult


def _slugify(name: str) -> str:
	"""Convert a test name to a filesystem-safe slug."""
	return name.lower().replace(' ', '_').replace("'", '')[:50]


# ─── Action metrics ──────────────────────────────────────────────────────────


@dataclass
class ActionMetrics:
	clicks: int = 0
	navigations: int = 0
	text_inputs: int = 0
	scrolls: int = 0
	pages_visited: list[str] = field(default_factory=list)
	total_actions: int = 0

	@property
	def unique_pages(self) -> int:
		return len(set(self.pages_visited))


def _compute_metrics(result: TestResult) -> ActionMetrics:
	"""Count clicks, navigations, text inputs, scrolls, and pages visited."""
	m = ActionMetrics()
	for action in result.actions:
		if not isinstance(action, dict):
			continue
		m.total_actions += 1
		if 'click' in action:
			m.clicks += 1
		if 'navigate' in action:
			m.navigations += 1
			url = action['navigate'].get('url', '')
			if url:
				m.pages_visited.append(url)
		if 'input_text' in action:
			m.text_inputs += 1
		if 'scroll' in action:
			m.scrolls += 1
		if 'go_to_url' in action:
			m.navigations += 1
			url = action['go_to_url'].get('url', '')
			if url:
				m.pages_visited.append(url)
	return m


def format_path(result: TestResult) -> str:
	"""Extract a concise user-readable path from the actions list.

	e.g. "Homepage → click 'About us' → click 'Ecosystems' → Portfolio"
	"""
	steps: list[str] = []
	for action in result.actions:
		if not isinstance(action, dict):
			continue
		if 'navigate' in action or 'go_to_url' in action:
			nav = action.get('navigate') or action.get('go_to_url') or {}
			url = nav.get('url', '')
			label = url.rstrip('/').split('/')[-1] or 'Homepage'
			steps.append(f'navigate → {label}')
		elif 'click' in action:
			el = action.get('interacted_element')
			if el and isinstance(el, dict):
				name = el.get('ax_name') or ''
				name = name.replace('Link to', '').replace('page', '').replace('\n', ' ').strip()
				if name:
					steps.append(f'click "{name}"')
		elif 'input_text' in action:
			text = action['input_text'].get('text', '')
			preview = text[:20] + '...' if len(text) > 20 else text
			steps.append(f'type "{preview}"')
		elif 'scroll' in action:
			direction = action['scroll'].get('direction', 'down')
			steps.append(f'scroll {direction}')
	return ' → '.join(steps) if steps else 'No path recorded'


def _format_metrics_line(m: ActionMetrics) -> str:
	"""Single-line summary of action metrics."""
	parts = []
	if m.clicks:
		parts.append(f'{m.clicks} click{"s" if m.clicks != 1 else ""}')
	if m.navigations:
		parts.append(f'{m.navigations} navigation{"s" if m.navigations != 1 else ""}')
	if m.text_inputs:
		parts.append(f'{m.text_inputs} text input{"s" if m.text_inputs != 1 else ""}')
	if m.scrolls:
		parts.append(f'{m.scrolls} scroll{"s" if m.scrolls != 1 else ""}')
	if m.unique_pages:
		parts.append(f'{m.unique_pages} unique page{"s" if m.unique_pages != 1 else ""}')
	return ', '.join(parts) if parts else 'No actions recorded'


def _form_field_label(fill: dict) -> str:
	"""Build a human-readable label for a form field from available metadata."""
	if fill.get('field_name'):
		return fill['field_name']
	if fill.get('aria_label'):
		return fill['aria_label']
	if fill.get('placeholder'):
		return fill['placeholder']
	if fill.get('name_attr'):
		return fill['name_attr']
	tag = fill.get('tag', '')
	type_attr = fill.get('type_attr', '')
	if tag:
		if type_attr:
			return f'<{tag} type="{type_attr}">'
		return f'<{tag}>'
	if fill.get('role'):
		return fill['role']
	return f'element #{fill.get("index", "?")}'


def suggest_fix(result: TestResult) -> str:
	"""Generate an actionable suggestion based on the failure context and persona."""
	judgement = result.judgement
	failure_reason = (judgement.failure_reason if judgement else '').lower()
	failure_reason_raw = judgement.failure_reason if judgement else ''
	reasoning = (judgement.reasoning if judgement else '').lower()
	scenario = result.scenario
	persona = scenario.test_persona

	# Captcha blocked
	if judgement and judgement.reached_captcha:
		return (
			'The test was blocked by a CAPTCHA. This is expected for automated testing. '
			'Consider whitelisting the test environment or using a CAPTCHA-solving service.'
		)

	# Impossible task
	if judgement and judgement.impossible_task:
		return (
			'This test scenario may not be possible on the current version of the website. '
			'Review whether the feature being tested actually exists and is accessible.'
		)

	# Test-type-specific suggestions for security / boundary personas
	persona_entry = PERSONA_REGISTRY.get(persona)  # type: ignore[arg-type]
	test_type = persona_entry[1] if persona_entry else 'ux'
	if test_type in ('security', 'boundary'):
		silent_handling_signals = [
			'no error',
			'no explicit',
			'no visible',
			'no message',
			'accepted',
			'no validation',
			'did not show',
			'without showing',
			'no indication',
			'silently',
			'no feedback',
		]
		if any(signal in failure_reason or signal in reasoning for signal in silent_handling_signals):
			return (
				f'The site accepted the {persona.replace("_", " ")} input without crashing or exposing errors, '
				f'which may actually be correct behavior (silent sanitization). '
				f'Consider whether the success criteria should treat silent handling as a pass. '
				f'Specific observation: {failure_reason_raw}'
			)
		crash_signals = ['crash', 'exception', 'stack trace', 'debug', 'leaked', 'executed', 'injection']
		if any(signal in failure_reason or signal in reasoning for signal in crash_signals):
			return (
				f'The site did not handle {persona.replace("_", " ")} input safely. '
				f'Add input validation or sanitization for this input path. '
				f'Specific issue: {failure_reason_raw}'
			)

	# Agent got stuck / looping
	if persona in ('confused_novice', 'impatient_user'):
		if result.duration > 200 or (len(result.actions) > 25):
			return (
				f'The agent ran {len(result.actions)} actions over {result.duration:.0f}s, suggesting it got stuck '
				f'in a loop. This is likely a test limitation — the "{persona.replace("_", " ")}" scenario '
				f'may need clearer exit conditions or a lower step limit. '
				f'Specific observation: {failure_reason_raw}'
			)

	# Verification / evidence issues
	if 'verify' in failure_reason or 'evidence' in failure_reason or 'confirm' in failure_reason:
		return (
			f'The actions were performed but the test could not confirm the expected outcome. '
			f'The success criteria may be too strict for what the site actually shows. '
			f'Specific observation: {failure_reason_raw}'
		)

	# Navigation failures
	if 'navigate' in failure_reason or 'load' in failure_reason or 'url' in failure_reason:
		return (
			f'A page failed to load or navigated to an unexpected URL. '
			f"Check that the target pages exist, aren't behind authentication, "
			f"and don't redirect unexpectedly. "
			f'Specific observation: {failure_reason_raw}'
		)

	# Element not found
	if 'element' in failure_reason or 'click' in failure_reason or 'not found' in failure_reason:
		return (
			f'An interactive element could not be found or clicked. '
			f'The page layout may have changed, or the element may load dynamically. '
			f'Specific observation: {failure_reason_raw}'
		)

	# Timeout
	if 'timeout' in failure_reason or 'time' in reasoning:
		return (
			f'The test took too long to complete. This could indicate slow page loads, '
			f'heavy JavaScript, or the agent getting stuck in a loop. '
			f'Specific observation: {failure_reason_raw}'
		)

	# Fallback with actual failure reason included
	if failure_reason_raw:
		return f'The test failed during the "{persona.replace("_", " ")}" scenario. Specific observation: {failure_reason_raw}'

	return ''
