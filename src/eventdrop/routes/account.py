from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path

from eventdrop.auth.dependencies import get_current_user
from eventdrop.auth.passwords import hash_password, verify_password
from eventdrop.database.session import get_db
from eventdrop.config import settings

router = APIRouter(prefix="/account", tags=["account"])
BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/", response_class=HTMLResponse)
async def account_page(request: Request, user=Depends(get_current_user)):
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, "account/index.html", {
        "user": user, "settings": settings, "flash": flash,
    })


@router.post("/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    flash = request.session.pop("flash", None)

    if not user.password_hash:
        request.session["flash"] = {"type": "error", "message": "Password change not available for SSO accounts."}
        return RedirectResponse(url="/account/", status_code=303)

    if not verify_password(current_password, user.password_hash):
        return templates.TemplateResponse(request, "account/index.html", {
            "user": user, "settings": settings, "flash": flash,
            "error": "Current password is incorrect.",
        })

    if len(new_password) < 8:
        return templates.TemplateResponse(request, "account/index.html", {
            "user": user, "settings": settings, "flash": flash,
            "error": "New password must be at least 8 characters.",
        })

    if new_password != confirm_password:
        return templates.TemplateResponse(request, "account/index.html", {
            "user": user, "settings": settings, "flash": flash,
            "error": "Passwords do not match.",
        })

    user.password_hash = hash_password(new_password)
    await db.commit()
    request.session["flash"] = {"type": "success", "message": "Password changed successfully."}
    return RedirectResponse(url="/account/", status_code=303)
