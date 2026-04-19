from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from eventdrop.database.session import get_db
from eventdrop.services.archive_service import get_archive_by_token
from eventdrop.templating import templates
from eventdrop.utils.context import build_ctx

router = APIRouter(tags=["downloads"])


@router.get("/downloads/{token}", response_class=HTMLResponse)
async def download_status_page(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    archive = await get_archive_by_token(db, token)
    if not archive:
        raise HTTPException(status_code=404, detail="Download link not found")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expired = archive.expires_at < now
    return templates.TemplateResponse(request, "downloads/status.html", await build_ctx(
        request, None,
        archive=archive,
        expired=expired,
        poll_url=f"/api/downloads/{token}/status",
        file_url=f"/api/downloads/{token}/file",
    ))
