import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.exception_handlers import register_exception_handlers
from app.core.middleware import UnhandledErrorMiddleware
from app.db.dependencies import DatabaseResources
from app.routers.geocode import router as geocode_router
from app.routers.health import router as health_router
from app.routers.market import router as market_router
from app.routers.meta import router as meta_router
from app.routers.nearby import router as nearby_router
from app.routers.risk import router as risk_router
from app.routers.snapshot import router as snapshot_router
from app.routers.stores import router as stores_router
from app.routers.support import router as support_router


def configure_sensitive_request_logging() -> None:
    """Keep third-party request URLs, including address query strings, out of logs."""
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else get_settings()
    configure_sensitive_request_logging()
    resources = DatabaseResources(config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            resources.close()

    application = FastAPI(title="Spot:ON BE", version="0.1.0", debug=False, lifespan=lifespan)
    application.state.settings = config
    application.state.database = resources
    register_exception_handlers(application)
    # 나중에 추가되는 CORS가 바깥에서 정상 응답과 미처리 오류 응답을 함께 감싼다.
    application.add_middleware(UnhandledErrorMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.include_router(health_router, prefix="/api")
    application.include_router(geocode_router, prefix="/api")
    application.include_router(stores_router, prefix="/api")
    application.include_router(nearby_router, prefix="/api")
    application.include_router(snapshot_router, prefix="/api")
    application.include_router(meta_router, prefix="/api")
    application.include_router(market_router, prefix="/api")
    application.include_router(risk_router, prefix="/api")
    application.include_router(support_router, prefix="/api")
    return application


app = create_app()
