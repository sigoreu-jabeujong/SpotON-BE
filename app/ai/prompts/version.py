"""프롬프트 버전과 내용 지문 이력.

프롬프트 파일을 바꾸면 PROMPT_VERSION을 올리고 PROMPT_HISTORY 끝에 새 지문을 추가한다.
테스트가 현재 파일의 지문과 이 값을 대조한다. 이전 항목은 지우지 않는다.
"""

from collections.abc import Mapping
from types import MappingProxyType

PROMPT_HISTORY: Mapping[str, str] = MappingProxyType(
    {
        "risk-interpret-v1": "9eb92e6eaf572cd2c94a80570c411a78c6f8a163fb055c9a4c2ad0f0050054e2",
        "risk-interpret-v2": "f4ee42541b2c5529fc677af03b0a9a4f68439efadf09c50c98b4be9889210b71",
        "risk-interpret-v3": "dfa05612994c4741d8d6c8f07357b965d9479ea5f251e9b4b4113f8f1f5d1747",
        "risk-interpret-v4": "044aba98cf36072bfb6473049b6007009e92807d33a907e8f85a45d5540d5985",
        "risk-interpret-v5": "f87b39f08a85c30e2b7e09749152eb63f02ca227fbf3c7d4d4041ffa12d8a87f",
        "risk-interpret-v6": "42407f84df7cf9049c1084a365982c8dc728df9b3427a7d4a6f8ac56ee3f3184",
        "risk-interpret-v7": "d2823664292f3c37ac819accb218ef750e17fca3103bc46eedaba3b63e9ae0c5",
        "risk-interpret-v8": "96748e3ccf6027eb885c16edfe11e2b339d809a4d6fa99cb97d98693bb93d2d0",
        "risk-interpret-v9": "a8b4162919694b58ef3834722003403136261dafb2db8c64f21929300d086dff",
    }
)
PROMPT_VERSION = "risk-interpret-v9"
PROMPT_SHA256 = PROMPT_HISTORY[PROMPT_VERSION]
