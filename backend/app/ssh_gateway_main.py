from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.ssh_gateway import router as ssh_router
from app.ssh_gateway_runtime import settings, ssh_gateway_service


def create_application() -> FastAPI:
    application = FastAPI(
        title='Campus AI SSH Gateway',
        version='0.1.0',
        description='Campus AI SSH/WebSSH data-plane gateway',
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    @application.get('/health', tags=['system'])
    @application.get('/api/health', tags=['system'])
    def health():
        return {
            'status': 'ok',
            'environment': settings.app_env,
            'target_mode': settings.ssh_gateway_target_mode,
            'resolver_mode': settings.ssh_gateway_resolver_mode,
        }

    application.include_router(ssh_router, prefix='/api/v1')

    @application.on_event('startup')
    async def startup_ssh_gateway():
        await ssh_gateway_service.start()

    @application.on_event('shutdown')
    async def shutdown_ssh_gateway():
        await ssh_gateway_service.stop()

    return application


app = create_application()
