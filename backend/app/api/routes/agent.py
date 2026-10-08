from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_session_with_emp_id, get_dev_agent_service
from app.schemas.agent import (
    AgentChatRequest,
    AgentChatRunResponse,
    AgentChatStartResponse,
    AgentConfigCreateRequest,
    AgentConfigDeleteResponse,
    AgentConfigListResponse,
    AgentConfigResponse,
    AgentConfigUpdateRequest,
)
from app.services.dev_agent_service import DevAgentService
from app.services.token_store import SessionRecord

router = APIRouter(prefix='/agent', tags=['agent'])


def _config_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.get('/settings', response_model=AgentConfigListResponse)
async def list_agent_settings(
    current_session: SessionRecord = Depends(get_current_session_with_emp_id),
    dev_agent_service: DevAgentService = Depends(get_dev_agent_service),
):
    try:
        configs = await run_in_threadpool(dev_agent_service.list_settings, current_session.username)
        return {'configs': configs}
    except RuntimeError as exc:
        raise _config_error(exc) from exc


@router.post('/settings', response_model=AgentConfigResponse)
async def create_agent_settings(
    payload: AgentConfigCreateRequest,
    current_session: SessionRecord = Depends(get_current_session_with_emp_id),
    dev_agent_service: DevAgentService = Depends(get_dev_agent_service),
):
    try:
        return await run_in_threadpool(
            dev_agent_service.create_settings,
            username=current_session.username,
            api_base=payload.api_base,
            model_name=payload.model_name,
            api_key=payload.api_key,
        )
    except (ValueError, RuntimeError) as exc:
        raise _config_error(exc) from exc


@router.put('/settings/{config_id}', response_model=AgentConfigResponse)
async def update_agent_settings(
    config_id: int,
    payload: AgentConfigUpdateRequest,
    current_session: SessionRecord = Depends(get_current_session_with_emp_id),
    dev_agent_service: DevAgentService = Depends(get_dev_agent_service),
):
    try:
        return await run_in_threadpool(
            dev_agent_service.update_settings,
            username=current_session.username,
            config_id=config_id,
            api_base=payload.api_base,
            model_name=payload.model_name,
            api_key=payload.api_key,
        )
    except (ValueError, RuntimeError) as exc:
        raise _config_error(exc) from exc


@router.delete('/settings/{config_id}', response_model=AgentConfigDeleteResponse)
async def delete_agent_settings(
    config_id: int,
    current_session: SessionRecord = Depends(get_current_session_with_emp_id),
    dev_agent_service: DevAgentService = Depends(get_dev_agent_service),
):
    try:
        await run_in_threadpool(
            dev_agent_service.delete_settings,
            username=current_session.username,
            config_id=config_id,
        )
        return {'ok': True}
    except (ValueError, RuntimeError) as exc:
        raise _config_error(exc) from exc


@router.post('/chat', response_model=AgentChatStartResponse)
async def chat_with_agent(
    payload: AgentChatRequest,
    current_session: SessionRecord = Depends(get_current_session_with_emp_id),
    dev_agent_service: DevAgentService = Depends(get_dev_agent_service),
):
    try:
        run_id = await run_in_threadpool(
            dev_agent_service.start_chat,
            emp_id=current_session.emp_id,
            username=current_session.username,
            pod_name=payload.pod_name,
            message=payload.message,
            history=[item.model_dump() for item in payload.history],
            config_id=payload.config_id,
        )
        return {'run_id': run_id}
    except (ValueError, FileNotFoundError, PermissionError, RuntimeError) as exc:
        raise _config_error(exc) from exc


@router.get('/runs/{run_id}', response_model=AgentChatRunResponse)
async def get_agent_run(
    run_id: str,
    current_session: SessionRecord = Depends(get_current_session_with_emp_id),
    dev_agent_service: DevAgentService = Depends(get_dev_agent_service),
):
    try:
        return await run_in_threadpool(
            dev_agent_service.get_chat_run,
            username=current_session.username,
            run_id=run_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _config_error(exc) from exc
