"""프롬프트 버전과 내용 지문 이력.

프롬프트 파일을 바꾸면 PROMPT_VERSION을 올리고 PROMPT_HISTORY 끝에 새 지문을 추가한다.
테스트가 현재 파일의 지문과 이 값을 대조한다. 이전 항목은 지우지 않는다.
"""

from collections.abc import Mapping
from types import MappingProxyType

PROMPT_HISTORY: Mapping[str, str] = MappingProxyType(
    {
        "risk-interpret-v1": "9eb92e6eaf572cd2c94a80570c411a78c6f8a163fb055c9a4c2ad0f0050054e2",
    }
)
PROMPT_VERSION = "risk-interpret-v1"
PROMPT_SHA256 = PROMPT_HISTORY[PROMPT_VERSION]
