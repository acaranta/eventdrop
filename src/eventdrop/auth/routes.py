import uuid
from typing import Optional

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eventdrop.database.session import get_db
from eventdrop.database.models import User
from eventdrop.auth.passwords import hash_password, verify_password
from eventdrop.auth.dependencies import get_current_user_optional
from eventdrop.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _set_flash(request: Request, message: str, flash_type: str = "error") -> None:
    """Store a flash message in the session for the next request."""
    request.session["flash"] = {"type": flash_type, "message": message}


def _pop_flash(request: Request) -> Optional[dict]:
    """Read and remove the flash message from the session."""
    flash = request.session.get("flash")
    if flash:
        del request.session["flash"]
    return flash


def _ctx(request: Request, user=None, **kwargs) -> dict:
    """Build a base template context with flash, user and settings."""
    return {
        "request": request,
        "user": user,
        "settings": settings,
        "flash": _pop_flash(request),
        **kwargs,
    }


@router.get("/login", response_class=HTMLResponse)
async def login_get(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Display the login page. Redirect to /events/ if already logged in."""
    user = await get_current_user_optional(request, db)
    if user is not None:
        return RedirectResponse(url="/events/", status_code=302)
    return templates.TemplateResponse(
        "auth/login.html",
        _ctx(request, user=None, error=None, oidc_enabled=settings.is_oidc_configured()),
    )


@router.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Process login form submission."""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None or not user.password_hash or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "auth/login.html",
            _ctx(
                request,
                user=None,
                error="Invalid username or password",
                oidc_enabled=settings.is_oidc_configured(),
            ),
            status_code=401,
        )

    request.session["user_id"] = str(user.id)
    _set_flash(request, f"Welcome back, {user.username}!", "success")
    return RedirectResponse(url="/events/", status_code=302)


@router.get("/signup", response_class=HTMLResponse)
async def signup_get(request: Request):
    """Display the sign-up page."""
    return templates.TemplateResponse(
        "auth/signup.html",
        _ctx(request, user=None, error=None),
    )


@router.post("/signup")
async def signup_post(
    request: Request,
    username: str = Form(...),
    email: str = Form(default=""),
    password: str = Form(...),
    confirm_password: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Process sign-up form submission."""
    # Validate password length
    if len(password) < 8:
        return templates.TemplateResponse(
            "auth/signup.html",
            _ctx(request, user=None, error="Password must be at least 8 characters long"),
            status_code=400,
        )

    # Validate password confirmation if provided
    if confirm_password and password != confirm_password:
        return templates.TemplateResponse(
            "auth/signup.html",
            _ctx(request, user=None, error="Passwords do not match"),
            status_code=400,
        )

    # Check username uniqueness
    result = await db.execute(select(User).where(User.username == username))
    existing = result.scalar_one_or_none()
    if existing:
        return templates.TemplateResponse(
            "auth/signup.html",
            _ctx(request, user=None, error="Username already taken"),
            status_code=400,
        )

    # Create new user
    new_user = User(
        id=str(uuid.uuid4()),
        username=username,
        email=email or None,
        password_hash=hash_password(password),
        is_admin=False,
    )
    db.add(new_user)
    await db.flush()

    request.session["user_id"] = str(new_user.id)
    _set_flash(request, f"Welcome to EventDrop, {username}!", "success")
    return RedirectResponse(url="/events/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    """Clear the user session and redirect to home."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


# ---- OIDC routes (only registered if OIDC is configured) ----

if settings.is_oidc_configured():
    from eventdrop.auth.oidc import get_oauth

    @router.get("/oidc/login")
    async def oidc_login(request: Request):
        """Redirect to the OIDC provider authorization endpoint."""
        oauth = get_oauth()
        if oauth is None:
            return RedirectResponse(url="/auth/login", status_code=302)
        redirect_uri = str(request.url_for("oidc_callback"))
        return await oauth.oidc.authorize_redirect(request, redirect_uri)

    @router.get("/oidc/callback", name="oidc_callback")
    async def oidc_callback(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ):
        """Handle the OIDC provider callback, create/find user, set session."""
        oauth = get_oauth()
        if oauth is None:
            return RedirectResponse(url="/auth/login", status_code=302)

        try:
            token = await oauth.oidc.authorize_access_token(request)
        except Exception:
            _set_flash(request, "OIDC login failed. Please try again.", "error")
            return RedirectResponse(url="/auth/login", status_code=302)

        userinfo = token.get("userinfo") or await oauth.oidc.userinfo(token=token)

        subject = userinfo.get("sub")
        email = userinfo.get("email", "")
        preferred_username = (
            userinfo.get("preferred_username")
            or userinfo.get("name")
            or (email.split("@")[0] if email else None)
            or subject
        )

        # Look up existing user by OIDC subject
        result = await db.execute(select(User).where(User.oidc_subject == subject))
        user = result.scalar_one_or_none()

        if user is None:
            # Try to match by email
            if email:
                result = await db.execute(select(User).where(User.email == email))
                user = result.scalar_one_or_none()

            if user is None:
                # Create a new user with a unique username
                base_username = preferred_username
                username = base_username
                counter = 1
                while True:
                    result = await db.execute(select(User).where(User.username == username))
                    if result.scalar_one_or_none() is None:
                        break
                    username = f"{base_username}{counter}"
                    counter += 1

                user = User(
                    id=str(uuid.uuid4()),
                    username=username,
                    email=email or None,
                    oidc_subject=subject,
                    is_admin=False,
                )
                db.add(user)
            else:
                # Link existing email user to OIDC subject
                user.oidc_subject = subject

            await db.flush()

        request.session["user_id"] = str(user.id)
        _set_flash(request, f"Welcome, {user.username}!", "success")
        return RedirectResponse(url="/events/", status_code=302)
