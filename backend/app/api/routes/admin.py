from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_admin_session, get_k3s_service, get_publication_service
from app.schemas.community import (
    PublicationReviewActionRequest,
    PublicationReviewListResponse,
    PublicationReviewSettings,
    PublicationReviewSettingsUpdate,
    PublishedAppItem,
)
from app.services.publication_service import PublicationService
from app.services.k3s_service import K3SService
from app.services.token_store import SessionRecord

router = APIRouter(prefix='/admin/publication', tags=['admin-publication'])


@router.get('/settings', response_model=PublicationReviewSettings)
async def get_publication_review_settings(
    _current_session: SessionRecord = Depends(get_current_admin_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(publication_service.get_review_settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post('/access-control/reconcile')
async def reconcile_publication_access_control(
    _current_session: SessionRecord = Depends(get_current_admin_session),
    k3s_service: K3SService = Depends(get_k3s_service),
):
    try:
        return await run_in_threadpool(k3s_service.reconcile_app_access_controls)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.put('/settings', response_model=PublicationReviewSettings)
async def update_publication_review_settings(
    payload: PublicationReviewSettingsUpdate,
    current_session: SessionRecord = Depends(get_current_admin_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(
            publication_service.update_review_settings,
            review_policy=payload.review_policy,
            responsibility_ack_version=payload.responsibility_ack_version,
            session=current_session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get('/reviews', response_model=PublicationReviewListResponse)
async def list_publication_review_items(
    status_filter: str = Query(default='pending', alias='status'),
    _current_session: SessionRecord = Depends(get_current_admin_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(publication_service.list_review_items, status_filter)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post('/reviews/{publication_id}/approve', response_model=PublishedAppItem)
async def approve_publication_review(
    publication_id: int,
    payload: PublicationReviewActionRequest | None = None,
    current_session: SessionRecord = Depends(get_current_admin_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(
            publication_service.approve_publication,
            publication_id,
            current_session,
            payload.review_note if payload else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post('/reviews/{publication_id}/reject', response_model=PublishedAppItem)
async def reject_publication_review(
    publication_id: int,
    payload: PublicationReviewActionRequest,
    current_session: SessionRecord = Depends(get_current_admin_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(
            publication_service.reject_publication,
            publication_id,
            current_session,
            payload.reject_reason or '',
            payload.review_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
