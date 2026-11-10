"""생성 → 검증 → 1회 재생성 → AI_VERIFY_FAILED (작업계획 8절, BE-31).

공급자 오류(LlmError)는 잡지 않고 그대로 올린다. 호출자가 AI_UNAVAILABLE로 매핑한다.
재생성은 같은 요청을 그대로 보낸다. 문장을 덧붙이면 BE-30 버전 관리 밖의 프롬프트가 생긴다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel, JsonValue

from app.ai.client import LlmClient, LlmRequest, LlmResult
from app.ai.verifier import VerifyFailure, VerifyPolicy, VerifyResult, verify_output
from app.core.errors import AppError
from app.schemas.common import ErrorCode

MAX_GENERATIONS = 2


class AiVerifyFailedError(Exception):
    """재생성 후에도 검증에 실패함. 실패 종류만 담는다."""

    def __init__(self, failures: tuple[VerifyFailure, ...]) -> None:
        self.failures = failures
        super().__init__(",".join(kind.value for kind in failures))

    def __repr__(self) -> str:
        return f"AiVerifyFailedError({[kind.value for kind in self.failures]!r})"

    def to_app_error(self) -> AppError:
        return AppError(ErrorCode.AI_VERIFY_FAILED)


@dataclass(frozen=True)
class VerifiedOutput:
    result: LlmResult
    data: dict[str, JsonValue] = field(repr=False)
    generations: int


async def generate_verified(
    client: LlmClient,
    request: LlmRequest,
    *,
    context: Mapping[str, JsonValue],
    response_model: type[BaseModel] | None = None,
    policy: VerifyPolicy | None = None,
) -> VerifiedOutput:
    verdict: VerifyResult | None = None
    for generation in range(1, MAX_GENERATIONS + 1):
        result = await client.generate(request)
        verdict = verify_output(
            result.text, context=context, response_model=response_model, policy=policy
        )
        if verdict.ok and verdict.data is not None:
            return VerifiedOutput(result=result, data=verdict.data, generations=generation)
    assert verdict is not None
    raise AiVerifyFailedError(verdict.failures)
