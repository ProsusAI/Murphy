"""Smoke tests for run_databricks_persona_pipeline with mocked adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from murphy.personas.models import AnalyticsSession
from murphy.personas.pipeline_models import (
	DimensionScore,
	Persona,
	PersonaResult,
	SessionPersonaAssignment,
	SessionScore,
	TraitDimension,
	TraitSchema,
)


def _sample_session(session_id: str = 'conv:sess') -> AnalyticsSession:
	from datetime import datetime, timezone

	ts = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
	return AnalyticsSession(
		session_id=session_id,
		user_id='user-a',
		started_at=ts,
		ended_at=ts,
		event_count=1,
		events=[],
		source='databricks',
	)


@pytest.mark.asyncio
async def test_run_databricks_persona_pipeline_end_to_end_mocked():
	schema = TraitSchema(
		dimensions=[
			TraitDimension(
				name='Patience',
				description='desc',
				why_chosen='why',
				low_description='low',
				high_description='high',
			)
		],
		rationale='test',
	)
	score = SessionScore(
		session_id='conv:sess',
		user_id='user-a',
		reasoning='ok',
		scores=[DimensionScore(trait_name='Patience', score=3)],
	)
	persona_result = PersonaResult(
		personas=[
			Persona(
				persona_id=0,
				name='Test Persona',
				description='desc',
				centroid=[DimensionScore(trait_name='Patience', score=3.0)],
				distinguishing_traits=['Patience'],
				size=1,
			)
		],
		assignments=[SessionPersonaAssignment(session_id='conv:sess', user_id='user-a', persona_id=0)],
		num_clusters=1,
		silhouette_score=0.5,
	)

	mock_adapter = MagicMock()
	mock_adapter.get_sessions = AsyncMock(return_value=[_sample_session()])
	mock_adapter.fetch_population_paths = AsyncMock(return_value='Top pages')
	mock_adapter.last_session_contexts = {'conv:sess': {'interactions': []}}
	mock_adapter.last_person_contexts = {'user-a': {'user_email': 'user-a'}}

	with (
		patch('murphy.personas.databricks_pipeline.DatabricksAdapter', return_value=mock_adapter),
		patch('murphy.personas.databricks_pipeline.run_discovery', AsyncMock(return_value=schema)),
		patch('murphy.personas.databricks_pipeline.run_scoring', AsyncMock(return_value=[score])),
		patch('murphy.personas.databricks_pipeline.cluster_sessions') as mock_cluster,
		patch('murphy.personas.databricks_pipeline.embed_sessions', AsyncMock(return_value={'conv:sess': np.zeros(3)})),
		patch('murphy.personas.databricks_pipeline.label_personas', AsyncMock(return_value=MagicMock(personas=[]))),
		patch('murphy.personas.databricks_pipeline.build_persona_result', return_value=persona_result),
		patch('murphy.personas.databricks_pipeline.compress_session', return_value='timeline sample'),
	):
		mock_cluster.return_value = MagicMock(k=1, labels=np.array([0]), centroids=np.array([[3.0]]))

		from murphy.personas.databricks_pipeline import run_databricks_persona_pipeline

		result_schema, scores, result, sample, tokens = await run_databricks_persona_pipeline(
			discovery_sessions=1,
			scoring_sessions=1,
			min_events=30,
			event_date_from='2026-05-01',
		)

	assert result_schema is schema
	assert scores == [score]
	assert result is persona_result
	assert sample == 'timeline sample'
	assert mock_adapter.get_sessions.await_count == 2
