from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_admin_session, get_notification_service
from app.schemas.notifications import (
    AdminNotificationCreateRequest,
    AdminNotificationDeleteResponse,
    AdminNotificationListResponse,
    NotificationItem,
)
from app.services.notification_service import NotificationService
from app.services.token_store import SessionRecord

router = APIRouter(prefix='/admin/notifications', tags=['admin-notifications'])


@router.get('', response_model=AdminNotificationListResponse)
async def list_admin_notifications(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _current_session: SessionRecord = Depends(get_current_admin_session),
    notification_service: NotificationService = Depends(get_notification_service),
):
    try:
        return await run_in_threadpool(
            notification_service.list_admin_notifications,
            limit=limit,
            offset=offset,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post('', response_model=NotificationItem)
async def create_admin_notification(
    payload: AdminNotificationCreateRequest,
    current_session: SessionRecord = Depends(get_current_admin_session),
    notification_service: NotificationService = Depends(get_notification_service),
):
    try:
        return await run_in_threadpool(
            notification_service.create_admin_notification,
            title=payload.title,
            content=payload.content,
            notification_type=payload.type,
            scope=payload.scope,
            sender_username=current_session.username,
            recipient_username=payload.recipient_username,
            related_type=payload.related_type,
            related_id=payload.related_id,
            expires_at=payload.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.delete('/{notification_id}', response_model=AdminNotificationDeleteResponse)
async def delete_admin_notification(
    notification_id: int,
    _current_session: SessionRecord = Depends(get_current_admin_session),
    notification_service: NotificationService = Depends(get_notification_service),
):
    try:
        return await run_in_threadpool(notification_service.delete_admin_notification, notification_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
