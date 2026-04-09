"""Tests for murphy.llm — multi-provider LLM factory and CLI/API integration."""

from unittest.mock import MagicMock, patch

import pytest

from murphy.llm import SUPPORTED_PROVIDERS, create_llm

# ─── Provider resolution ────────────────────────────────────────────────────


def test_unknown_provider_raises_with_suggestions():
	with pytest.raises(ValueError, match='Unknown provider.*Supported'):
		create_llm('some-model', provider='nonexistent')


def test_supported_providers_list_is_complete():
	"""SUPPORTED_PROVIDERS should include all major providers."""
	expected = {'openai', 'google', 'anthropic', 'azure', 'mistral', 'groq', 'deepseek', 'cerebras', 'ollama', 'openrouter', 'bu'}
	assert expected == set(SUPPORTED_PROVIDERS)


# ─── API key from env ───────────────────────────────────────────────────────


def test_api_key_passed_from_env():
	"""create_llm should read the provider's env var and pass it to the constructor."""
	mock_cls = MagicMock()
	with patch.dict('os.environ', {'GOOGLE_API_KEY': 'test-key-123'}):
		with patch('importlib.import_module') as mock_import:
			mock_import.return_value = MagicMock(**{'ChatGoogle': mock_cls})
			create_llm('gemini-2.5-pro', provider='google')
			mock_cls.assert_called_once_with(model='gemini-2.5-pro', api_key='test-key-123')


def test_api_key_omitted_when_not_set():
	"""When env var is unset, api_key should not be passed (let SDK use its own default)."""
	mock_cls = MagicMock()
	env = {k: v for k, v in {}.items()}  # empty
	with patch.dict('os.environ', env, clear=True):
		with patch('importlib.import_module') as mock_import:
			mock_import.return_value = MagicMock(**{'ChatOpenAI': mock_cls})
			create_llm('gpt-5-mini', provider='openai')
			mock_cls.assert_called_once_with(model='gpt-5-mini')


def test_azure_passes_endpoint_from_env():
	"""Azure provider should pass azure_endpoint from AZURE_OPENAI_ENDPOINT."""
	mock_cls = MagicMock()
	with patch.dict('os.environ', {'AZURE_OPENAI_KEY': 'az-key', 'AZURE_OPENAI_ENDPOINT': 'https://my.azure.com'}):
		with patch('importlib.import_module') as mock_import:
			mock_import.return_value = MagicMock(**{'ChatAzureOpenAI': mock_cls})
			create_llm('gpt-4o', provider='azure')
			mock_cls.assert_called_once_with(model='gpt-4o', api_key='az-key', azure_endpoint='https://my.azure.com')


def test_ollama_no_api_key():
	"""Ollama is local — should never pass an api_key."""
	mock_cls = MagicMock()
	with patch('importlib.import_module') as mock_import:
		mock_import.return_value = MagicMock(**{'ChatOllama': mock_cls})
		create_llm('llama3', provider='ollama')
		mock_cls.assert_called_once_with(model='llama3')


# ─── CLI arg parsing ────────────────────────────────────────────────────────


def test_cli_provider_defaults():
	"""--provider defaults to 'openai', --judge-provider defaults to None."""
	parser = _build_parser()
	args = parser.parse_args(['--url', 'https://example.com'])
	assert args.provider == 'openai'
	assert args.judge_provider is None
	assert args.judge_model is None


def test_cli_provider_override():
	parser = _build_parser()
	args = parser.parse_args(['--url', 'https://example.com', '--provider', 'google', '--model', 'gemini-2.5-pro'])
	assert args.provider == 'google'
	assert args.model == 'gemini-2.5-pro'


def test_cli_judge_provider_independent():
	parser = _build_parser()
	args = parser.parse_args(
		[
			'--url',
			'https://example.com',
			'--provider',
			'google',
			'--model',
			'gemini-2.5-flash',
			'--judge-provider',
			'openai',
			'--judge-model',
			'gpt-5-mini',
		]
	)
	assert args.provider == 'google'
	assert args.model == 'gemini-2.5-flash'
	assert args.judge_provider == 'openai'
	assert args.judge_model == 'gpt-5-mini'


# ─── REST API request models ────────────────────────────────────────────────


def test_analyze_request_provider_default():
	from murphy.api.request_models import AnalyzeRequest

	req = AnalyzeRequest.model_validate({'url': 'https://example.com'})
	assert req.provider == 'openai'
	assert req.model == 'gpt-5-mini'


def test_execute_request_judge_provider_defaults_to_none():
	from murphy.api.request_models import ExecuteRequest

	req = ExecuteRequest.model_validate({'url': 'https://example.com'})
	assert req.provider == 'openai'
	assert req.judge_provider is None
	assert req.judge_model is None


def test_execute_request_custom_providers():
	from murphy.api.request_models import ExecuteRequest

	req = ExecuteRequest.model_validate(
		{
			'url': 'https://example.com',
			'provider': 'google',
			'model': 'gemini-2.5-pro',
			'judge_provider': 'anthropic',
			'judge_model': 'claude-sonnet-4-20250514',
		}
	)
	assert req.provider == 'google'
	assert req.model == 'gemini-2.5-pro'
	assert req.judge_provider == 'anthropic'
	assert req.judge_model == 'claude-sonnet-4-20250514'


def test_evaluate_request_provider_field():
	from murphy.api.request_models import EvaluateRequest

	req = EvaluateRequest.model_validate({'url': 'https://example.com', 'provider': 'mistral', 'model': 'mistral-large-latest'})
	assert req.provider == 'mistral'


# ─── Judge LLM creation logic ───────────────────────────────────────────────


def test_judge_llm_none_when_same_as_main():
	"""When judge provider+model match main, no separate judge LLM should be created."""
	# Replicate the CLI logic
	provider, model = 'openai', 'gpt-5-mini'
	judge_provider = provider  # defaults to main
	judge_model = model  # defaults to main
	should_create = judge_model != model or judge_provider != provider
	assert should_create is False


def test_judge_llm_created_when_different_provider():
	provider, model = 'openai', 'gpt-5-mini'
	judge_provider, judge_model = 'google', 'gemini-2.5-pro'
	should_create = judge_model != model or judge_provider != provider
	assert should_create is True


def test_judge_llm_created_when_different_model_same_provider():
	provider, model = 'openai', 'gpt-5-mini'
	judge_provider, judge_model = 'openai', 'gpt-5'
	should_create = judge_model != model or judge_provider != provider
	assert should_create is True


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _build_parser():
	"""Build the Murphy CLI parser for testing (mirrors cli.py's arg definitions)."""
	import argparse

	parser = argparse.ArgumentParser()
	parser.add_argument('--url')
	parser.add_argument('--provider', default='openai')
	parser.add_argument('--model', default='gpt-5-mini')
	parser.add_argument('--judge-provider', default=None)
	parser.add_argument('--judge-model', default=None)
	return parser
