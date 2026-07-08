# Copyright © 2026 MIH AI B.V.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Murphy — LLM factory supporting multiple providers via browser_use."""

import os

from browser_use.llm import BaseChatModel

_PROVIDER_MAP = {
	'openai': ('browser_use.llm.openai.chat', 'ChatOpenAI', 'OPENAI_API_KEY'),
	'anthropic': ('browser_use.llm.anthropic.chat', 'ChatAnthropic', 'ANTHROPIC_API_KEY'),
	'google': ('browser_use.llm.google.chat', 'ChatGoogle', 'GOOGLE_API_KEY'),
	'azure': ('browser_use.llm.azure.chat', 'ChatAzureOpenAI', 'AZURE_OPENAI_KEY'),
	'mistral': ('browser_use.llm.mistral.chat', 'ChatMistral', 'MISTRAL_API_KEY'),
	'groq': ('browser_use.llm.groq.chat', 'ChatGroq', 'GROQ_API_KEY'),
	'deepseek': ('browser_use.llm.deepseek.chat', 'ChatDeepSeek', 'DEEPSEEK_API_KEY'),
	'cerebras': ('browser_use.llm.cerebras.chat', 'ChatCerebras', 'CEREBRAS_API_KEY'),
	'ollama': ('browser_use.llm.ollama.chat', 'ChatOllama', None),
	'openrouter': ('browser_use.llm.openrouter.chat', 'ChatOpenRouter', 'OPENROUTER_API_KEY'),
	'bu': ('browser_use.llm.browser_use.chat', 'ChatBrowserUse', 'BROWSER_USE_API_KEY'),
}

SUPPORTED_PROVIDERS = sorted(_PROVIDER_MAP.keys())


def create_llm(model: str, provider: str = 'openai') -> BaseChatModel:
	"""Create an LLM instance from a provider name and model string.

	The model name is passed directly to the provider — use exact names as
	they appear in the provider's docs (e.g. 'gemini-2.5-pro', 'claude-sonnet-4-20250514').
	"""
	if provider not in _PROVIDER_MAP:
		raise ValueError(f"Unknown provider: '{provider}'. Supported: {', '.join(SUPPORTED_PROVIDERS)}")

	module_path, class_name, api_key_env = _PROVIDER_MAP[provider]

	from importlib import import_module

	cls = getattr(import_module(module_path), class_name)

	kwargs: dict = {'model': model}
	if api_key_env:
		api_key = os.getenv(api_key_env)
		if api_key:
			kwargs['api_key'] = api_key

	# Azure needs extra env vars
	if provider == 'azure':
		azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
		if azure_endpoint:
			kwargs['azure_endpoint'] = azure_endpoint

	return cls(**kwargs)
