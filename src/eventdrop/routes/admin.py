from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone

from eventdrop.auth.dependencies import require_admin
from eventdrop.database.session import get_db
from eventdrop.database.models import User, Event, MediaFile, EventEmailConfig, ArchiveRequest
from eventdrop.services import user_service, event_service
from eventdrop.storage import get_storage
from eventdrop.utils.context import build_ctx
from eventdrop.templating import templates

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    # Stats
    users_count = (await db.execute(select(func.count(User.id)))).scalar()
    events_count = (await db.execute(select(func.count(Event.id)))).scalar()
    media_count = (await db.execute(select(func.count(MediaFile.id)))).scalar()
    total_size = (await db.execute(select(func.sum(MediaFile.file_size)))).scalar() or 0
    email_configs_count = (await db.execute(
        select(func.count(EventEmailConfig.id)).where(EventEmailConfig.is_enabled == True)
    )).scalar()

    # Recent poll statuses
    recent_polls = (await db.execute(
        select(EventEmailConfig)
        .where(EventEmailConfig.last_poll_at != None)
        .order_by(EventEmailConfig.last_poll_at.desc())
        .limit(5)
    )).scalars().all()

    return templates.TemplateResponse(request, "admin/dashboard.html", await build_ctx(
        request, admin,
        users_count=users_count,
        events_count=events_count,
        media_count=media_count,
        total_size=total_size,
        email_configs_count=email_configs_count,
        recent_polls=recent_polls,
    ))


@router.get("/events", response_class=HTMLResponse)
async def admin_events(request: Request, admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    events = await event_service.list_all_events(db)
    return templates.TemplateResponse(request, "admin/events.html", await build_ctx(request, admin, events=events))


@router.get("/events/{event_id}", response_class=HTMLResponse)
async def admin_event_detail(event_id: str, request: Request, admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Event)
        .options(selectinload(Event.media_files), selectinload(Event.email_config), selectinload(Event.owner))
        .where(Event.id == event_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    storage = get_storage()
    media_with_urls = []
    for mf in event.media_files:
        url = await storage.get_url(mf.stored_path)
        thumb_url = await storage.get_url(mf.thumb_path) if mf.thumb_path else None
        media_with_urls.append({"media": mf, "url": url, "thumb_url": thumb_url})
    return templates.TemplateResponse(request, "admin/event_detail.html", await build_ctx(
        request, admin, event=event, media_with_urls=media_with_urls
    ))


@router.post("/events/{event_id}/delete")
async def admin_delete_event(event_id: str, request: Request, admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    storage = get_storage()
    await event_service.delete_event(db, event_id, storage)
    await db.commit()
    request.session["flash"] = {"type": "success", "key": "flash.event_deleted"}
    return RedirectResponse(url="/admin/events", status_code=303)


@router.get("/users", response_class=HTMLResponse)
async def admin_users(request: Request, admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    users = await user_service.list_users(db)
    return templates.TemplateResponse(request, "admin/users.html", await build_ctx(request, admin, users=users))


@router.post("/users/{user_id}/delete")
async def admin_delete_user(user_id: str, request: Request, admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    if user_id == str(admin.id):
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    await user_service.delete_user(db, user_id)
    await db.commit()
    request.session["flash"] = {"type": "success", "key": "flash.user_deleted"}
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{user_id}/toggle-admin")
async def admin_toggle_admin(user_id: str, request: Request, admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    user = await user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404)
    if user_id == str(admin.id):
        raise HTTPException(status_code=400, detail="Cannot change your own admin status")
    user.is_admin = not user.is_admin
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    from eventdrop.services.settings_service import get_setting
    allow_registration = (await get_setting(db, "allow_registration")) == "true"
    return templates.TemplateResponse(request, "admin/settings.html", await build_ctx(
        request, admin, allow_registration=allow_registration
    ))


@router.get("/downloads", response_class=HTMLResponse)
async def admin_downloads(request: Request, admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ArchiveRequest, Event.name.label("event_name"))
        .join(Event, ArchiveRequest.event_id == Event.id, isouter=True)
        .order_by(ArchiveRequest.created_at.desc())
    )
    rows = result.all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    archives = [
        {
            "archive": row.ArchiveRequest,
            "event_name": row.event_name or "",
            "expired": row.ArchiveRequest.expires_at < now,
        }
        for row in rows
    ]
    return templates.TemplateResponse(request, "admin/downloads.html", await build_ctx(
        request, admin, archives=archives, now=now,
    ))


@router.post("/downloads/{archive_id}/cancel")
async def admin_cancel_archive(archive_id: str, request: Request, admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ArchiveRequest).where(ArchiveRequest.id == archive_id))
    archive = result.scalar_one_or_none()
    if not archive:
        raise HTTPException(status_code=404)
    if archive.status in ("pending", "processing"):
        archive.status = "cancelled"
        await db.commit()
    return RedirectResponse(url="/admin/downloads", status_code=303)


@router.post("/downloads/{archive_id}/delete")
async def admin_delete_archive(archive_id: str, request: Request, admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    import os
    result = await db.execute(select(ArchiveRequest).where(ArchiveRequest.id == archive_id))
    archive = result.scalar_one_or_none()
    if not archive:
        raise HTTPException(status_code=404)
    if archive.file_path and os.path.exists(archive.file_path):
        try:
            os.remove(archive.file_path)
        except Exception:
            pass
    await db.delete(archive)
    await db.commit()
    return RedirectResponse(url="/admin/downloads", status_code=303)


@router.post("/settings")
async def admin_settings_post(
    request: Request,
    allow_registration: bool = Form(False),
    admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from eventdrop.services.settings_service import set_setting
    from eventdrop.utils.context import invalidate_registration_cache
    await set_setting(db, "allow_registration", "true" if allow_registration else "false")
    await db.commit()
    invalidate_registration_cache()
    request.session["flash"] = {"type": "success", "key": "flash.settings_saved"}
    return RedirectResponse(url="/admin/settings", status_code=303)
