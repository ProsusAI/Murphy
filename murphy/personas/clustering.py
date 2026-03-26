"""Phase 3a — Clustering: group scored sessions into persona clusters.

Pure algorithmic module (no LLM calls). Uses K-Means with automatic K
selection via silhouette analysis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from murphy.personas.pipeline_models import SessionScore, TraitSchema

logger = logging.getLogger(__name__)

NEUTRAL_SCORE = 3.0


@dataclass
class ClusteringResult:
	"""Raw output from the clustering algorithm."""

	labels: np.ndarray
	centroids: np.ndarray
	k: int
	silhouette: float
	silhouette_scores: dict[int, float]


def extract_score_matrix(
	scores: list[SessionScore],
	schema: TraitSchema,
) -> tuple[np.ndarray, list[str]]:
	"""Build an (N, D) score matrix aligned to the schema dimension order.

	Returns the matrix and a parallel list of session_ids so callers can
	map rows back to sessions.  Missing dimensions are filled with
	``NEUTRAL_SCORE`` (3.0).
	"""
	dim_names = [d.name for d in schema.dimensions]
	session_ids: list[str] = []
	rows: list[list[float]] = []

	for s in scores:
		score_dict = s.scores_as_dict()
		row = [float(score_dict.get(name, NEUTRAL_SCORE)) for name in dim_names]
		rows.append(row)
		session_ids.append(s.session_id)

	return np.array(rows, dtype=np.float64), session_ids


def find_optimal_k(
	matrix: np.ndarray,
	k_range: tuple[int, int] = (4, 10),
) -> tuple[int, dict[int, float]]:
	"""Try each K in range and return the one with the highest silhouette score.

	The upper bound is capped at ``n_samples - 1`` to stay valid for
	small datasets.
	"""
	n = matrix.shape[0]
	lo = max(k_range[0], 2)
	hi = min(k_range[1], n - 1)

	if lo > hi:
		return lo, {lo: -1.0}

	sil_scores: dict[int, float] = {}
	for k in range(lo, hi + 1):
		km = KMeans(n_clusters=k, n_init=10, random_state=42)
		labels = km.fit_predict(matrix)
		sil = float(silhouette_score(matrix, labels))
		sil_scores[k] = sil
		logger.debug('K=%d  silhouette=%.4f', k, sil)

	best_k = max(sil_scores, key=lambda k: sil_scores[k])
	logger.info('Optimal K=%d (silhouette=%.4f)', best_k, sil_scores[best_k])
	return best_k, sil_scores


def cluster_sessions(
	scores: list[SessionScore],
	schema: TraitSchema,
	k: int | None = None,
	k_range: tuple[int, int] = (4, 10),
	standardize: bool = False,
) -> ClusteringResult:
	"""Cluster scored sessions into persona groups.

	Parameters
	----------
	scores:
		Session scores from Phase 2.
	schema:
		The trait schema used for scoring (defines dimension order).
	k:
		Explicit number of clusters.  When ``None``, auto-selects via
		silhouette analysis over *k_range*.
	k_range:
		``(min_k, max_k)`` search range for automatic K selection.
	standardize:
		If ``True``, z-score standardize each dimension before clustering.
		Useful when per-dimension variance is very uneven.

	Returns
	-------
	ClusteringResult
		Labels, centroids (in original score space), chosen K, silhouette
		score, and the full silhouette-per-K map.
	"""
	matrix, _ = extract_score_matrix(scores, schema)

	fit_matrix = matrix
	scaler: StandardScaler | None = None
	if standardize:
		scaler = StandardScaler()
		fit_matrix = scaler.fit_transform(matrix)

	sil_scores: dict[int, float] = {}
	if k is None:
		k, sil_scores = find_optimal_k(fit_matrix, k_range)
	else:
		k = min(k, matrix.shape[0] - 1)
		k = max(k, 2)

	km = KMeans(n_clusters=k, n_init=10, random_state=42)
	labels = km.fit_predict(fit_matrix)

	sil = float(silhouette_score(fit_matrix, labels)) if len(set(labels)) > 1 else 0.0
	if k not in sil_scores:
		sil_scores[k] = sil

	centroids = km.cluster_centers_
	if scaler is not None:
		centroids = scaler.inverse_transform(centroids)

	logger.info('Clustered %d sessions into %d personas (silhouette=%.4f)', len(scores), k, sil)
	return ClusteringResult(
		labels=labels,
		centroids=centroids,
		k=k,
		silhouette=sil,
		silhouette_scores=sil_scores,
	)
