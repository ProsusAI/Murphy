"""Tests for Phase 3a — clustering (pure algorithmic, no LLM)."""

import numpy as np

from murphy.personas.clustering import (
	ClusteringResult,
	cluster_sessions,
	extract_score_matrix,
	find_optimal_k,
)
from murphy.personas.pipeline_models import (
	DimensionScore,
	SessionScore,
	TraitDimension,
	TraitSchema,
)

SCHEMA = TraitSchema(
	dimensions=[
		TraitDimension(
			name='engagement_depth',
			description='How deeply the user engages.',
			why_chosen='Observed variation in depth.',
			low_description='Passive browsing',
			high_description='Deep multi-feature usage',
		),
		TraitDimension(
			name='exploration_breadth',
			description='How many features the user explores.',
			why_chosen='Some users stayed in one area; others explored widely.',
			low_description='Single feature focus',
			high_description='Wide exploration across features',
		),
		TraitDimension(
			name='feedback_depth',
			description='How detailed the user feedback is.',
			why_chosen='Feedback ranged from thumbs up to detailed text.',
			low_description='No feedback',
			high_description='Detailed written feedback',
		),
	],
	rationale='Core behavioral axes.',
)


def _make_score(
	session_id: str,
	user_id: str,
	engagement: int,
	exploration: int,
	feedback: int,
) -> SessionScore:
	return SessionScore(
		session_id=session_id,
		user_id=user_id,
		scores=[
			DimensionScore(trait_name='engagement_depth', score=engagement),
			DimensionScore(trait_name='exploration_breadth', score=exploration),
			DimensionScore(trait_name='feedback_depth', score=feedback),
		],
		reasoning='test',
	)


def _make_clusterable_scores() -> list[SessionScore]:
	"""Three tight clusters in 3D score space."""
	scores: list[SessionScore] = []
	# Cluster A: high engagement, low exploration, low feedback
	for i in range(15):
		scores.append(_make_score(f'a-{i}', f'u-a-{i}', 5, 1, 1))
	# Cluster B: low engagement, high exploration, low feedback
	for i in range(15):
		scores.append(_make_score(f'b-{i}', f'u-b-{i}', 1, 5, 1))
	# Cluster C: mid engagement, mid exploration, high feedback
	for i in range(15):
		scores.append(_make_score(f'c-{i}', f'u-c-{i}', 3, 3, 5))
	return scores


# ─── extract_score_matrix ────────────────────────────────────────────────────


def test_extract_score_matrix_shape():
	scores = [_make_score('s1', 'u1', 4, 2, 3), _make_score('s2', 'u2', 1, 5, 2)]
	matrix, session_ids = extract_score_matrix(scores, SCHEMA)

	assert matrix.shape == (2, 3)
	assert session_ids == ['s1', 's2']


def test_extract_score_matrix_alignment():
	"""Values should align to schema dimension order, not score list order."""
	score = SessionScore(
		session_id='s1',
		user_id='u1',
		scores=[
			DimensionScore(trait_name='feedback_depth', score=5),
			DimensionScore(trait_name='engagement_depth', score=1),
			DimensionScore(trait_name='exploration_breadth', score=3),
		],
		reasoning='test',
	)
	matrix, _ = extract_score_matrix([score], SCHEMA)
	# Schema order: engagement, exploration, feedback
	assert list(matrix[0]) == [1.0, 3.0, 5.0]


def test_extract_score_matrix_missing_dimension():
	"""Missing dimensions should be filled with 3.0 (neutral)."""
	score = SessionScore(
		session_id='s1',
		user_id='u1',
		scores=[
			DimensionScore(trait_name='engagement_depth', score=5),
		],
		reasoning='test',
	)
	matrix, _ = extract_score_matrix([score], SCHEMA)
	assert matrix[0, 0] == 5.0
	assert matrix[0, 1] == 3.0  # exploration_breadth missing -> neutral
	assert matrix[0, 2] == 3.0  # feedback_depth missing -> neutral


# ─── find_optimal_k ─────────────────────────────────────────────────────────


def test_find_optimal_k_returns_best():
	"""With well-separated clusters, should find k=3."""
	scores = _make_clusterable_scores()
	matrix, _ = extract_score_matrix(scores, SCHEMA)
	best_k, sil_scores = find_optimal_k(matrix, k_range=(2, 6))

	assert best_k == 3
	assert 2 in sil_scores
	assert 3 in sil_scores
	assert sil_scores[3] > sil_scores[2]


def test_find_optimal_k_caps_at_n_minus_1():
	"""With only 4 samples, k_range max should cap at 3."""
	scores = [_make_score(f's{i}', f'u{i}', i + 1, 5 - i, 3) for i in range(4)]
	matrix, _ = extract_score_matrix(scores, SCHEMA)
	best_k, sil_scores = find_optimal_k(matrix, k_range=(2, 10))

	assert max(sil_scores.keys()) <= 3


# ─── cluster_sessions ───────────────────────────────────────────────────────


def test_cluster_sessions_with_explicit_k():
	scores = _make_clusterable_scores()
	result = cluster_sessions(scores, SCHEMA, k=3)

	assert isinstance(result, ClusteringResult)
	assert result.k == 3
	assert result.labels.shape == (45,)
	assert result.centroids.shape == (3, 3)
	assert result.silhouette > 0.5
	assert len(set(result.labels)) == 3


def test_cluster_sessions_auto_k():
	scores = _make_clusterable_scores()
	result = cluster_sessions(scores, SCHEMA, k_range=(2, 8))

	assert result.k == 3
	assert result.silhouette > 0.5


def test_cluster_sessions_small_dataset():
	"""With 3 sessions, only k=2 is valid."""
	scores = [
		_make_score('s1', 'u1', 5, 1, 1),
		_make_score('s2', 'u2', 1, 5, 1),
		_make_score('s3', 'u3', 3, 3, 5),
	]
	result = cluster_sessions(scores, SCHEMA, k_range=(2, 8))

	assert result.k == 2
	assert result.labels.shape == (3,)


def test_cluster_sessions_with_standardize():
	scores = _make_clusterable_scores()
	result = cluster_sessions(scores, SCHEMA, k=3, standardize=True)

	assert result.k == 3
	assert result.silhouette > 0.5
	# Centroids should be in original score space (inverse-transformed)
	assert np.all(result.centroids >= 0)
	assert np.all(result.centroids <= 6)


def test_cluster_sessions_explicit_k_clamped():
	"""k > n-1 should be clamped down."""
	scores = [_make_score(f's{i}', f'u{i}', i + 1, 5 - i, 3) for i in range(4)]
	result = cluster_sessions(scores, SCHEMA, k=20)

	assert result.k <= 3
