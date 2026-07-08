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

"""Monkey-patch: make browser_use's schema_dict_to_pydantic_model resolve
$defs/$ref before validation so schemas with nested Pydantic models work."""

import browser_use.tools.extraction.schema_utils as _schema_utils

_orig = _schema_utils.schema_dict_to_pydantic_model


def _resolve_refs(schema: dict | list, defs: dict | None = None) -> dict | list:
	"""Recursively inline all $ref references from $defs."""
	if defs is None:
		assert isinstance(schema, dict)
		defs = schema.get('$defs', schema.get('definitions', {}))
	if isinstance(schema, dict):
		if '$ref' in schema:
			ref_path = schema['$ref'].split('/')[-1]
			resolved = defs.get(ref_path, {})  # type: ignore[union-attr]
			merged = {k: v for k, v in schema.items() if k != '$ref'}
			merged.update(_resolve_refs(resolved, defs))
			return merged
		return {
			k: _resolve_refs(v, defs) if isinstance(v, (dict, list)) else v
			for k, v in schema.items()
			if k not in ('$defs', 'definitions')
		}
	if isinstance(schema, list):
		return [_resolve_refs(item, defs) if isinstance(item, (dict, list)) else item for item in schema]
	return schema


def _patched(schema: dict):  # type: ignore[type-arg]
	"""Flatten $defs/$ref then delegate to the original implementation."""
	if '$defs' in schema or 'definitions' in schema or '$ref' in schema:
		schema = _resolve_refs(schema)  # type: ignore[assignment]
	return _orig(schema)


_applied = False


def apply() -> None:
	"""Apply the monkey-patch (idempotent)."""
	global _applied
	if _applied:
		return
	_schema_utils.schema_dict_to_pydantic_model = _patched  # type: ignore[assignment]
	_applied = True
