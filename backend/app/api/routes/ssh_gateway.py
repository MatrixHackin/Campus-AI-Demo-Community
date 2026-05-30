import contextlib

from fastapi import APIRouter, Cookie, WebSocket, WebSocketDisconnect, status
from starlette.concurrency import run_in_threadpool

from app.ssh_gateway_runtime import settings, ssh_gateway_service

router = APIRouter(prefix='/ssh', tags=['ssh'])


@router.websocket('/ws/{app_name}/{ssh_username}')
async def webssh(
    websocket: WebSocket,
    app_name: str,
    ssh_username: str,
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
):
    try:
        target = await run_in_threadpool(
            ssh_gateway_service.resolve_target,
            app_name=app_name,
            ssh_username=ssh_username,
            session_token=session_token,
        )
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    try:
        await ssh_gateway_service.bridge_websocket(websocket, target)
    except WebSocketDisconnect:
        return
    except Exception:
        with contextlib.suppress(Exception):
            await websocket.close()
