from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_session, get_notification_event_bus, get_notification_service
from app.schemas.notifications import (
    NotificationActionResponse,
    NotificationListResponse,
    NotificationUnreadCountResponse,
)
from app.services.notification_event_bus import NotificationEventBus
from app.services.notification_service import NotificationService
from app.services.token_store import SessionRecord

router = APIRouter(prefix='/notifications', tags=['notifications'])
SSE_HEARTBEAT_SECONDS = 25


@router.get('', response_model=NotificationListResponse)
async def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_session: SessionRecord = Depends(get_current_session),
    notification_service: NotificationService = Depends(get_notification_service),
):
    try:
        return await run_in_threadpool(
            notification_service.list_user_notifications,
            session=current_session,
            unread_only=unread_only,
            limit=limit,
            offset=offset,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get('/unread-count', response_model=NotificationUnreadCountResponse)
async def get_unread_count(
    current_session: SessionRecord = Depends(get_current_session),
    notification_service: NotificationService = Depends(get_notification_service),
):
    try:
        return await run_in_threadpool(notification_service.get_unread_count, current_session)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post('/read-all', response_model=NotificationActionResponse)
async def mark_all_notifications_read(
    current_session: SessionRecord = Depends(get_current_session),
    notification_service: NotificationService = Depends(get_notification_service),
):
    try:
        return await run_in_threadpool(notification_service.mark_all_read, current_session)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get('/events')
async def notification_events(
    request: Request,
    current_session: SessionRecord = Depends(get_current_session),
    notification_service: NotificationService = Depends(get_notification_service),
    event_bus: NotificationEventBus = Depends(get_notification_event_bus),
):
    async def event_stream():
        subscriber_id, queue = event_bus.subscribe(current_session.username)
        try:
            unread = await run_in_threadpool(notification_service.get_unread_count, current_session)
            yield _format_sse(
                event='notification.changed',
                data={'type': 'notification.changed', 'unread_count': unread['unread_count']},
            )
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ': heartbeat\n\n'
                    continue

                unread = await run_in_threadpool(notification_service.get_unread_count, current_session)
                payload = {
                    **event.payload,
                    'unread_count': unread['unread_count'],
                }
                yield _format_sse(event='notification.changed', data=payload, event_id=str(event.id))
        finally:
            event_bus.unsubscribe(subscriber_id)

    return StreamingResponse(
        event_stream(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )


@router.post('/{notification_id}/read', response_model=NotificationActionResponse)
async def mark_notification_read(
    notification_id: int,
    current_session: SessionRecord = Depends(get_current_session),
    notification_service: NotificationService = Depends(get_notification_service),
):
    try:
        return await run_in_threadpool(notification_service.mark_read, notification_id, current_session)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post('/{notification_id}/dismiss', response_model=NotificationActionResponse)
async def dismiss_notification(
    notification_id: int,
    current_session: SessionRecord = Depends(get_current_session),
    notification_service: NotificationService = Depends(get_notification_service),
):
    try:
        return await run_in_threadpool(notification_service.dismiss, notification_id, current_session)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _format_sse(*, event: str, data: dict, event_id: str | None = None) -> str:
    lines = []
    if event_id:
        lines.append(f'id: {event_id}')
    lines.append(f'event: {event}')
    lines.append(f'data: {json.dumps(data, ensure_ascii=False)}')
    return '\n'.join(lines) + '\n\n'
