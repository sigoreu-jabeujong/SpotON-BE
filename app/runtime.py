"""Container entry point; create server workers without opening a DB in the parent."""

import os

import uvicorn

from app.core.config import Settings


def main() -> None:
    settings = Settings()
    raw_port = os.environ.get("PORT", "10000")
    if not raw_port.isascii() or not raw_port.isdecimal() or not 1 <= int(raw_port) <= 65535:
        raise ValueError("PORT에는 1~65535 정수를 지정하세요")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(raw_port),
        workers=settings.web_concurrency,
        access_log=False,
        timeout_graceful_shutdown=30,
    )


if __name__ == "__main__":
    main()
