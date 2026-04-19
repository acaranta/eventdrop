from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from pydantic import BaseModel
import os

from eventdrop.database.session import get_db
from eventdrop.database.models import Event, MediaFile
from eventdrop.services import event_service
from eventdrop.services.media_service import delete_media_file, list_event_media, get_regen_status, regenerate_thumbnails_task
from eventdrop.services.archive_service import enqueue_archive, get_archive_by_token
from eventdrop.storage import get_storage
from eventdrop.config import settings

router = APIRouter(prefix="/api", tags=["api"])


class MediaIdsRequest(BaseModel):
    media_ids: List[str]


async def get_event_and_check_access(event_id: str, request: Request, db: AsyncSession, require_owner: bool = False):
    """Get event and check access. Returns (event, is_owner, user)."""
    from eventdrop.auth.dependencies import get_current_user_optional
    user = await get_current_user_optional(request, db)

    event = await event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    is_owner = user and (str(user.id) == str(event.owner_id) or user.is_admin)

    if require_owner and not is_owner:
        raise HTTPException(status_code=403, detail="Owner or admin access required")

    return event, is_owner, user


@router.get("/health")
async def health():
    """Health check endpoint."""
    return JSONResponse({"status": "ok"})


@router.post("/events/{event_id}/media/download")
async def bulk_download(
    event_id: str,
    body: MediaIdsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    event, is_owner, user = await get_event_and_check_access(event_id, request, db)

    if not event.allow_public_download and not is_owner:
        raise HTTPException(status_code=403, detail="Download not allowed")

    # Validate all media IDs belong to this event
    result = await db.execute(
        select(MediaFile).where(
            MediaFile.id.in_(body.media_ids),
            MediaFile.event_id == event_id,
        )
    )
    valid_ids = [str(mf.id) for mf in result.scalars().all()]
    if not valid_ids:
        raise HTTPException(status_code=400, detail="No valid media files specified")

    archive = await enqueue_archive(db, event_id, valid_ids, event.name)

    return JSONResponse({
        "token": archive.token,
        "status": "pending",
        "status_page": f"/downloads/{archive.token}",
    })


@router.post("/events/{event_id}/media/download-all")
async def bulk_download_all(
    event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    event, is_owner, user = await get_event_and_check_access(event_id, request, db)

    if not event.allow_public_download and not is_owner:
        raise HTTPException(status_code=403, detail="Download not allowed")

    media_files = await list_event_media(db, event_id)
    media_ids = [str(mf.id) for mf in media_files]

    if not media_ids:
        raise HTTPException(status_code=400, detail="No media files in this event")

    archive = await enqueue_archive(db, event_id, media_ids, event.name)

    return JSONResponse({
        "token": archive.token,
        "status": "pending",
        "status_page": f"/downloads/{archive.token}",
    })


@router.get("/downloads/{token}/status")
async def download_archive_status(token: str, db: AsyncSession = Depends(get_db)):
    from datetime import datetime, timezone
    archive = await get_archive_by_token(db, token)
    if not archive:
        raise HTTPException(status_code=404, detail="Not found")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if archive.expires_at < now:
        raise HTTPException(status_code=410, detail="Expired")
    resp = {
        "status": archive.status,
        "file_count": archive.file_count,
        "file_size": archive.file_size,
        "download_url": None,
        "error": None,
        "expires_at": archive.expires_at.isoformat(),
    }
    if archive.status == "ready":
        resp["download_url"] = f"/api/downloads/{token}/file"
    elif archive.status == "failed":
        resp["error"] = archive.error_message
    return JSONResponse(resp)


@router.get("/downloads/{token}/file")
async def download_archive(token: str, db: AsyncSession = Depends(get_db)):
    from datetime import datetime, timezone
    archive = await get_archive_by_token(db, token)
    if not archive:
        raise HTTPException(status_code=404, detail="Download link not found")

    if archive.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(status_code=410, detail="Download link has expired")

    if archive.status != "ready":
        raise HTTPException(status_code=425, detail="Archive not ready yet")

    if not os.path.exists(archive.file_path):
        raise HTTPException(status_code=404, detail="Archive file not found")

    filename = os.path.basename(archive.file_path)
    # Remove UUID prefix from filename
    parts = filename.split("_", 1)
    if len(parts) > 1:
        filename = parts[1]

    return FileResponse(
        archive.file_path,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/events/{event_id}/media/delete")
async def bulk_delete_media(
    event_id: str,
    body: MediaIdsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    event, is_owner, user = await get_event_and_check_access(event_id, request, db, require_owner=True)

    storage = get_storage()
    deleted = 0
    errors = []

    for media_id in body.media_ids:
        try:
            # Verify belongs to this event
            result = await db.execute(
                select(MediaFile).where(MediaFile.id == media_id, MediaFile.event_id == event_id)
            )
            mf = result.scalar_one_or_none()
            if not mf:
                errors.append({"id": media_id, "error": "Not found"})
                continue
            success = await delete_media_file(db, storage, media_id)
            if success:
                deleted += 1
            else:
                errors.append({"id": media_id, "error": "Delete failed"})
        except Exception as e:
            errors.append({"id": media_id, "error": str(e)})

    await db.commit()
    return JSONResponse({"deleted": deleted, "errors": errors})


@router.delete("/events/{event_id}/media/{media_id}")
async def delete_single_media(
    event_id: str,
    media_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    event, is_owner, user = await get_event_and_check_access(event_id, request, db, require_owner=True)

    # Verify belongs to this event
    result = await db.execute(
        select(MediaFile).where(MediaFile.id == media_id, MediaFile.event_id == event_id)
    )
    mf = result.scalar_one_or_none()
    if not mf:
        raise HTTPException(status_code=404)

    storage = get_storage()
    success = await delete_media_file(db, storage, media_id)
    await db.commit()

    return JSONResponse({"deleted": success})


@router.post("/events/{event_id}/thumbnails/regenerate")
async def start_thumbnail_regeneration(
    event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await get_event_and_check_access(event_id, request, db, require_owner=True)

    status = get_regen_status(event_id)
    if status.get("status") == "running":
        return JSONResponse({"status": "already_running"}, status_code=409)

    import asyncio
    asyncio.create_task(regenerate_thumbnails_task(event_id))
    return JSONResponse({"status": "started"}, status_code=202)


@router.get("/events/{event_id}/thumbnails/status")
async def thumbnail_regeneration_status(
    event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await get_event_and_check_access(event_id, request, db, require_owner=True)
    return JSONResponse(get_regen_status(event_id))


@router.post("/events/{event_id}/email-config/force-poll")
async def force_poll_email(
    event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    from eventdrop.auth.dependencies import get_current_user_optional
    from eventdrop.database.models import EventEmailConfig
    from eventdrop.services.email_ingestion import poll_mailbox

    user = await get_current_user_optional(request, db)
    if not user:
        raise HTTPException(status_code=401)

    event = await event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404)
    if str(event.owner_id) != str(user.id) and not user.is_admin:
        raise HTTPException(status_code=403)

    result = await db.execute(
        select(EventEmailConfig).where(
            EventEmailConfig.event_id == event_id,
            EventEmailConfig.is_enabled == True,  # noqa: E712
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="No active email config for this event")

    try:
        await poll_mailbox(config)
        await db.refresh(config)
        return JSONResponse({
            "success": True,
            "last_poll_status": config.last_poll_status,
            "last_poll_media_count": config.last_poll_media_count,
            "last_poll_error": config.last_poll_error,
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/events/{event_id}/email-config/test")
async def test_email_connection(
    event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Test email connection without saving."""
    from eventdrop.auth.dependencies import get_current_user_optional
    user = await get_current_user_optional(request, db)
    if not user:
        raise HTTPException(status_code=401)

    body = await request.json()
    protocol = body.get("protocol", "imap")
    server_host = body.get("server_host", "")
    server_port = int(body.get("server_port", 993))
    use_ssl = body.get("use_ssl", True)
    username = body.get("username", "")
    password = body.get("password", "")

    # Reject connections to private/loopback addresses to prevent SSRF
    import ipaddress
    import socket
    try:
        resolved = socket.getaddrinfo(server_host, None)
        for _, _, _, _, sockaddr in resolved:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise HTTPException(status_code=400, detail="Connections to private or reserved addresses are not allowed")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Unable to resolve host")

    # Validate port range
    if not (1 <= server_port <= 65535):
        raise HTTPException(status_code=400, detail="Invalid port number")

    def test_connection():
        try:
            if protocol.lower() == "imap":
                import imaplib
                if use_ssl:
                    mail = imaplib.IMAP4_SSL(server_host, server_port)
                else:
                    mail = imaplib.IMAP4(server_host, server_port)
                mail.login(username, password)
                mail.logout()
            else:
                import poplib
                if use_ssl:
                    mail = poplib.POP3_SSL(server_host, server_port)
                else:
                    mail = poplib.POP3(server_host, server_port)
                mail.user(username)
                mail.pass_(password)
                mail.quit()
            return {"success": True, "message": "Connection successful!"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    import asyncio
    result = await asyncio.to_thread(test_connection)
    return JSONResponse(result)
