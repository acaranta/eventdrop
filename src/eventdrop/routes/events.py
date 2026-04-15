from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from pathlib import Path

from eventdrop.auth.dependencies import get_current_user
from eventdrop.database.session import get_db
from eventdrop.database.models import Event
from eventdrop.services import event_service
from eventdrop.storage import get_storage
from eventdrop.config import settings
from eventdrop.utils.qrcode import generate_qr_code_base64
from eventdrop.utils.context import build_ctx

router = APIRouter(prefix="/events", tags=["events"])
BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/", response_class=HTMLResponse)
async def my_events(request: Request, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    events = await event_service.list_events_by_owner(db, str(user.id))
    return templates.TemplateResponse(request, "events/my_events.html", await build_ctx(request, user, events=events))


@router.get("/create", response_class=HTMLResponse)
async def create_event_form(request: Request, user=Depends(get_current_user)):
    return templates.TemplateResponse(request, "events/create_event.html", await build_ctx(request, user))


@router.post("/create")
async def create_event_submit(
    request: Request,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    is_gallery_public: bool = Form(False),
    allow_public_download: bool = Form(False),
    # Email config fields
    email_enabled: bool = Form(False),
    email_protocol: Optional[str] = Form(None),
    email_server_host: Optional[str] = Form(None),
    email_server_port: Optional[int] = Form(None),
    email_use_ssl: bool = Form(False),
    email_username: Optional[str] = Form(None),
    email_password: Optional[str] = Form(None),
    email_address: Optional[str] = Form(None),
    email_delete_after: bool = Form(False),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    event = await event_service.create_event(
        db, owner_id=str(user.id), name=name, description=description,
        is_gallery_public=is_gallery_public, allow_public_download=allow_public_download
    )

    if settings.email_ingestion_enabled and email_enabled and email_server_host and email_username and email_password:
        await event_service.upsert_email_config(db, event.id, {
            "is_enabled": True,
            "protocol": email_protocol or "imap",
            "server_host": email_server_host,
            "server_port": email_server_port or (993 if email_use_ssl else 143),
            "use_ssl": email_use_ssl,
            "username": email_username,
            "password": email_password,
            "email_address": email_address or email_username,
            "delete_after_ingestion": email_delete_after,
        })

    await db.commit()
    request.session["flash"] = {"type": "success", "key": "flash.event_created"}
    return RedirectResponse(url=f"/events/{event.id}/edit", status_code=303)


@router.get("/{event_id}/edit", response_class=HTMLResponse)
async def edit_event_form(event_id: str, request: Request, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    event = await event_service.get_event_with_email_config(db, event_id)
    if not event:
        raise HTTPException(status_code=404)
    if str(event.owner_id) != str(user.id) and not user.is_admin:
        raise HTTPException(status_code=403)
    upload_url = f"{settings.base_url}/e/{event.id}/"
    qr_code = generate_qr_code_base64(upload_url)
    stats = await event_service.get_event_stats(db, event_id)

    from sqlalchemy import select, func
    from eventdrop.database.models import MediaFile
    contrib_result = await db.execute(
        select(
            MediaFile.uploader_email,
            func.count(MediaFile.id).label("count")
        )
        .where(MediaFile.event_id == event_id)
        .group_by(MediaFile.uploader_email)
        .order_by(func.count(MediaFile.id).desc())
    )
    contributors = [{"email": row.uploader_email, "count": row.count} for row in contrib_result]

    return templates.TemplateResponse(request, "events/edit_event.html", await build_ctx(
        request, user, event=event, upload_url=upload_url, qr_code=qr_code, stats=stats,
        contributors=contributors
    ))


@router.post("/{event_id}/edit")
async def edit_event_submit(
    event_id: str,
    request: Request,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    is_gallery_public: bool = Form(False),
    allow_public_download: bool = Form(False),
    is_active: bool = Form(True),
    email_enabled: bool = Form(False),
    email_protocol: Optional[str] = Form(None),
    email_server_host: Optional[str] = Form(None),
    email_server_port: Optional[int] = Form(None),
    email_use_ssl: bool = Form(False),
    email_username: Optional[str] = Form(None),
    email_password: Optional[str] = Form(None),
    email_address: Optional[str] = Form(None),
    email_delete_after: bool = Form(False),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    event = await event_service.get_event(db, event_id)
    if not event or (str(event.owner_id) != str(user.id) and not user.is_admin):
        raise HTTPException(status_code=403)

    await event_service.update_event(db, event_id, name=name, description=description,
                                     is_gallery_public=is_gallery_public,
                                     allow_public_download=allow_public_download,
                                     is_active=is_active)

    if settings.email_ingestion_enabled:
        if email_enabled and email_server_host and email_username:
            config_data = {
                "is_enabled": True,
                "protocol": email_protocol or "imap",
                "server_host": email_server_host,
                "server_port": email_server_port or (993 if email_use_ssl else 143),
                "use_ssl": email_use_ssl,
                "username": email_username,
                "email_address": email_address or email_username,
                "delete_after_ingestion": email_delete_after,
            }
            if email_password:
                config_data["password"] = email_password
            await event_service.upsert_email_config(db, event_id, config_data)
        else:
            # Disable email config if exists
            from sqlalchemy import select
            from eventdrop.database.models import EventEmailConfig
            result = await db.execute(select(EventEmailConfig).where(EventEmailConfig.event_id == event_id))
            cfg = result.scalar_one_or_none()
            if cfg:
                cfg.is_enabled = False

    await db.commit()
    request.session["flash"] = {"type": "success", "key": "flash.event_updated"}
    return RedirectResponse(url=f"/events/{event_id}/edit", status_code=303)


@router.post("/{event_id}/delete")
async def delete_event(event_id: str, request: Request, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    event = await event_service.get_event(db, event_id)
    if not event or (str(event.owner_id) != str(user.id) and not user.is_admin):
        raise HTTPException(status_code=403)
    storage = get_storage()
    await event_service.delete_event(db, event_id, storage)
    await db.commit()
    request.session["flash"] = {"type": "success", "key": "flash.event_deleted"}
    return RedirectResponse(url="/events/", status_code=303)


@router.get("/{event_id}/qr.png")
async def download_qr(event_id: str, db: AsyncSession = Depends(get_db)):
    from eventdrop.utils.qrcode import generate_qr_code
    event = await event_service.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404)
    upload_url = f"{settings.base_url}/e/{event.id}/"
    qr_data = generate_qr_code(upload_url)
    return Response(content=qr_data, media_type="image/png",
                    headers={"Content-Disposition": f"attachment; filename=event_{event_id}_qr.png"})
