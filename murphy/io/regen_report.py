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

"""Quick script to regenerate markdown from existing JSON report."""

import logging
from pathlib import Path

from murphy.io.report import write_markdown_report
from murphy.models import EvaluationReport

logger = logging.getLogger(__name__)

output_dir = Path('murphy/output')
json_data = (output_dir / 'evaluation_report.json').read_text()
report = EvaluationReport.model_validate_json(json_data)
md_path = write_markdown_report(report, output_dir)
logger.info('Regenerated: %s', md_path)
