"""Tests for judge helper functions (no LLM calls)."""

from murphy.core.judge import (
	TEST_TYPE_RULES,
	TRAIT_JUDGE_QUESTIONS,
	build_judge_trait_context,
)
from murphy.models import PERSONA_REGISTRY, TraitLevel

# ─── build_judge_trait_context ────────────────────────────────────────────────


def test_build_judge_trait_context_first_timer():
	traits, test_type = PERSONA_REGISTRY['first_timer']
	context = build_judge_trait_context('first_timer', traits, test_type)
	assert 'first_timer' in context
	assert test_type in context
	assert 'technical_literacy' in context
	assert 'patience' in context


def test_build_judge_trait_context_adversarial():
	traits, test_type = PERSONA_REGISTRY['adversarial']
	context = build_judge_trait_context('adversarial', traits, test_type)
	assert 'adversarial' in context
	assert 'RESISTING' in context  # adversarial intent question


def test_build_judge_trait_context_exploratory():
	traits, test_type = PERSONA_REGISTRY['edge_case']
	context = build_judge_trait_context('edge_case', traits, test_type)
	assert 'exploratory' in context


def test_build_judge_trait_context_benign_intent():
	traits, test_type = PERSONA_REGISTRY['first_timer']
	context = build_judge_trait_context('first_timer', traits, test_type)
	assert 'benign' in context


# ─── TRAIT_JUDGE_QUESTIONS ────────────────────────────────────────────────────


def test_all_trait_questions_have_all_levels():
	for trait_name, levels in TRAIT_JUDGE_QUESTIONS.items():
		for level in [TraitLevel.low, TraitLevel.medium, TraitLevel.high]:
			assert level in levels, f'{trait_name} missing {level.name}'


# ─── TEST_TYPE_RULES ─────────────────────────────────────────────────────────


def test_all_test_types_have_rules():
	assert 'ux' in TEST_TYPE_RULES
	assert 'security' in TEST_TYPE_RULES
	assert 'boundary' in TEST_TYPE_RULES


# ─── PERSONA_REGISTRY coverage in judge context ──────────────────────────────


def test_all_personas_produce_valid_context():
	for persona, (traits, test_type) in PERSONA_REGISTRY.items():
		context = build_judge_trait_context(persona, traits, test_type)
		assert persona in context
		assert len(context) > 100  # non-trivial output
