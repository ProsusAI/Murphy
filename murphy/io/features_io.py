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

"""Murphy — features markdown read/write (analogous to test_plan_io.py for YAML)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
	from murphy.models import WebsiteAnalysis


def write_features_markdown(analysis: WebsiteAnalysis, output_dir: Path) -> Path:
	"""Write a clean markdown file listing all discovered features."""
	domain = urlparse(analysis.key_pages[0].url).netloc if analysis.key_pages else analysis.site_name
	slug = domain.replace('.', '_').replace(':', '_')
	path = output_dir / f'{slug}_features.md'

	lines: list[str] = []
	lines.append(f'# {analysis.site_name}')
	lines.append(f'**Category:** {analysis.category}  ')
	lines.append(f'**Description:** {analysis.description}\n')

	# ── Pages ──
	lines.append('## Pages discovered\n')
	lines.append('| Page | Type | Purpose |')
	lines.append('|------|------|---------|')
	for page in analysis.key_pages:
		lines.append(f'| [{page.title}]({page.url}) | `{page.page_type}` | {page.purpose} |')

	# ── Features by importance ──
	lines.append('\n## Features\n')
	for importance in ('core', 'secondary', 'peripheral'):
		features = [f for f in analysis.features if f.importance == importance]
		if not features:
			continue
		lines.append(f'### {importance.capitalize()}\n')
		for feat in features:
			testability_badge = {'testable': 'testable', 'partial': 'partial', 'untestable': 'untestable'}[feat.testability]
			lines.append(f'- **{feat.name}** (`{feat.category}`, {testability_badge})')
			lines.append(f'  {feat.description}')
			if feat.elements:
				lines.append(f'  Elements: {", ".join(feat.elements)}')
			if feat.testability_reason:
				lines.append(f'  _{feat.testability_reason}_')
			lines.append(f'  Page: {feat.page_url}\n')

	# ── User flows ──
	if analysis.identified_user_flows:
		lines.append('## Identified user flows\n')
		for flow in analysis.identified_user_flows:
			lines.append(f'1. {flow}')

	path.write_text('\n'.join(lines) + '\n')
	return path


def read_features_markdown(path: Path) -> WebsiteAnalysis:
	"""Parse a features markdown file back into a WebsiteAnalysis."""
	from murphy.models import Feature, PageInfo, WebsiteAnalysis

	text = path.read_text()
	lines = text.split('\n')

	# ── Header ──
	site_name = ''
	category = ''
	description = ''
	for line in lines:
		if line.startswith('# ') and not line.startswith('## '):
			site_name = line[2:].strip()
		elif line.startswith('**Category:**'):
			category = line.replace('**Category:**', '').strip().rstrip('  ')
		elif line.startswith('**Description:**'):
			description = line.replace('**Description:**', '').strip()

	# ── Pages table ──
	key_pages: list[PageInfo] = []
	in_pages_table = False
	for line in lines:
		if line.startswith('## Pages discovered'):
			in_pages_table = True
			continue
		if in_pages_table and line.startswith('## '):
			break
		if in_pages_table and line.startswith('|') and not line.startswith('|---') and not line.startswith('| Page'):
			# | [Title](url) | `type` | Purpose |
			cells = [c.strip() for c in line.split('|')[1:-1]]
			if len(cells) >= 3:
				link_match = re.match(r'\[(.+?)\]\((.+?)\)', cells[0])
				title = link_match.group(1) if link_match else cells[0]
				url = link_match.group(2) if link_match else ''
				page_type = cells[1].strip('`').strip()
				purpose = cells[2]
				# Validate page_type, fall back to 'other'
				valid_types = (
					'homepage',
					'landing',
					'product',
					'listing',
					'detail',
					'form',
					'content',
					'dashboard',
					'auth',
					'error',
					'other',
				)
				if page_type not in valid_types:
					page_type = 'other'
				key_pages.append(
					PageInfo(
						url=url,
						title=title,
						purpose=purpose,
						page_type=page_type,
						interactive_elements=[],  # type: ignore[arg-type]
					)
				)

	# ── Features ──
	features: list[Feature] = []
	current_importance: str = 'core'
	i = 0
	while i < len(lines):
		line = lines[i]

		# Track importance sections
		if line.startswith('### Core'):
			current_importance = 'core'
		elif line.startswith('### Secondary'):
			current_importance = 'secondary'
		elif line.startswith('### Peripheral'):
			current_importance = 'peripheral'

		# Feature entry: - **Name** (`category`, testability)
		feat_match = re.match(r'^- \*\*(.+?)\*\* \(`(.+?)`,\s*(testable|partial|untestable)\)', line)
		if feat_match:
			name = feat_match.group(1)
			feat_category = feat_match.group(2)
			testability = feat_match.group(3)

			# Valid categories
			valid_cats = (
				'navigation',
				'search',
				'forms',
				'content_display',
				'filtering_sorting',
				'media',
				'authentication',
				'ecommerce',
				'social',
				'other',
			)
			if feat_category not in valid_cats:
				feat_category = 'other'

			feat_description = ''
			elements: list[str] = []
			testability_reason: str | None = None
			page_url = ''

			# Read continuation lines (indented with 2 spaces)
			j = i + 1
			while j < len(lines) and lines[j].startswith('  ') and not lines[j].startswith('- **'):
				cont = lines[j].strip()
				if cont.startswith('Elements:'):
					elements = [e.strip() for e in cont[len('Elements:') :].split(',')]
				elif cont.startswith('Page:'):
					page_url = cont[len('Page:') :].strip()
				elif cont.startswith('_') and cont.endswith('_'):
					testability_reason = cont.strip('_')
				elif cont and not feat_description:
					feat_description = cont
				j += 1

			features.append(
				Feature(
					name=name,
					category=feat_category,  # type: ignore[arg-type]
					description=feat_description,
					page_url=page_url,
					elements=elements,
					testability=testability,  # type: ignore[arg-type]
					testability_reason=testability_reason,
					importance=current_importance,  # type: ignore[arg-type]
				)
			)
			i = j
			continue

		i += 1

	# ── User flows ──
	user_flows: list[str] = []
	in_flows = False
	for line in lines:
		if line.startswith('## Identified user flows'):
			in_flows = True
			continue
		if in_flows and line.startswith('## '):
			break
		if in_flows and re.match(r'^\d+\.\s+', line):
			user_flows.append(re.sub(r'^\d+\.\s+', '', line).strip())

	return WebsiteAnalysis(
		site_name=site_name,
		category=category,
		description=description,
		key_pages=key_pages,
		features=features,
		identified_user_flows=user_flows,
	)
