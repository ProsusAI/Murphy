"""Murphy — shared constants and configuration."""

import os

from dotenv import load_dotenv

load_dotenv()

# ─── Pipeline defaults ────────────────────────────────────────────────────────

DEFAULT_MAX_STEPS = 30
DEFAULT_MAX_TESTS = 8
DEFAULT_MAX_ACTIONS_PER_STEP = 3
QUALITY_MAX_RETRIES = 2

# Hard cap on parallel browser sessions to avoid resource exhaustion
MAX_PARALLEL_SESSIONS = 5

# Exploration agent step limit (capped below DEFAULT_MAX_STEPS for speed)
EXPLORE_MAX_STEPS = 14

# Execution agent step limit per test scenario
EXECUTION_MAX_STEPS = 15

# UI readiness thresholds for session stabilization
UI_READY_MIN_INTERACTIVE = 3
UI_READY_MIN_TEXT_LENGTH = 120

# ─── Per-endpoint job timeouts (seconds) ──────────────────────────────────────

JOB_TIMEOUT_ANALYZE = 3600  # 60 min
JOB_TIMEOUT_GENERATE_PLAN = 3600  # 60 min
JOB_TIMEOUT_EXECUTE = 3600  # 60 min
JOB_TIMEOUT_EVALUATE = 3600  # 60 min

# ─── Vercel Blob Storage ──────────────────────────────────────────────────────

BLOB_READ_WRITE_TOKEN = os.environ.get('BLOB_READ_WRITE_TOKEN', '')
# Path within the blob store where feedback JSONL is written.
# Set BLOB_FEEDBACK_PATH in the environment to override the default.
# The blob is uploaded with access='private' — requires a signed URL to read.
BLOB_FEEDBACK_PATH = os.environ.get('BLOB_FEEDBACK_PATH', 'feedback/news/feedback.jsonl')

# ─── REST API configuration ───────────────────────────────────────────────────

MURPHY_API_KEY = os.environ.get('MURPHY_API_KEY', '')
MURPHY_MAX_CONCURRENT_JOBS = int(os.environ.get('MURPHY_MAX_CONCURRENT_JOBS', '2'))
MURPHY_JOB_TIMEOUT_OVERRIDE = os.environ.get('MURPHY_JOB_TIMEOUT_OVERRIDE')
MURPHY_REQUEST_TIMEOUT = int(os.environ.get('MURPHY_REQUEST_TIMEOUT', '3600'))
MURPHY_API_HOST = os.environ.get('MURPHY_API_HOST', '0.0.0.0')
MURPHY_API_PORT = int(os.environ.get('MURPHY_API_PORT', '8000'))
SEMAPHORE_ACQUIRE_TIMEOUT = 30
