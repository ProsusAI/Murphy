"""Tests for persona pipeline Pydantic models."""

from murphy.personas.pipeline_models import (
	DimensionScore,
	SessionObservation,
	SessionScore,
	TraitDimension,
	TraitSchema,
)

# ─── SessionObservation ─────────────────────────────────────────────────────


def test_observation_roundtrip():
	obs = SessionObservation(
		session_id='sess-1',
		observed_traits=['rapid navigation', 'single feature focus'],
		behavioral_summary='User navigated quickly through the app with minimal engagement.',
	)
	rebuilt = SessionObservation.model_validate(obs.model_dump())
	assert rebuilt == obs


# ─── TraitDimension ─────────────────────────────────────────────────────────


def test_dimension_roundtrip():
	dim = TraitDimension(
		name='engagement_depth',
		description='How deeply the user engages with product features.',
		why_chosen='Observations repeatedly contrasted shallow vs deep feature use.',
		low_description='Passive browser, minimal interaction',
		high_description='Power user, deep multi-feature engagement',
	)
	rebuilt = TraitDimension.model_validate(dim.model_dump())
	assert rebuilt == dim


# ─── TraitSchema ─────────────────────────────────────────────────────────────


def test_schema_roundtrip():
	schema = TraitSchema(
		dimensions=[
			TraitDimension(
				name='engagement',
				description='Engagement level',
				why_chosen='Summaries varied on interaction depth.',
				low_description='Low engagement',
				high_description='High engagement',
			),
		],
		rationale='Testing roundtrip.',
	)
	rebuilt = TraitSchema.model_validate(schema.model_dump())
	assert rebuilt == schema


# ─── SessionScore ────────────────────────────────────────────────────────────


def test_score_roundtrip():
	score = SessionScore(
		session_id='sess-1',
		user_id='user-a',
		scores=[
			DimensionScore(trait_name='engagement', score=4),
			DimensionScore(trait_name='exploration', score=2),
		],
		reasoning='User showed deep engagement but narrow exploration.',
	)
	rebuilt = SessionScore.model_validate(score.model_dump())
	assert rebuilt == score


def test_score_as_dict():
	score = SessionScore(
		session_id='sess-1',
		user_id='user-a',
		scores=[
			DimensionScore(trait_name='engagement', score=4),
			DimensionScore(trait_name='exploration', score=2),
		],
		reasoning='Test.',
	)
	d = score.scores_as_dict()
	assert d == {'engagement': 4, 'exploration': 2}
