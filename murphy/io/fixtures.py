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

"""Dummy fixture files for upload scenario testing."""

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / 'fixture_data'
DUMMY_FILE_PATH = FIXTURES_DIR / 'dummy.txt'
DUMMY_CSV_PATH = FIXTURES_DIR / 'dummy.csv'
DUMMY_PDF_PATH = FIXTURES_DIR / 'dummy.pdf'
DUMMY_EXE_PATH = FIXTURES_DIR / 'dummy.exe'
DUMMY_DOCX_PATH = FIXTURES_DIR / 'dummy.docx'


def ensure_dummy_fixture_files() -> list[Path]:
	"""Create stable dummy upload fixtures with common file extensions."""
	FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

	if not DUMMY_FILE_PATH.exists():
		DUMMY_FILE_PATH.write_text(
			'This is a dummy fixture file for murphy upload scenarios.\n',
			encoding='utf-8',
		)
	if not DUMMY_CSV_PATH.exists():
		DUMMY_CSV_PATH.write_text(
			'id,name,role\n1,Test User,viewer\n2,Dummy User,editor\n',
			encoding='utf-8',
		)
	if not DUMMY_PDF_PATH.exists():
		DUMMY_PDF_PATH.write_bytes(b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n')
	if not DUMMY_EXE_PATH.exists():
		DUMMY_EXE_PATH.write_bytes(b'MZ\x90\x00Dummy executable fixture for upload validation only.\n')
	if not DUMMY_DOCX_PATH.exists():
		DUMMY_DOCX_PATH.write_text(
			'This is a dummy fixture file for murphy upload scenarios.\nIt can be used safely for upload-field testing.\n',
			encoding='utf-8',
		)
	return [DUMMY_FILE_PATH, DUMMY_CSV_PATH, DUMMY_PDF_PATH, DUMMY_EXE_PATH, DUMMY_DOCX_PATH]
