import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.operations import API_PATHS, api_event, elapsed_ms, new_id


class OperationLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = new_id()
        start = time.monotonic()
        status = None
        complete = False

        async def observe(message: Message) -> None:
            nonlocal status, complete
            await send(message)
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                complete = True

        try:
            await self.app(scope, receive, observe)
        finally:
            path = next((known for known in API_PATHS if scope.get("path") == known), "unmatched")
            api_event(
                path=path,
                status=status,
                duration=elapsed_ms(start),
                request_id=request_id,
                complete=complete,
            )
