"""Shared job storage for Murphy async API jobs."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field
from uuid_extensions import uuid7str

JobStatus = Literal['pending', 'running', 'completed', 'failed']


class JobRecord(BaseModel):
	"""Durable metadata for one Murphy job."""

	id: str = Field(default_factory=uuid7str)
	status: JobStatus = 'pending'
	kind: str
	payload_s3_key: str | None = None
	result_s3_key: str | None = None
	summary: dict[str, Any] | None = None
	error: str | None = None
	webhook_url: str | None = None
	created_at: float = Field(default_factory=time.time)
	updated_at: float = Field(default_factory=time.time)
	started_at: float | None = None
	finished_at: float | None = None
	ttl: int | None = None

	@classmethod
	def create(cls, kind: str, webhook_url: str | None = None, ttl_seconds: int | None = None) -> JobRecord:
		now = time.time()
		return cls(
			kind=kind,
			webhook_url=webhook_url,
			created_at=now,
			updated_at=now,
			ttl=int(now + ttl_seconds) if ttl_seconds is not None else None,
		)


class JobStore(Protocol):
	async def create_job(self, job: JobRecord, payload: dict[str, Any]) -> JobRecord: ...

	async def put_job(self, job: JobRecord) -> None: ...

	async def get_job(self, job_id: str) -> JobRecord | None: ...

	async def get_payload(self, job_id: str) -> dict[str, Any]: ...

	async def get_result(self, job_id: str) -> Any: ...

	async def mark_running(self, job_id: str) -> bool: ...

	async def mark_completed(self, job_id: str, result: Any, summary: dict[str, Any] | None = None) -> None: ...

	async def mark_failed(self, job_id: str, error: str) -> None: ...

	async def mark_stale_running_jobs_failed(self, max_age_seconds: int) -> list[str]: ...


class InMemoryJobStore:
	"""Test/local implementation with the same behavior as the durable store."""

	def __init__(self) -> None:
		self._jobs: dict[str, JobRecord] = {}
		self._payloads: dict[str, dict[str, Any]] = {}
		self._results: dict[str, Any] = {}

	async def create_job(self, job: JobRecord, payload: dict[str, Any]) -> JobRecord:
		self._jobs[job.id] = job
		self._payloads[job.id] = payload
		return job

	async def put_job(self, job: JobRecord) -> None:
		self._jobs[job.id] = job

	async def get_job(self, job_id: str) -> JobRecord | None:
		return self._jobs.get(job_id)

	async def get_payload(self, job_id: str) -> dict[str, Any]:
		return self._payloads[job_id]

	async def get_result(self, job_id: str) -> Any:
		return self._results.get(job_id)

	async def mark_running(self, job_id: str) -> bool:
		job = self._jobs.get(job_id)
		if job is None or job.status != 'pending':
			return False
		now = time.time()
		job.status = 'running'
		job.started_at = now
		job.updated_at = now
		self._jobs[job_id] = job
		return True

	async def mark_completed(self, job_id: str, result: Any, summary: dict[str, Any] | None = None) -> None:
		job = self._jobs[job_id]
		now = time.time()
		self._results[job_id] = result
		job.status = 'completed'
		job.result_s3_key = f'jobs/{job_id}/result.json'
		job.summary = summary
		job.updated_at = now
		job.finished_at = now
		self._jobs[job_id] = job

	async def mark_failed(self, job_id: str, error: str) -> None:
		job = self._jobs[job_id]
		now = time.time()
		job.status = 'failed'
		job.error = error
		job.updated_at = now
		job.finished_at = now
		self._jobs[job_id] = job

	async def mark_stale_running_jobs_failed(self, max_age_seconds: int) -> list[str]:
		now = time.time()
		failed: list[str] = []
		for job_id, job in list(self._jobs.items()):
			if job.status == 'running' and (now - job.updated_at) > max_age_seconds:
				await self.mark_failed(job_id, 'worker lost or timed out')
				failed.append(job_id)
		return failed


class AwsJobStore:
	"""DynamoDB metadata plus S3 payload/result storage."""

	def __init__(self, table_name: str, bucket_name: str, region_name: str | None = None) -> None:
		import boto3

		self.table_name = table_name
		self.bucket_name = bucket_name
		self._dynamodb: Any = boto3.resource('dynamodb', region_name=region_name)
		self._table = self._dynamodb.Table(table_name)
		self._s3: Any = boto3.client('s3', region_name=region_name)

	async def create_job(self, job: JobRecord, payload: dict[str, Any]) -> JobRecord:
		job.payload_s3_key = f'jobs/{job.id}/payload.json'
		self._put_s3_json(job.payload_s3_key, payload)
		self._table.put_item(Item=self._to_item(job))
		return job

	async def put_job(self, job: JobRecord) -> None:
		self._table.put_item(Item=self._to_item(job))

	async def get_job(self, job_id: str) -> JobRecord | None:
		resp = self._table.get_item(Key={'id': job_id}, ConsistentRead=True)
		item = resp.get('Item')
		return self._from_item(item) if item else None

	async def get_payload(self, job_id: str) -> dict[str, Any]:
		job = await self.get_job(job_id)
		if job is None or job.payload_s3_key is None:
			raise KeyError(job_id)
		return self._get_s3_json(job.payload_s3_key)

	async def get_result(self, job_id: str) -> Any:
		job = await self.get_job(job_id)
		if job is None or job.result_s3_key is None:
			return None
		return self._get_s3_json(job.result_s3_key)

	async def mark_running(self, job_id: str) -> bool:
		now = time.time()
		try:
			self._table.update_item(
				Key={'id': job_id},
				UpdateExpression='SET #status = :running, started_at = :now, updated_at = :now',
				ConditionExpression='#status = :pending',
				ExpressionAttributeNames={'#status': 'status'},
				ExpressionAttributeValues={':running': 'running', ':pending': 'pending', ':now': str(now)},
			)
			return True
		except Exception as exc:
			if exc.__class__.__name__ == 'ConditionalCheckFailedException':
				return False
			raise

	async def mark_completed(self, job_id: str, result: Any, summary: dict[str, Any] | None = None) -> None:
		result_key = f'jobs/{job_id}/result.json'
		self._put_s3_json(result_key, result)
		now = time.time()
		self._table.update_item(
			Key={'id': job_id},
			UpdateExpression=(
				'SET #status = :status, result_s3_key = :result_key, summary_json = :summary, '
				'updated_at = :now, finished_at = :now'
			),
			ExpressionAttributeNames={'#status': 'status'},
			ExpressionAttributeValues={
				':status': 'completed',
				':result_key': result_key,
				':summary': json.dumps(summary) if summary is not None else None,
				':now': str(now),
			},
		)

	async def mark_failed(self, job_id: str, error: str) -> None:
		now = time.time()
		self._table.update_item(
			Key={'id': job_id},
			UpdateExpression='SET #status = :status, error = :error, updated_at = :now, finished_at = :now',
			ExpressionAttributeNames={'#status': 'status'},
			ExpressionAttributeValues={':status': 'failed', ':error': error, ':now': str(now)},
		)

	async def mark_stale_running_jobs_failed(self, max_age_seconds: int) -> list[str]:
		cutoff = time.time() - max_age_seconds
		resp = self._table.scan(
			FilterExpression='#status = :running',
			ExpressionAttributeNames={'#status': 'status'},
			ExpressionAttributeValues={':running': 'running'},
		)
		failed: list[str] = []
		for item in resp.get('Items', []):
			job = self._from_item(item)
			if job.updated_at < cutoff:
				await self.mark_failed(job.id, 'worker lost or timed out')
				failed.append(job.id)
		return failed

	def _put_s3_json(self, key: str, payload: Any) -> None:
		self._s3.put_object(
			Bucket=self.bucket_name,
			Key=key,
			Body=json.dumps(payload, default=str).encode('utf-8'),
			ContentType='application/json',
		)

	def _get_s3_json(self, key: str) -> Any:
		resp = self._s3.get_object(Bucket=self.bucket_name, Key=key)
		return json.loads(resp['Body'].read().decode('utf-8'))

	def _to_item(self, job: JobRecord) -> dict[str, Any]:
		data = job.model_dump(exclude_none=True)
		if job.summary is not None:
			data['summary_json'] = json.dumps(job.summary)
			data.pop('summary', None)
		for key in ('created_at', 'updated_at', 'started_at', 'finished_at'):
			if key in data:
				data[key] = str(data[key])
		return data

	def _from_item(self, item: dict[str, Any]) -> JobRecord:
		data = dict(item)
		summary_json = data.pop('summary_json', None)
		if summary_json is not None:
			data['summary'] = json.loads(summary_json)
		for key in ('created_at', 'updated_at', 'started_at', 'finished_at'):
			if data.get(key) is not None:
				data[key] = float(data[key])
		return JobRecord.model_validate(data)


_store: JobStore | None = None


def get_job_store() -> JobStore:
	global _store
	if _store is not None:
		return _store

	table_name = os.environ.get('MURPHY_JOB_TABLE')
	bucket_name = os.environ.get('MURPHY_RESULTS_BUCKET')
	if table_name and bucket_name:
		_store = AwsJobStore(
			table_name=table_name,
			bucket_name=bucket_name,
			region_name=os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION'),
		)
	else:
		_store = InMemoryJobStore()
	return _store


def set_job_store_for_tests(store: JobStore | None) -> None:
	global _store
	_store = store
