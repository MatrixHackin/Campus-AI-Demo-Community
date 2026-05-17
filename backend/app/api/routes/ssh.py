import contextlib

from fastapi import APIRouter, Cookie, WebSocket, WebSocketDisconnect, status

from app.api.deps import get_ssh_gateway_service, get_token_store, settings

router = APIRouter(prefix='/ssh', tags=['ssh'])


@router.websocket('/ws/{app_name}/{ssh_username}')
async def webssh(
    websocket: WebSocket,
    app_name: str,
    ssh_username: str,
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
):
    token_store = get_token_store()
    session = token_store.get_session(session_token) if session_token else None
    if not session:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    ssh_gateway_service = get_ssh_gateway_service()
    try:
        target = ssh_gateway_service.resolve_target(
            app_name=app_name,
            ssh_username=ssh_username,
            owner_username=session.username,
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
