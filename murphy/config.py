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

"""Murphy — shared constants and configuration."""

import os

from dotenv import load_dotenv

load_dotenv()

# ─── Pipeline defaults ────────────────────────────────────────────────────────

DEFAULT_MAX_STEPS = 30
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

JOB_TIMEOUT_ANALYZE = 300  # 5 min — single browser exploration
JOB_TIMEOUT_GENERATE_PLAN = 180  # 3 min — pure LLM, no browser
JOB_TIMEOUT_EXECUTE = 1800  # 30 min — runs multiple tests (160-621s each)
JOB_TIMEOUT_EVALUATE = 600  # 10 min — exploration + plan synthesis

# ─── REST API configuration ───────────────────────────────────────────────────

MURPHY_API_KEY = os.environ.get('MURPHY_API_KEY', '')
MURPHY_MAX_CONCURRENT_JOBS = int(os.environ.get('MURPHY_MAX_CONCURRENT_JOBS', '2'))
MURPHY_JOB_TIMEOUT_OVERRIDE = os.environ.get('MURPHY_JOB_TIMEOUT_OVERRIDE')
MURPHY_REQUEST_TIMEOUT = int(os.environ.get('MURPHY_REQUEST_TIMEOUT', '1800'))
MURPHY_API_HOST = os.environ.get('MURPHY_API_HOST', '0.0.0.0')
MURPHY_API_PORT = int(os.environ.get('MURPHY_API_PORT', '8000'))
SEMAPHORE_ACQUIRE_TIMEOUT = 30

# ─── PostHog integration ─────────────────────────────────────────────────────

POSTHOG_API_KEY = os.environ.get('POSTHOG_API_KEY', '')
POSTHOG_PROJECT_ID = os.environ.get('POSTHOG_PROJECT_ID', '')
POSTHOG_HOST = os.environ.get('POSTHOG_HOST', 'https://eu.posthog.com')

# ─── Persona pipeline defaults ──────────────────────────────────────────────

PERSONA_DISCOVERY_SESSIONS = int(os.environ.get('PERSONA_DISCOVERY_SESSIONS', '200'))
PERSONA_SCORING_SESSIONS = int(os.environ.get('PERSONA_SCORING_SESSIONS', '500'))
# Minimum event count per session when sampling from PostHog for the persona pipeline
PERSONA_MIN_EVENTS = int(os.environ.get('PERSONA_MIN_EVENTS', '100'))
PERSONA_LLM_CONCURRENCY = int(os.environ.get('PERSONA_LLM_CONCURRENCY', '15'))
PERSONA_MONTHS_BACK = int(os.environ.get('PERSONA_MONTHS_BACK', '2'))
PERSONA_MAX_CLUSTERS = int(os.environ.get('PERSONA_MAX_CLUSTERS', '10'))
# Fixed K for K-Means in the persona pipeline; ``0`` = auto-select via silhouette
PERSONA_NUM_CLUSTERS = int(os.environ.get('PERSONA_NUM_CLUSTERS', '8'))

# ─── Embedding model ─────────────────────────────────────────────────────────

EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'Qwen/Qwen3-Embedding-0.6B')
EMBEDDING_DEVICE = os.environ.get('EMBEDDING_DEVICE', 'cpu')
