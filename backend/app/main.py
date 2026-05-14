from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import settings
from app.api.routes.auth import router as auth_router
from app.api.routes.sandbox import router as sandbox_router


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
            'mock_kubernetes': settings.mock_kubernetes,
        }

    application.include_router(auth_router, prefix='/api/v1')
    application.include_router(sandbox_router, prefix='/api/v1')
    return application


app = create_application()
