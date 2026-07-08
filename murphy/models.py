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

"""Pydantic models for the Murphy evaluation pipeline."""

from enum import IntEnum
from typing import Annotated, Any, ClassVar, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

# ─── Shared types ─────────────────────────────────────────────────────────────

FeatureCategory = Literal[
	'navigation',
	'search',
	'forms',
	'content_display',
	'filtering_sorting',
	'media',
	'authentication',
	'ecommerce',
	'social',
	'other',
]

ScenarioPriority = Literal['critical', 'high', 'medium', 'low']

TestPersona = Literal[
	'happy_path',  # standard user, expected flow
	'confused_novice',  # clicks wrong things, gets lost, misuses features
	'adversarial',  # tries to break things: XSS, injection, invalid inputs
	'edge_case',  # empty forms, special chars, long inputs, double-clicks
	'explorer',  # goes off the beaten path, tries unexpected combinations
	'impatient_user',  # clicks rapidly, doesn't wait for loads, skips steps
	'angry_user',  # rage-clicks, force-navigates, rapid form submissions, abandons flows mid-way
	'classic_ui',  # readability, font size, clear labels, familiar patterns, high contrast
	'modern_ui',  # current aesthetics, dark mode, visual appeal, engagement, micro-interactions
	'layout_auditor_ui',  # spacing consistency, breathing room, alignment, padding regularity, grid adherence
]


# ─── Trait system ─────────────────────────────────────────────────────────────
#
# Each test persona maps to a TraitVector and a TestType. The trait vector
# captures eight behavioral dimensions at low/medium/high levels. During
# judging, each trait level selects a different evaluation question — e.g.
# a low-patience persona is judged on whether the site provided *immediate*
# feedback, while a high-patience persona only needs eventual correctness.
#
# Core dims: technical_literacy, patience, intent, exploration, reading_comprehension
# UI dims:   visual_density_preference, aesthetic_era, layout_strictness
#
# TestType controls pass/fail semantics in the judge:
#   ux       — silent handling with no visible feedback is a FAIL
#   security — silent sanitization is CORRECT; only crashes/leaks fail
#   boundary — graceful degradation is a PASS; only unhandled exceptions fail
#   design   — evaluates visual design quality; functional correctness not in scope
#
# TRAIT_JUDGE_QUESTIONS (below TraitVector) maps trait levels to evaluation
# questions.  TEST_TYPE_RULES lives in core/judge.py.


class TraitLevel(IntEnum):
	low = 1
	medium = 2
	high = 3


class TraitVector(BaseModel):
	"""Behavioral profile for a test persona.

	Each dimension is evaluated independently by the judge LLM, with the
	trait level selecting a difficulty-appropriate evaluation question.
	"""

	model_config = ConfigDict(extra='forbid', frozen=True)
	technical_literacy: TraitLevel = TraitLevel.medium
	patience: TraitLevel = TraitLevel.medium
	intent: Literal['benign', 'exploratory', 'adversarial'] = 'benign'
	exploration: TraitLevel = TraitLevel.medium
	reading_comprehension: TraitLevel = TraitLevel.medium
	visual_density_preference: TraitLevel = TraitLevel.medium
	aesthetic_era: Literal['classic', 'modern', 'experimental'] = 'modern'
	layout_strictness: TraitLevel = TraitLevel.medium

	# ── Trait classification (single source of truth) ─────────────────────
	# When adding a new TraitLevel trait:
	#   1. Add the field above.
	#   2. Add its name to the appropriate tuple below.
	#   3. Add its judge questions to TRAIT_JUDGE_QUESTIONS (below the class).
	#   4. Add its short name to _SUMMARY_NAMES.
	# All consumers (judge, prompts, quality) derive from these.
	CORE_LEVEL_TRAITS: ClassVar[tuple[str, ...]] = (
		'technical_literacy',
		'patience',
		'reading_comprehension',
		'exploration',
	)
	DESIGN_LEVEL_TRAITS: ClassVar[tuple[str, ...]] = (
		'visual_density_preference',
		'layout_strictness',
	)
	_SUMMARY_NAMES: ClassVar[dict[str, str]] = {
		'technical_literacy': 'tech_lit',
		'patience': 'patience',
		'reading_comprehension': 'reading',
		'exploration': 'exploration',
		'visual_density_preference': 'density',
		'layout_strictness': 'strictness',
	}

	@classmethod
	def level_trait_names(cls, test_type: str) -> tuple[str, ...]:
		"""Return TraitLevel field names relevant to the given test type."""
		if test_type == 'design':
			return cls.CORE_LEVEL_TRAITS + cls.DESIGN_LEVEL_TRAITS
		return cls.CORE_LEVEL_TRAITS

	def level_trait_items(self, test_type: str) -> list[tuple[str, 'TraitLevel']]:
		"""Return (name, level) pairs for TraitLevel traits relevant to *test_type*."""
		return [(n, getattr(self, n)) for n in self.level_trait_names(test_type)]

	def render_summary(self, test_type: str) -> str:
		"""Compact one-line trait summary for prompt distribution text."""
		parts: list[str] = []
		for name in self.CORE_LEVEL_TRAITS:
			parts.append(f'{self._SUMMARY_NAMES[name]}={getattr(self, name).name}')
		parts.append(f'intent={self.intent}')
		if test_type == 'design':
			for name in self.DESIGN_LEVEL_TRAITS:
				parts.append(f'{self._SUMMARY_NAMES[name]}={getattr(self, name).name}')
			parts.append(f'era={self.aesthetic_era}')
		return ', '.join(parts)

	def render_full(self) -> str:
		"""Multi-line trait vector for execution prompts."""
		lines: list[str] = []
		for name in self.CORE_LEVEL_TRAITS:
			lines.append(f'  {name}: {getattr(self, name).name}')
		lines.append(f'  intent: {self.intent}')
		for name in self.DESIGN_LEVEL_TRAITS:
			lines.append(f'  {name}: {getattr(self, name).name}')
		lines.append(f'  aesthetic_era: {self.aesthetic_era}')
		return '\n'.join(lines)


# ── Per-trait evaluation questions (used by the judge) ────────────────────────
# Each TraitLevel trait must have an entry with low/medium/high questions.

TRAIT_JUDGE_QUESTIONS: dict[str, dict[TraitLevel, str]] = {
	'technical_literacy': {
		TraitLevel.low: 'Would a user unfamiliar with UI conventions understand what happened? Labels, icons, affordances must be self-explanatory without domain knowledge. This user needs explicit text, not just icons or color cues.',
		TraitLevel.medium: 'Were standard UI patterns followed? Would a typical web user understand the interaction?',
		TraitLevel.high: 'Were expert-level controls available and efficient?',
	},
	'patience': {
		TraitLevel.low: 'Did the site communicate state IMMEDIATELY? Loading indicators, progress bars, "please wait" messages? This user interprets 2+ seconds of silence as broken. Silent deduplication with no feedback = FAIL.',
		TraitLevel.medium: 'Did the site provide timely feedback within reasonable expectations?',
		TraitLevel.high: 'Did the site complete the task correctly, regardless of timing?',
	},
	'reading_comprehension': {
		TraitLevel.low: 'Was critical information conveyed through visual hierarchy: bold labels, color coding, icons, position-based cues? Error messages in body text are invisible to this user.',
		TraitLevel.medium: 'Were important messages prominent and scannable?',
		TraitLevel.high: 'Was detailed information available for thorough readers?',
	},
	'exploration': {
		TraitLevel.high: 'Did the site provide ORIENTATION at every step? Breadcrumbs, page titles, "no results" messages? Dead ends with no feedback = FAIL.',
		TraitLevel.medium: 'Did the site handle minor path deviations gracefully?',
		TraitLevel.low: 'Did the expected path work without requiring exploration?',
	},
	'visual_density_preference': {
		TraitLevel.low: 'Is the layout spacious and uncluttered? This user needs generous whitespace, large tap targets, and no more than one primary action per screen region. Dense dashboards or multi-column data grids feel overwhelming.',
		TraitLevel.medium: 'Is content density balanced? A reasonable amount of information per viewport with clear grouping and breathing room between sections.',
		TraitLevel.high: 'Is the layout information-dense and efficient? This user wants maximum data per screen — compact rows, minimal padding, and no wasted space. Sparse layouts feel empty.',
	},
	'layout_strictness': {
		TraitLevel.low: 'Is the overall layout coherent and usable? Minor spacing inconsistencies are acceptable as long as the layout does not feel broken.',
		TraitLevel.medium: 'Is spacing generally consistent? Obvious misalignments or irregular padding between clearly related components should be flagged.',
		TraitLevel.high: 'Does every margin, padding, and gutter follow a consistent scale? Flag any misaligned elements, irregular gaps between sibling components, or inconsistent padding inside cards — even subtle deviations.',
	},
}

assert set(TRAIT_JUDGE_QUESTIONS) == set(TraitVector.CORE_LEVEL_TRAITS + TraitVector.DESIGN_LEVEL_TRAITS), (
	f'TRAIT_JUDGE_QUESTIONS keys {set(TRAIT_JUDGE_QUESTIONS)} drift from '
	f'TraitVector level traits {set(TraitVector.CORE_LEVEL_TRAITS + TraitVector.DESIGN_LEVEL_TRAITS)}'
)

TestType = Literal['ux', 'security', 'boundary', 'design']

PERSONA_REGISTRY: dict[TestPersona, tuple[TraitVector, TestType]] = {
	'happy_path': (
		TraitVector(
			technical_literacy=TraitLevel.high,
			patience=TraitLevel.high,
			intent='benign',
			exploration=TraitLevel.low,
			reading_comprehension=TraitLevel.high,
		),
		'ux',
	),
	'confused_novice': (
		TraitVector(
			technical_literacy=TraitLevel.low,
			patience=TraitLevel.medium,
			intent='benign',
			exploration=TraitLevel.medium,
			reading_comprehension=TraitLevel.low,
		),
		'ux',
	),
	'adversarial': (
		TraitVector(
			technical_literacy=TraitLevel.high,
			patience=TraitLevel.high,
			intent='adversarial',
			exploration=TraitLevel.medium,
			reading_comprehension=TraitLevel.high,
		),
		'security',
	),
	'edge_case': (
		TraitVector(
			technical_literacy=TraitLevel.high,
			patience=TraitLevel.medium,
			intent='exploratory',
			exploration=TraitLevel.low,
			reading_comprehension=TraitLevel.medium,
		),
		'boundary',
	),
	'explorer': (
		TraitVector(
			technical_literacy=TraitLevel.medium,
			patience=TraitLevel.medium,
			intent='exploratory',
			exploration=TraitLevel.high,
			reading_comprehension=TraitLevel.medium,
		),
		'ux',
	),
	'impatient_user': (
		TraitVector(
			technical_literacy=TraitLevel.medium,
			patience=TraitLevel.low,
			intent='benign',
			exploration=TraitLevel.low,
			reading_comprehension=TraitLevel.low,
		),
		'ux',
	),
	'angry_user': (
		TraitVector(
			technical_literacy=TraitLevel.medium,
			patience=TraitLevel.low,
			intent='benign',
			exploration=TraitLevel.low,
			reading_comprehension=TraitLevel.low,
		),
		'security',
	),
	'classic_ui': (
		TraitVector(
			technical_literacy=TraitLevel.medium,
			patience=TraitLevel.high,
			intent='benign',
			exploration=TraitLevel.low,
			reading_comprehension=TraitLevel.medium,
			visual_density_preference=TraitLevel.low,
			aesthetic_era='classic',
			layout_strictness=TraitLevel.medium,
		),
		'design',
	),
	'modern_ui': (
		TraitVector(
			technical_literacy=TraitLevel.high,
			patience=TraitLevel.low,
			intent='benign',
			exploration=TraitLevel.high,
			reading_comprehension=TraitLevel.medium,
			visual_density_preference=TraitLevel.medium,
			aesthetic_era='experimental',
			layout_strictness=TraitLevel.low,
		),
		'design',
	),
	'layout_auditor_ui': (
		TraitVector(
			technical_literacy=TraitLevel.high,
			patience=TraitLevel.high,
			intent='benign',
			exploration=TraitLevel.high,
			reading_comprehension=TraitLevel.high,
			visual_density_preference=TraitLevel.low,
			aesthetic_era='modern',
			layout_strictness=TraitLevel.high,
		),
		'design',
	),
}


class FeedbackQualityScore(BaseModel):
	model_config = ConfigDict(extra='forbid')
	response_present: bool
	response_timely: bool
	response_clear: bool
	response_actionable: bool
	feedback_type: Literal[
		'none',
		'silent_handling',
		'visual_state_change',
		'inline_message',
		'toast_notification',
		'modal_dialog',
		'page_redirect',
		'error_page',
	]


# ─── Phase 1: Analysis ─────────────────────────────────────────────────────────


class InteractiveElement(BaseModel):
	element_type: Literal[
		'link',
		'button',
		'text_input',
		'search_box',
		'dropdown',
		'checkbox',
		'radio',
		'form',
		'tab',
		'accordion',
		'modal_trigger',
		'video_player',
		'carousel',
		'other',
	]
	label: str
	destination: str | None = None
	requires_auth: bool = False
	notes: str | None = None


class PageInfo(BaseModel):
	url: str
	title: str
	purpose: str
	page_type: Literal[
		'homepage', 'landing', 'product', 'listing', 'detail', 'form', 'content', 'dashboard', 'auth', 'error', 'other'
	]
	interactive_elements: list[InteractiveElement]


class Feature(BaseModel):
	name: str
	category: FeatureCategory
	description: str
	page_url: str
	elements: list[str]
	testability: Literal['testable', 'partial', 'untestable']
	testability_reason: str | None = None
	importance: Literal['core', 'secondary', 'peripheral']


class WebsiteAnalysis(BaseModel):
	site_name: str
	category: str = Field(min_length=1)
	description: str
	key_pages: list[PageInfo]
	features: list[Feature]
	identified_user_flows: list[str]

	@model_validator(mode='after')
	def _normalize_category(self) -> 'WebsiteAnalysis':
		if not self.category or self.category.lower() in ('unknown', 'n/a', 'none', ''):
			self.category = 'uncategorized'
		return self


# ─── Phase 2: Test Generation ──────────────────────────────────────────────────


class TestScenario(BaseModel):
	name: Annotated[str, AfterValidator(lambda v: v[:100] if len(v) > 100 else v)]
	description: str = Field(min_length=1)
	priority: Literal['critical', 'high', 'medium', 'low']
	feature_category: FeatureCategory
	target_feature: str
	test_persona: str
	steps_description: str = Field(min_length=1)
	success_criteria: str = Field(min_length=1)


class TestPlan(BaseModel):
	scenarios: list[TestScenario]


# ─── Structured verdict (returned by execution agent) ─────────────────────────


class ScenarioExecutionVerdict(BaseModel):
	"""Structured per-scenario verdict returned by the execution agent."""

	success: bool = Field(
		description='True if scenario passed according to success criteria, else False.',
	)
	reason: str = Field(
		default='',
		description='Why the scenario passed or failed, grounded in observed UI behavior.',
	)
	process_evaluation: str = Field(
		default='',
		description='Assessment of step-by-step process quality and friction.',
	)
	logical_evaluation: str = Field(
		default='',
		description='Assessment of UI/system logic and consistency for this flow.',
	)
	usability_evaluation: str = Field(
		default='',
		description='Assessment of clarity, affordances, and user friendliness.',
	)
	validation_evidence: str = Field(
		default='',
		description=(
			'Concrete verification evidence used for verdict: what was checked, where it was checked, and what was observed.'
		),
	)
	feature_suggestions: list[str] = Field(
		default_factory=list,
		description='1-3 concrete feature or UX improvement suggestions from this persona perspective.',
	)


# ─── Judge verdict ─────────────────────────────────────────────────────────────


class TraitEvaluation(BaseModel):
	"""Single trait pass/fail entry — used instead of dict[str, str] to avoid
	OpenAI strict-mode ``additionalProperties: false`` blocking dynamic keys."""

	trait_name: str = Field(description='Exact trait dimension name from the persona (e.g. "technical_literacy", "patience").')
	assessment: Literal['pass', 'fail'] = Field(description='"pass" or "fail".')


class JudgeVerdict(BaseModel):
	reasoning: str
	verdict: bool
	failure_reason: str
	impossible_task: bool
	reached_captcha: bool
	failure_category: Literal['website_issue', 'test_limitation'] | None
	process_evaluation: str = ''
	logical_evaluation: str = ''
	usability_evaluation: str = ''
	feedback_quality: FeedbackQualityScore | None = None
	trait_evaluations: list[TraitEvaluation] = Field(
		default_factory=list,
		description=(
			'Per-trait pass/fail verdicts. One entry per trait dimension from the persona. '
			'Each entry has trait_name (exact dimension name) and assessment ("pass" or "fail").'
		),
	)

	@property
	def trait_evaluations_dict(self) -> dict[str, Literal['pass', 'fail']]:
		"""Convert list to {trait_name: assessment} dict for consumers."""
		return {entry.trait_name: entry.assessment for entry in self.trait_evaluations}

	missing_signals: list[str] = Field(
		default_factory=list,
		description=(
			'Confirmation signals that were expected but not observed '
			'(e.g. "ephemeral toast not captured", "Active status badge not visible in list"). '
			'The outcome still passed via another signal. '
			'Report for UX improvement only — never used to fail the test.'
		),
	)


# ─── Phase 3: Results ──────────────────────────────────────────────────────────


class TestResult(BaseModel):
	scenario: TestScenario
	success: bool | None
	judgement: JudgeVerdict | None
	actions: list[dict[str, Any]]
	errors: list[str | None]
	duration: float
	failure_category: Literal['website_issue', 'test_limitation'] | None = None
	pages_visited: list[str] = Field(default_factory=list)
	screenshot_paths: list[str | None] = Field(default_factory=list)
	form_fills: list[dict] = Field(default_factory=list)
	process_evaluation: str = ''
	logical_evaluation: str = ''
	usability_evaluation: str = ''
	reason: str = ''
	validation_evidence: str = ''
	feedback_quality: FeedbackQualityScore | None = None
	trait_evaluations: dict[str, Literal['pass', 'fail']] | None = None
	missing_signals: list[str] = Field(default_factory=list)
	feature_suggestions: list[str] = Field(default_factory=list)


class ReportSummary(BaseModel):
	total: int
	passed: int
	failed: int
	pass_rate: float
	website_issues: int = 0
	test_limitations: int = 0
	by_priority: dict[str, dict[str, int]]


class ExecutiveSummary(BaseModel):
	"""LLM-generated executive summary of evaluation findings."""

	overall_assessment: str = Field(description='1-2 sentence overall site quality assessment.')
	key_findings: list[str] = Field(description='3-5 key UX findings ranked by severity.')
	recommended_actions: list[str] = Field(description='Top 3 recommended actions to improve the site.')


class TokenUsage(BaseModel):
	"""Accumulated LLM token usage for a pipeline phase."""

	input_tokens: int = 0
	output_tokens: int = 0


class EvaluationReport(BaseModel):
	url: str
	timestamp: str
	analysis: WebsiteAnalysis
	results: list[TestResult]
	summary: ReportSummary
	executive_summary: ExecutiveSummary | None = None
	persona_discovery_tokens: TokenUsage | None = None
	murphy_tokens: TokenUsage | None = None
