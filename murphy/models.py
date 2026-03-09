"""Pydantic models for the Murphy evaluation pipeline."""

from enum import IntEnum
from typing import Annotated, Any, Literal

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
]


# ─── Trait system ─────────────────────────────────────────────────────────────
#
# Each test persona maps to a TraitVector and a TestType. The trait vector
# captures five behavioral dimensions (technical_literacy, patience, intent,
# exploration, reading_comprehension) at low/medium/high levels. During
# judging, each trait level selects a different evaluation question — e.g.
# a low-patience persona is judged on whether the site provided *immediate*
# feedback, while a high-patience persona only needs eventual correctness.
#
# TestType controls pass/fail semantics in the judge:
#   ux       — silent handling with no visible feedback is a FAIL
#   security — silent sanitization is CORRECT; only crashes/leaks fail
#   boundary — graceful degradation is a PASS; only unhandled exceptions fail
#
# See core/judge.py (TRAIT_JUDGE_QUESTIONS, TEST_TYPE_RULES) for the full
# mapping from trait levels to evaluation questions.


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


TestType = Literal['ux', 'security', 'boundary']

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
	test_persona: TestPersona
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


# ─── Judge verdict ─────────────────────────────────────────────────────────────


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
	trait_evaluations: dict[str, str] | None = None
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
	trait_evaluations: dict[str, str] | None = None
	missing_signals: list[str] = Field(default_factory=list)


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


class EvaluationReport(BaseModel):
	url: str
	timestamp: str
	analysis: WebsiteAnalysis
	results: list[TestResult]
	summary: ReportSummary
	executive_summary: ExecutiveSummary | None = None
