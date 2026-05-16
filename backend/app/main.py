from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import settings
from app.api.routes.auth import api_router as auth_api_router, browser_router as auth_browser_router, callback_router
from app.api.routes.harbor import router as harbor_router
from app.api.routes.k3s import router as k3s_router


def create_application() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version='0.1.0',
        description='Campus AI Demo Community - 分离式前后端示例',
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    @application.get('/api/health', tags=['system'])
    def health():
        return {
            'status': 'ok',
            'environment': settings.app_env,
        }

    application.include_router(auth_api_router, prefix='/api/v1')
    application.include_router(harbor_router, prefix='/api/v1')
    application.include_router(k3s_router, prefix='/api/v1')
    application.include_router(auth_browser_router)
    application.include_router(callback_router)
    return application


app = create_application()
