from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.exception_handlers import register_exception_handlers
from app.core.middleware import UnhandledErrorMiddleware
from app.routers.health import router as health_router


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else get_settings()
    application = FastAPI(title="Spot:ON BE", version="0.1.0", debug=False)
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
    return application


app = create_app()
