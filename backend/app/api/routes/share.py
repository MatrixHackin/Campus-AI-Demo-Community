from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_publication_service
from app.services.publication_service import PublicationService

router = APIRouter(prefix='/share/apps', tags=['share'])


@router.get('/{publication_id}', response_class=HTMLResponse, include_in_schema=False)
async def share_publication(
    publication_id: int,
    publication_service: PublicationService = Depends(get_publication_service),
):
    status_code, content = await run_in_threadpool(publication_service.get_share_page, publication_id)
    return HTMLResponse(content=content, status_code=status_code)
