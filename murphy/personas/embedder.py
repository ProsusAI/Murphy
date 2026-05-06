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
import tiktoken
from openai import AsyncOpenAI

from murphy.personas.compressor import compress_session
from murphy.personas.models import AnalyticsSession

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = 'text-embedding-3-small'
EMBEDDING_BATCH_SIZE = 10
EMBEDDING_MAX_TOKENS = 8000  # just under the 8,192 token model limit

_ENCODER = tiktoken.get_encoding('cl100k_base')


def _truncate_to_tokens(text: str) -> str:
	tokens = _ENCODER.encode(text)
	if len(tokens) <= EMBEDDING_MAX_TOKENS:
		return text
	logger.warning(
		'Truncating session from %d to %d tokens (%.0f%% kept)',
		len(tokens),
		EMBEDDING_MAX_TOKENS,
		EMBEDDING_MAX_TOKENS / len(tokens) * 100,
	)
	return _ENCODER.decode(tokens[:EMBEDDING_MAX_TOKENS])


async def embed_texts(texts: list[str]) -> np.ndarray:
	"""Embed a list of strings via OpenAI. Returns an (N, dim) float64 array."""
	client = AsyncOpenAI()
	all_embeddings: list[list[float]] = []

	for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
		batch = [_truncate_to_tokens(t) for t in texts[i : i + EMBEDDING_BATCH_SIZE]]
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
