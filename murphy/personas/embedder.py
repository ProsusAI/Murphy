"""Shared embedding utility for the persona pipeline.

Provides batched text embedding via OpenAI's text-embedding-3-small model.
Used in two places:
- discovery.py: embed observed trait strings for dimension clustering
- pipeline.py: embed session timelines to build per-persona centroid embeddings
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from openai import AsyncOpenAI

from murphy.personas.compressor import compress_session
from murphy.personas.models import AnalyticsSession

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = 'text-embedding-3-small'
EMBEDDING_BATCH_SIZE = 50  # session timelines are long; keep well under the 300k token/request limit
# EMBEDDING_MAX_CHARS = 30000  # ~7,500 tokens; safely under the 8,192 token/string limit
EMBEDDING_MAX_CHARS = 6000  # 25,000 tokens; safely under the 300k token/request limit


async def embed_texts(texts: list[str]) -> np.ndarray:
	"""Embed a list of strings via OpenAI. Returns an (N, dim) float64 array."""
	client = AsyncOpenAI()
	all_embeddings: list[list[float]] = []

	for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
		batch = [t[:EMBEDDING_MAX_CHARS] for t in texts[i : i + EMBEDDING_BATCH_SIZE]]
		resp = await client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
		for item in sorted(resp.data, key=lambda x: x.index):
			all_embeddings.append(item.embedding)

	return np.array(all_embeddings, dtype=np.float64)


async def embed_sessions(
	sessions: list[AnalyticsSession],
	person_contexts: dict[str, Any],
) -> dict[str, np.ndarray]:
	"""Compress each session into a timeline and embed it.

	Returns a dict mapping session_id -> embedding vector.
	The compression is deterministic so re-running it is cheap.
	"""
	if not sessions:
		return {}

	timelines = [compress_session(s, person_contexts.get(s.user_id)) for s in sessions]
	logger.info('Embedding %d session timelines', len(timelines))
	matrix = await embed_texts(timelines)
	return {s.session_id: matrix[i] for i, s in enumerate(sessions)}
