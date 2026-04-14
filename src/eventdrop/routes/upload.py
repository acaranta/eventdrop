from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from pathlib import Path

from eventdrop.database.session import get_db
from eventdrop.database.models import Event, EventEmailConfig
from eventdrop.services.media_service import (
    store_media_file, get_uploader_by_token, get_or_create_uploader_session,
    ALLOWED_MIME_TYPES
)
from eventdrop.storage import get_storage
from eventdrop.config import settings
from sqlalchemy import select
from sqlalchemy.orm import selectinload

router = APIRouter(tags=["upload"])
BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

COOKIE_NAME = "uploader_token"
MAX_UPLOAD_BYTES = settings.max_upload_size_mb * 1024 * 1024


@router.get("/e/{event_id}/")
async def upload_page(event_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Event)
        .options(selectinload(Event.email_config))
        .where(Event.id == event_id)
    )
    event = result.scalar_one_or_none()
    if not event or not event.is_active:
        raise HTTPException(status_code=404, detail="Event not found or uploads closed")

    # Get email ingestion address if configured
    email_ingestion_address = None
    if event.email_config and event.email_config.is_enabled:
        email_ingestion_address = event.email_config.email_address

    # Check uploader session from cookie
    uploader_email = None
    token = request.cookies.get(COOKIE_NAME)
    if token:
        session = await get_uploader_by_token(db, token)
        if session:
            uploader_email = session.email

    from eventdrop.auth.dependencies import get_current_user_optional
    auth_user = await get_current_user_optional(request, db)

    return templates.TemplateResponse(request, "upload/upload.html", {
        "user": auth_user,
        "settings": settings,
        "event": event,
        "uploader_email": uploader_email,
        "email_ingestion_address": email_ingestion_address,
    })


@router.post("/e/{event_id}/set-email")
async def set_uploader_email(
    event_id: str,
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    # Validate event exists
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if not event or not event.is_active:
        raise HTTPException(status_code=404)

    session = await get_or_create_uploader_session(db, email)
    await db.commit()

    response = RedirectResponse(url=f"/e/{event_id}/", status_code=303)
    response.set_cookie(COOKIE_NAME, session.token, httponly=True, samesite="lax", max_age=365 * 24 * 3600)
    return response


@router.post("/e/{event_id}/clear-email")
async def clear_uploader_email(event_id: str, request: Request):
    response = RedirectResponse(url=f"/e/{event_id}/", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.post("/api/e/{event_id}/upload")
async def upload_file(
    event_id: str,
    request: Request,
    file: UploadFile = File(...),
    upload_message: Optional[str] = Form(None),
    message_is_public: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    """Handle single file upload via AJAX."""
    # Get event
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if not event or not event.is_active:
        raise HTTPException(status_code=404, detail="Event not found or uploads closed")

    # Get uploader email from cookie session
    uploader_email = None
    token = request.cookies.get(COOKIE_NAME)
    if token:
        session = await get_uploader_by_token(db, token)
        if session:
            uploader_email = session.email

    # Also check if authenticated user — use email if set, fall back to username
    if not uploader_email:
        from eventdrop.auth.dependencies import get_current_user_optional
        auth_user = await get_current_user_optional(request, db)
        if auth_user:
            uploader_email = auth_user.email or f"{auth_user.username}@eventdrop.local"

    if not uploader_email:
        raise HTTPException(status_code=400, detail="Email required. Please set your email before uploading.")

    # Read file
    file_data = await file.read()

    # Check size
    if len(file_data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large. Max {settings.max_upload_size_mb}MB.")

    # Detect MIME type
    import magic
    mime_type = magic.from_buffer(file_data, mime=True)

    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=415, detail=f"File type '{mime_type}' not allowed.")

    storage = get_storage()
    media_file = await store_media_file(
        db=db,
        storage=storage,
        event_id=event_id,
        uploader_email=uploader_email,
        original_filename=file.filename or "upload",
        file_data=file_data,
        mime_type=mime_type,
        source="upload",
        upload_message=upload_message,
        message_is_public=message_is_public,
    )
    await db.commit()

    return JSONResponse({
        "id": str(media_file.id),
        "filename": media_file.original_filename,
        "size": media_file.file_size,
        "mime_type": media_file.mime_type,
        "status": "ok",
    })
