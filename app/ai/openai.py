"""OpenAI Responses wire format over the existing bounded REST transport.

Only transport/deadlines/attempt accounting are inherited; no Google endpoint,
credentials, request format or response parser are used by this adapter.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.client import LlmError, LlmErrorKind, LlmRequest, LlmResult, LlmUsage
from app.ai.gemini import GeminiClient

OPENAI_PROVIDER = "openai"


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class OutputPart(_Model):
    type: str
    text: str | None = None


class OutputItem(_Model):
    type: str
    content: list[OutputPart] = Field(default_factory=list)


class Usage(_Model):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class Response(_Model):
    status: str
    output: list[OutputItem] = Field(default_factory=list)
    usage: Usage | None = None


class OpenAIClient(GeminiClient):
    @property
    def provider(self) -> str:
        return OPENAI_PROVIDER

    def _url(self) -> str:
        return "https://api.openai.com/v1/responses"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": "Bearer " + api_key}

    def _http_failure(self, response: httpx.Response) -> LlmErrorKind:
        if response.status_code == 429:
            try:
                error = response.json().get("error", {})
                if error.get("code") == "insufficient_quota":
                    return LlmErrorKind.QUOTA_EXHAUSTED
            except (ValueError, AttributeError):
                pass
        return super()._http_failure(response)

    def _body(self, request: LlmRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "instructions": request.system_instruction,
            "input": request.user_content,
            "store": False,
            "max_output_tokens": request.max_output_tokens or self._max_output_tokens,
        }
        if request.response_json_schema is not None:
            # Make an independent JSON tree; all strict-schema arrays need items.
            schema = json.loads(json.dumps(dict(request.response_json_schema)))

            def normalize(value: Any) -> None:
                if isinstance(value, dict):
                    if value.get("type") == "array":
                        value.setdefault("items", {"type": "string"})
                    for child in value.values():
                        normalize(child)
                elif isinstance(value, list):
                    for child in value:
                        normalize(child)

            normalize(schema)
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "spoton_interpretation",
                    "strict": True,
                    "schema": schema,
                }
            }
        return body

    def _parse(self, content: bytes, attempts: int) -> LlmResult:
        payload = None
        try:
            payload = Response.model_validate_json(content)
        except ValidationError:
            pass
        if payload is None:
            raise LlmError(LlmErrorKind.MALFORMED_RESPONSE)
        if payload.status == "incomplete":
            raise LlmError(LlmErrorKind.INCOMPLETE)
        if payload.status != "completed":
            raise LlmError(LlmErrorKind.UPSTREAM)
        parts = [part for item in payload.output if item.type == "message" for part in item.content]
        if any(part.type == "refusal" for part in parts):
            raise LlmError(LlmErrorKind.BLOCKED)
        output = "".join(part.text or "" for part in parts if part.type == "output_text")
        if not output.strip():
            raise LlmError(LlmErrorKind.MALFORMED_RESPONSE)
        usage = payload.usage or Usage()
        return LlmResult(
            text=output,
            provider=self.provider,
            model=self._model,
            attempts=attempts,
            usage=LlmUsage(
                prompt_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
            ),
        )
