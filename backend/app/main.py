from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import settings, ssh_gateway_service
from app.api.routes.admin_notifications import router as admin_notifications_router
from app.api.routes.admin import router as admin_router
from app.api.routes.auth import api_router as auth_api_router, browser_router as auth_browser_router, callback_router
from app.api.routes.community import router as community_router
from app.api.routes.harbor import router as harbor_router
from app.api.routes.internal import router as internal_router
from app.api.routes.k3s import router as k3s_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.ssh import router as ssh_router
from fastapi.staticfiles import StaticFiles


def create_application() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version='0.1.0',
        description='Campus AI Community API',
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
    application.include_router(admin_router, prefix='/api/v1')
    application.include_router(admin_notifications_router, prefix='/api/v1')
    application.include_router(community_router, prefix='/api/v1')
    application.include_router(harbor_router, prefix='/api/v1')
    application.include_router(k3s_router, prefix='/api/v1')
    application.include_router(notifications_router, prefix='/api/v1')
    application.include_router(ssh_router, prefix='/api/v1')
    application.include_router(internal_router)
    application.include_router(auth_browser_router)
    application.include_router(callback_router)
    application.mount('/api/static', StaticFiles(directory='static', check_dir=False), name='api-static')

    @application.on_event('startup')
    async def startup_ssh_gateway():
        await ssh_gateway_service.start()

    @application.on_event('shutdown')
    async def shutdown_ssh_gateway():
        await ssh_gateway_service.stop()

    return application


app = create_application()
