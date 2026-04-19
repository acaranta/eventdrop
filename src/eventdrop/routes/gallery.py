from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.sql.functions import coalesce
from sqlalchemy.orm import selectinload
from typing import Optional

from eventdrop.database.session import get_db
from eventdrop.database.models import Event, MediaFile
from eventdrop.storage import get_storage
from eventdrop.config import settings
from eventdrop.utils.context import build_ctx
from eventdrop.templating import templates
from eventdrop.services.media_service import email_hash

router = APIRouter(tags=["gallery"])


@router.get("/e/{event_id}/gallery/", response_class=HTMLResponse)
async def gallery_page(
    event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    uploader_filter: Optional[str] = Query(None, alias="uploader"),
    source_filter: Optional[str] = Query(None, alias="source"),
    gps_only: Optional[str] = Query(None, alias="gps"),  # "1" to show only GPS-tagged media
    sort_by: Optional[str] = Query("exif", alias="sort"),    # exif | upload
    sort_order: Optional[str] = Query("asc", alias="order"),   # asc | desc
):
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

    # Build contributors list (always unfiltered — needed to resolve uploader hash before filtering)
    contrib_result = await db.execute(
        select(
            MediaFile.uploader_email,
            func.count(MediaFile.id).label("count")
        )
        .where(MediaFile.event_id == event_id)
        .group_by(MediaFile.uploader_email)
        .order_by(func.count(MediaFile.id).desc())
    )
    contributors = [
        {"email": row.uploader_email, "count": row.count, "hash": email_hash(row.uploader_email)}
        for row in contrib_result
    ]

    # Resolve uploader_filter (8-char hash) → actual email for DB query
    uploader_email_resolved = None
    if uploader_filter:
        match = next((c for c in contributors if c["hash"] == uploader_filter), None)
        uploader_email_resolved = match["email"] if match else None

    # Build filtered media query
    query = select(MediaFile).where(MediaFile.event_id == event_id)
    if uploader_email_resolved:
        query = query.where(MediaFile.uploader_email == uploader_email_resolved)
    if source_filter in ("upload", "email"):
        query = query.where(MediaFile.source == source_filter)
    if gps_only:
        query = query.where(MediaFile.gps_lat.isnot(None))

    # Sorting: exif uses COALESCE(file_datetime, uploaded_at); upload uses uploaded_at only
    if sort_by == "upload":
        sort_col = MediaFile.uploaded_at
    else:  # exif (default)
        sort_col = coalesce(MediaFile.file_datetime, MediaFile.uploaded_at)
    query = query.order_by(sort_col.asc() if sort_order == "asc" else sort_col.desc())
    result = await db.execute(query)
    media_files = list(result.scalars().all())

    total_media_size = sum(mf.file_size or 0 for mf in media_files)

    storage = get_storage()

    media_with_urls = []
    for mf in media_files:
        url = await storage.get_url(mf.stored_path)
        if mf.thumb_path:
            thumb_url = await storage.get_url(mf.thumb_path)
        elif mf.mime_type and mf.mime_type.startswith("video/"):
            thumb_url = None
        else:
            thumb_url = url
        show_message = (
            mf.upload_message and
            (mf.message_is_public or bool(is_owner))
        )
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
            "upload_message": mf.upload_message if show_message else None,
            "message_is_public": mf.message_is_public,
            "has_gps": mf.gps_lat is not None and mf.gps_lon is not None,
        })

    return templates.TemplateResponse(request, "gallery/gallery.html", await build_ctx(
        request, auth_user,
        event=event,
        media_with_urls=media_with_urls,
        is_owner=is_owner,
        can_download=event.allow_public_download or bool(is_owner),
        can_delete=bool(is_owner),
        contributors=contributors,
        uploader_filter=uploader_filter,
        uploader_filter_email=uploader_email_resolved,
        source_filter=source_filter,
        gps_filter=bool(gps_only),
        sort_by=sort_by if sort_by in ("exif", "upload") else "exif",
        sort_order=sort_order if sort_order in ("asc", "desc") else "asc",
        total_media_size=total_media_size,
        settings=settings,
    ))
