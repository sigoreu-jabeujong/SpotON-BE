from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_response
from app.core.exception_handlers import log_unhandled_error
from app.schemas.common import ErrorCode


class UnhandledErrorMiddleware:
    """응답 시작 전의 예외를 CORS 안쪽에서 처리해 브라우저도 500 본문을 읽게 한다."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            if started:
                # 전송된 응답을 새 JSON으로 덮어쓰거나 중복 전송하지 않는다.
                raise
            log_unhandled_error(exc)
            response = error_response(ErrorCode.INTERNAL_ERROR)
            await response(scope, receive, send)
