from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pathlib import Path

from eventdrop.auth.dependencies import require_admin
from eventdrop.database.session import get_db
from eventdrop.database.models import User, Event, MediaFile, EventEmailConfig
from eventdrop.services import user_service, event_service
from eventdrop.storage import get_storage

router = APIRouter(prefix="/admin", tags=["admin"])
BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def admin_ctx(request, admin_user, **kwargs):
    return {"request": request, "user": admin_user, "settings": __import__("eventdrop.config", fromlist=["settings"]).settings, **kwargs}


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

    flash = request.session.pop("flash", None)
    return templates.TemplateResponse("admin/dashboard.html", admin_ctx(
        request, admin,
        users_count=users_count,
        events_count=events_count,
        media_count=media_count,
        total_size=total_size,
        email_configs_count=email_configs_count,
        recent_polls=recent_polls,
        flash=flash,
    ))


@router.get("/events", response_class=HTMLResponse)
async def admin_events(request: Request, admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    events = await event_service.list_all_events(db)
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse("admin/events.html", admin_ctx(request, admin, events=events, flash=flash))


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
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse("admin/event_detail.html", admin_ctx(
        request, admin, event=event, media_with_urls=media_with_urls, flash=flash
    ))


@router.post("/events/{event_id}/delete")
async def admin_delete_event(event_id: str, request: Request, admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    storage = get_storage()
    await event_service.delete_event(db, event_id, storage)
    await db.commit()
    request.session["flash"] = {"type": "success", "message": "Event deleted successfully."}
    return RedirectResponse(url="/admin/events", status_code=303)


@router.get("/users", response_class=HTMLResponse)
async def admin_users(request: Request, admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    users = await user_service.list_users(db)
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse("admin/users.html", admin_ctx(request, admin, users=users, flash=flash))


@router.post("/users/{user_id}/delete")
async def admin_delete_user(user_id: str, request: Request, admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    if user_id == str(admin.id):
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    await user_service.delete_user(db, user_id)
    await db.commit()
    request.session["flash"] = {"type": "success", "message": "User deleted."}
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
