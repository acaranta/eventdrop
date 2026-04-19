from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from eventdrop.database.models import Event
from eventdrop.database.session import get_db
from eventdrop.services.archive_service import get_archive_by_token, get_archives_by_batch_id
from eventdrop.templating import templates
from eventdrop.utils.context import build_ctx

router = APIRouter(tags=["downloads"])


@router.get("/downloads/batch/{batch_id}", response_class=HTMLResponse)
async def download_batch_status_page(batch_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    archives = await get_archives_by_batch_id(db, batch_id)
    if not archives:
        raise HTTPException(status_code=404, detail="Batch not found")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    event = await db.get(Event, archives[0].event_id)
    event_name = event.name if event else ""
    return templates.TemplateResponse(request, "downloads/batch_status.html", await build_ctx(
        request, None,
        archives=archives,
        event_name=event_name,
        batch_id=batch_id,
        now=now,
        poll_url=f"/api/downloads/batch/{batch_id}/status",
    ))


@router.get("/downloads/{token}", response_class=HTMLResponse)
async def download_status_page(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    archive = await get_archive_by_token(db, token)
    if not archive:
        raise HTTPException(status_code=404, detail="Download link not found")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expired = archive.expires_at < now
    event = await db.get(Event, archive.event_id)
    event_name = event.name if event else ""
    return templates.TemplateResponse(request, "downloads/status.html", await build_ctx(
        request, None,
        archive=archive,
        expired=expired,
        event_name=event_name,
        poll_url=f"/api/downloads/{token}/status",
        file_url=f"/api/downloads/{token}/file",
    ))
