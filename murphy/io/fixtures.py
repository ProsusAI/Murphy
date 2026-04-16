"""Dummy fixture files for upload scenario testing."""

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / 'fixture_data'
DUMMY_FILE_PATH = FIXTURES_DIR / 'dummy.txt'
DUMMY_CSV_PATH = FIXTURES_DIR / 'dummy.csv'
DUMMY_PDF_PATH = FIXTURES_DIR / 'dummy.pdf'
DUMMY_EXE_PATH = FIXTURES_DIR / 'dummy.exe'
DUMMY_DOCX_PATH = FIXTURES_DIR / 'dummy.docx'
STARTUP_HANDBOOK_PATH = FIXTURES_DIR / 'startup_handbook.pdf'


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
	paths = [DUMMY_FILE_PATH, DUMMY_CSV_PATH, DUMMY_PDF_PATH, DUMMY_EXE_PATH, DUMMY_DOCX_PATH]
	if STARTUP_HANDBOOK_PATH.exists():
		paths.append(STARTUP_HANDBOOK_PATH)
	return paths
