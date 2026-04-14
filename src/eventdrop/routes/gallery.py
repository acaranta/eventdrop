from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pathlib import Path

from eventdrop.database.session import get_db
from eventdrop.database.models import Event, MediaFile
from eventdrop.services.media_service import list_event_media
from eventdrop.storage import get_storage
from eventdrop.config import settings

router = APIRouter(tags=["gallery"])
BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/e/{event_id}/gallery/", response_class=HTMLResponse)
async def gallery_page(event_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    from eventdrop.auth.dependencies import get_current_user_optional
    auth_user = await get_current_user_optional(request, db)

    result = await db.execute(
        select(Event)
        .options(selectinload(Event.owner))
        .where(Event.id == event_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404)

    # Access control
    is_owner = auth_user and (str(auth_user.id) == str(event.owner_id) or auth_user.is_admin)
    if not event.is_gallery_public and not is_owner:
        if not auth_user:
            raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
        raise HTTPException(status_code=403, detail="Gallery is private")

    media_files = await list_event_media(db, event_id)
    storage = get_storage()

    media_with_urls = []
    for mf in media_files:
        url = await storage.get_url(mf.stored_path)
        thumb_url = await storage.get_url(mf.thumb_path) if mf.thumb_path else url
        media_with_urls.append({
            "id": str(mf.id),
            "url": url,
            "thumb_url": thumb_url,
            "filename": mf.original_filename,
            "mime_type": mf.mime_type,
            "size": mf.file_size,
            "uploaded_at": mf.uploaded_at.isoformat() if mf.uploaded_at else None,
            "file_datetime": mf.file_datetime.isoformat() if mf.file_datetime else None,
            "source": mf.source,
            "uploader_email": mf.uploader_email,
        })

    return templates.TemplateResponse(request, "gallery/gallery.html", {
        "user": auth_user,
        "settings": settings,
        "event": event,
        "media_with_urls": media_with_urls,
        "is_owner": is_owner,
        "can_download": event.allow_public_download or bool(is_owner),
        "can_delete": bool(is_owner),
    })
