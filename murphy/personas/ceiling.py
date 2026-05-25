"""Intra-cluster ceiling metrics.

For each persona cluster, compute the average pairwise similarity among
all real-user sessions in that cluster. This establishes an empirical
ceiling — the score two real members of the same persona achieve when
compared to each other under the exact same formulas used to score Murphy.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np

from murphy.personas.pipeline_models import SessionScore


def pairwise_llm_ceiling(cluster_scores: list[SessionScore]) -> float | None:
	"""Average pairwise LLM similarity among real-user sessions in a cluster.

	Uses the identical delta/4 formula as evaluate_similarity(). Trait dimensions
	missing from either session in a pair are skipped for that pair. Returns None
	if fewer than 2 sessions are provided or no valid pairs exist.
	"""
	if len(cluster_scores) < 2:
		return None
	pair_sims: list[float] = []
	for a, b in combinations(cluster_scores, 2):
		dict_a = a.scores_as_dict()
		dict_b = b.scores_as_dict()
		common = dict_a.keys() & dict_b.keys()
		if not common:
			continue
		mean_norm_delta = sum(abs(dict_a[t] - dict_b[t]) / 4.0 for t in common) / len(common)
		pair_sims.append(max(0.0, min(1.0, 1.0 - mean_norm_delta)))
	return round(sum(pair_sims) / len(pair_sims), 3) if pair_sims else None


def pairwise_embedding_ceiling(embeddings: list[list[float]]) -> float | None:
	"""Average pairwise cosine similarity among real-user session embeddings in a cluster.

	Uses the identical cosine formula as evaluate_similarity(). Pairs where either
	vector has zero norm are skipped. Returns None if fewer than 2 embeddings are
	provided or no valid pairs exist.
	"""
	if len(embeddings) < 2:
		return None
	vecs = [np.array(e, dtype=np.float64) for e in embeddings]
	pair_sims: list[float] = []
	for a, b in combinations(vecs, 2):
		norm = np.linalg.norm(a) * np.linalg.norm(b)
		if norm > 0:
			pair_sims.append(float(np.dot(a, b) / norm))
	return round(sum(pair_sims) / len(pair_sims), 3) if pair_sims else None
