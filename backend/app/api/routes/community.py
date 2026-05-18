from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_session, get_publication_service
from app.schemas.community import PublishedAppItem, PublishedAppListResponse
from app.services.publication_service import PublicationService
from app.services.token_store import SessionRecord

router = APIRouter(prefix='/community', tags=['community'])


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
    cover: UploadFile | None = File(default=None),
    current_session: SessionRecord = Depends(get_current_session),
    publication_service: PublicationService = Depends(get_publication_service),
):
    try:
        return await run_in_threadpool(
            publication_service.publish_app,
            pod_name=pod_name,
            app_description=app_description,
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
