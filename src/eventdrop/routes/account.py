from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path
from typing import Optional

from eventdrop.auth.dependencies import get_current_user
from eventdrop.auth.passwords import hash_password, verify_password
from eventdrop.database.session import get_db
from eventdrop.config import settings
from eventdrop.utils.context import build_ctx

router = APIRouter(prefix="/account", tags=["account"])
BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/", response_class=HTMLResponse)
async def account_page(request: Request, user=Depends(get_current_user)):
    return templates.TemplateResponse(request, "account/index.html", build_ctx(request, user))


@router.post("/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.password_hash:
        request.session["flash"] = {"type": "error", "message": "Password change not available for SSO accounts."}
        return RedirectResponse(url="/account/", status_code=303)

    if not verify_password(current_password, user.password_hash):
        return templates.TemplateResponse(request, "account/index.html",
            build_ctx(request, user, error_key="flash.password_error_current"))

    if len(new_password) < 8:
        return templates.TemplateResponse(request, "account/index.html",
            build_ctx(request, user, error_key="flash.password_error_short"))

    if new_password != confirm_password:
        return templates.TemplateResponse(request, "account/index.html",
            build_ctx(request, user, error_key="flash.password_error_match"))

    user.password_hash = hash_password(new_password)
    await db.commit()
    request.session["flash"] = {"type": "success", "key": "flash.password_changed"}
    return RedirectResponse(url="/account/", status_code=303)


@router.post("/update-email")
async def update_email(
    request: Request,
    email: Optional[str] = Form(None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    email = email.strip() if email else ""
    if email and "@" not in email:
        request.session["flash"] = {"type": "error", "key": "flash.email_invalid"}
        return RedirectResponse(url="/account/", status_code=303)

    user.email = email or None
    await db.commit()
    request.session["flash"] = {"type": "success", "key": "flash.email_updated"}
    return RedirectResponse(url="/account/", status_code=303)
