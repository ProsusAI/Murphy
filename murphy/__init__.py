"""Murphy — AI-driven website evaluation powered by browser-use."""

__version__ = '1.1.3'

from murphy.core.analysis import analyze_website as analyze_website
from murphy.core.execution import execute_tests as execute_tests
from murphy.core.execution import execute_tests_with_session as execute_tests_with_session
from murphy.core.generation import explore_and_generate_plan as explore_and_generate_plan
from murphy.core.generation import generate_tests as generate_tests
from murphy.core.judge import murphy_judge as murphy_judge
from murphy.core.summary import build_summary as build_summary
from murphy.core.summary import classify_failure as classify_failure
from murphy.models import JudgeVerdict as JudgeVerdict
