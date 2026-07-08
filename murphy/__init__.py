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

"""Murphy — AI-driven website evaluation powered by browser-use."""

__version__ = '1.1.0'

from murphy.core.analysis import analyze_website as analyze_website
from murphy.core.execution import execute_tests as execute_tests
from murphy.core.execution import execute_tests_with_session as execute_tests_with_session
from murphy.core.generation import explore_and_generate_plan as explore_and_generate_plan
from murphy.core.generation import generate_tests as generate_tests
from murphy.core.judge import murphy_judge as murphy_judge
from murphy.core.summary import build_summary as build_summary
from murphy.core.summary import classify_failure as classify_failure
from murphy.models import JudgeVerdict as JudgeVerdict
