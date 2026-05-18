from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_container_usage_service, get_current_session_with_emp_id, get_k3s_service
from app.schemas.k3s import (
    AppNameAvailabilityResponse,
    ContainerCommitRequest,
    ContainerCommitResponse,
    ContainerDeleteResponse,
    ContainerListResponse,
    ContainerUsageTrendResponse,
    DevboxCreateRequest,
    DevboxCreateResponse,
    K3SJobStatusResponse,
    MyAppsUsageResponse,
)
from app.services.container_usage_service import ContainerUsageService
from app.services.k3s_service import K3SService
from app.services.token_store import SessionRecord

router = APIRouter(prefix='/k3s', tags=['k3s'])


@router.post('/devbox', response_model=DevboxCreateResponse)
async def create_devbox_container(
    payload: DevboxCreateRequest,
    current_session: SessionRecord = Depends(get_current_session_with_emp_id),
    k3s_service: K3SService = Depends(get_k3s_service),
):
    try:
        return await run_in_threadpool(
            k3s_service.create_devbox_container,
            current_session.emp_id,
            current_session.username,
            current_session.email,
            payload.app_name,
            payload.connection_password,
            payload.image,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get('/apps/check-name', response_model=AppNameAvailabilityResponse)
async def check_app_name_availability(
    app_name: str,
    _current_session: SessionRecord = Depends(get_current_session_with_emp_id),
    k3s_service: K3SService = Depends(get_k3s_service),
):
    try:
        return await run_in_threadpool(k3s_service.check_app_name_availability, app_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get('/containers', response_model=ContainerListResponse)
async def list_user_containers(
    current_session: SessionRecord = Depends(get_current_session_with_emp_id),
    k3s_service: K3SService = Depends(get_k3s_service),
):
    try:
        return await run_in_threadpool(k3s_service.list_user_containers, current_session.emp_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get('/my-apps/usage', response_model=MyAppsUsageResponse)
async def list_my_apps_usage(
    current_session: SessionRecord = Depends(get_current_session_with_emp_id),
    k3s_service: K3SService = Depends(get_k3s_service),
    container_usage_service: ContainerUsageService = Depends(get_container_usage_service),
):
    try:
        namespace = k3s_service.namespace_for_emp_id(current_session.emp_id or '')
        return await run_in_threadpool(container_usage_service.list_namespace_usage, namespace)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get('/containers/{pod_name}/usage-trend', response_model=ContainerUsageTrendResponse)
async def get_container_usage_trend(
    pod_name: str,
    current_session: SessionRecord = Depends(get_current_session_with_emp_id),
    k3s_service: K3SService = Depends(get_k3s_service),
    container_usage_service: ContainerUsageService = Depends(get_container_usage_service),
):
    try:
        namespace = k3s_service.namespace_for_emp_id(current_session.emp_id or '')
        return await run_in_threadpool(
            container_usage_service.get_pod_usage_trend,
            namespace=namespace,
            pod_name=pod_name,
            minutes=5,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.delete('/containers/{pod_name}', response_model=ContainerDeleteResponse)
async def delete_user_container(
    pod_name: str,
    current_session: SessionRecord = Depends(get_current_session_with_emp_id),
    k3s_service: K3SService = Depends(get_k3s_service),
):
    try:
        return await run_in_threadpool(
            k3s_service.delete_user_container,
            current_session.emp_id,
            current_session.username,
            pod_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post('/containers/{pod_name}/commit', response_model=ContainerCommitResponse)
async def commit_user_container(
    pod_name: str,
    payload: ContainerCommitRequest,
    current_session: SessionRecord = Depends(get_current_session_with_emp_id),
    k3s_service: K3SService = Depends(get_k3s_service),
):
    try:
        return await run_in_threadpool(
            k3s_service.commit_user_container,
            current_session.emp_id,
            current_session.username,
            current_session.email,
            pod_name,
            payload.image_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get('/jobs/{job_name}', response_model=K3SJobStatusResponse)
async def get_k3s_job_status(
    job_name: str,
    current_session: SessionRecord = Depends(get_current_session_with_emp_id),
    k3s_service: K3SService = Depends(get_k3s_service),
):
    try:
        return await run_in_threadpool(k3s_service.get_commit_job_status, current_session.emp_id, job_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
