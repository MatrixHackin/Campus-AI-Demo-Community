from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_session, get_publication_service
from app.schemas.community import (
    AppReviewListResponse,
    AppReviewRequest,
    PublicationStatusListResponse,
    PublicationReviewSettings,
    PublishedAppItem,
    PublishedAppListResponse,
)
from app.services.publication_service import PublicationService
from app.services.token_store import SessionRecord

router = APIRouter(prefix='/community', tags=['community'])


@router.get('/publication-settings', response_model=PublicationReviewSettings)
async def get_publication_settings(
    _current_session: SessionRecord = Depends(get_current_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(publication_service.get_review_settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get('/publication-status', response_model=PublicationStatusListResponse)
async def list_my_publication_statuses(
    pod_names: list[str] = Query(default=[]),
    current_session: SessionRecord = Depends(get_current_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(
            publication_service.list_publication_statuses,
            pod_names,
            current_session,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get('/apps', response_model=PublishedAppListResponse)
async def list_public_apps(
    current_session: SessionRecord = Depends(get_current_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(publication_service.list_public_apps, current_session)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post('/apps/{pod_name}/publish', response_model=PublishedAppItem)
async def publish_app(
    pod_name: str,
    app_description: str = Form(...),
    responsibility_ack: bool = Form(False),
    cover: UploadFile | None = File(default=None),
    current_session: SessionRecord = Depends(get_current_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(
            publication_service.publish_app,
            pod_name=pod_name,
            app_description=app_description,
            responsibility_ack=responsibility_ack,
            cover_file=cover.file if cover else None,
            cover_content_type=cover.content_type if cover else None,
            session=current_session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.delete('/apps/{pod_name}/publish', response_model=PublishedAppItem | None)
async def unpublish_app(
    pod_name: str,
    current_session: SessionRecord = Depends(get_current_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(
            publication_service.unpublish_app,
            pod_name=pod_name,
            session=current_session,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post('/apps/{publication_id}/visit', response_model=PublishedAppItem)
async def record_app_visit(
    publication_id: int,
    _current_session: SessionRecord = Depends(get_current_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(publication_service.record_visit, publication_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post('/apps/{publication_id}/like', response_model=PublishedAppItem)
async def toggle_app_like(
    publication_id: int,
    current_session: SessionRecord = Depends(get_current_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(publication_service.toggle_like, publication_id, current_session)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get('/apps/{publication_id}/reviews', response_model=AppReviewListResponse)
async def list_app_reviews(
    publication_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=50),
    sort: str = Query(default='desc', pattern='^(asc|desc)$'),
    current_session: SessionRecord = Depends(get_current_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(
            publication_service.get_reviews,
            publication_id,
            current_session,
            offset,
            limit,
            sort,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post('/apps/{publication_id}/review', response_model=AppReviewListResponse)
async def upsert_app_review(
    publication_id: int,
    payload: AppReviewRequest,
    current_session: SessionRecord = Depends(get_current_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(
            publication_service.upsert_review,
            publication_id,
            payload.rating,
            payload.comment,
            current_session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.delete('/apps/{publication_id}/review', response_model=AppReviewListResponse)
async def delete_app_review(
    publication_id: int,
    current_session: SessionRecord = Depends(get_current_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(publication_service.delete_review, publication_id, current_session)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
