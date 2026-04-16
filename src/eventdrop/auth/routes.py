import logging
import uuid
import secrets
from datetime import datetime, timedelta, timezone
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
from eventdrop.utils.context import build_ctx

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/login", response_class=HTMLResponse)
async def login_get(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Display the login page. Redirect to /events/ if already logged in."""
    from eventdrop.services.settings_service import is_registration_allowed
    user = await get_current_user_optional(request, db)
    if user is not None:
        return RedirectResponse(url="/events/", status_code=302)
    reg_allowed = await is_registration_allowed(db)
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        await build_ctx(
            request,
            user=None,
            oidc_enabled=settings.is_oidc_configured(),
            registration_allowed=reg_allowed,
            smtp_enabled=settings.is_smtp_configured(),
        ),
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
            request,
            "auth/login.html",
            await build_ctx(
                request,
                user=None,
                error_key="flash.login_error",
                oidc_enabled=settings.is_oidc_configured(),
            ),
            status_code=401,
        )

    request.session["user_id"] = str(user.id)
    return RedirectResponse(url="/events/", status_code=302)


@router.get("/signup", response_class=HTMLResponse)
async def signup_get(request: Request, db: AsyncSession = Depends(get_db)):
    """Display the sign-up page."""
    from eventdrop.services.settings_service import is_registration_allowed
    reg_allowed = await is_registration_allowed(db)
    return templates.TemplateResponse(
        request,
        "auth/signup.html",
        await build_ctx(request, user=None, registration_allowed=reg_allowed),
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
    from eventdrop.services.settings_service import is_registration_allowed
    if not (await is_registration_allowed(db)):
        return templates.TemplateResponse(
            request,
            "auth/signup.html",
            await build_ctx(request, user=None, error_key="flash.registration_disabled"),
            status_code=403,
        )

    # Validate password length
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "auth/signup.html",
            await build_ctx(request, user=None, error_key="flash.signup_error_short"),
            status_code=400,
        )

    # Validate password confirmation if provided
    if confirm_password and password != confirm_password:
        return templates.TemplateResponse(
            request,
            "auth/signup.html",
            await build_ctx(request, user=None, error_key="flash.signup_error_password"),
            status_code=400,
        )

    # Check username uniqueness
    result = await db.execute(select(User).where(User.username == username))
    existing = result.scalar_one_or_none()
    if existing:
        return templates.TemplateResponse(
            request,
            "auth/signup.html",
            await build_ctx(request, user=None, error_key="flash.signup_error_exists"),
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
    return RedirectResponse(url="/events/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    """Clear the user session and redirect to home."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_get(request: Request):
    return templates.TemplateResponse(request, "auth/forgot_password.html", await build_ctx(request))


@router.post("/forgot-password")
async def forgot_password_post(
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from eventdrop.database.models import PasswordResetToken
    from eventdrop.services.email_service import send_password_reset_email

    # Always show success to prevent email enumeration
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user and settings.is_smtp_configured():
        token = secrets.token_urlsafe(48)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        reset_token = PasswordResetToken(
            user_id=user.id,
            token=token,
            expires_at=expires_at,
        )
        db.add(reset_token)
        await db.commit()
        reset_url = f"{settings.base_url}/auth/reset-password?token={token}"
        await send_password_reset_email(user.email, reset_url)

    request.session["flash"] = {"type": "info", "key": "flash.reset_sent"}
    return RedirectResponse(url="/auth/forgot-password", status_code=302)


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_get(request: Request, token: str = ""):
    if not token:
        return RedirectResponse(url="/auth/login", status_code=302)
    return templates.TemplateResponse(request, "auth/reset_password.html", await build_ctx(request, token=token))


@router.post("/reset-password")
async def reset_password_post(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from eventdrop.database.models import PasswordResetToken

    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            await build_ctx(request, token=token, error_key="flash.password_error_short"),
            status_code=400,
        )
    if password != confirm_password:
        return templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            await build_ctx(request, token=token, error_key="flash.password_error_match"),
            status_code=400,
        )

    result = await db.execute(
        select(PasswordResetToken)
        .where(PasswordResetToken.token == token, PasswordResetToken.used == False)  # noqa: E712
    )
    reset_token = result.scalar_one_or_none()

    if not reset_token or reset_token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            await build_ctx(request, token=token, error_key="flash.reset_expired"),
            status_code=400,
        )

    result = await db.execute(select(User).where(User.id == reset_token.user_id))
    user = result.scalar_one_or_none()
    if not user:
        return templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            await build_ctx(request, token=token, error_key="flash.reset_expired"),
            status_code=400,
        )

    user.password_hash = hash_password(password)
    reset_token.used = True
    await db.commit()

    request.session["flash"] = {"type": "success", "key": "flash.reset_success"}
    return RedirectResponse(url="/auth/login", status_code=302)


# ---- OIDC routes (only registered if OIDC is configured) ----

if settings.is_oidc_configured():
    from eventdrop.auth.oidc import get_oauth

    @router.get("/oidc/login")
    async def oidc_login(request: Request):
        """Redirect to the OIDC provider authorization endpoint."""
        oauth = get_oauth()
        if oauth is None:
            return RedirectResponse(url="/auth/login", status_code=302)
        redirect_uri = settings.base_url.rstrip("/") + "/auth/oidc/callback"
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
            request.session["flash"] = {"type": "error", "message": "OIDC login failed. Please try again."}
            return RedirectResponse(url="/auth/login", status_code=302)

        # Merge ID token claims with userinfo endpoint claims.
        # Authelia (and some providers) only return profile/email claims from the
        # userinfo endpoint, not in the ID token — so we must call both and merge.
        id_token_claims = token.get("userinfo") or {}
        try:
            userinfo_claims = await oauth.oidc.userinfo(token=token)
        except Exception:
            userinfo_claims = {}
        userinfo = {**id_token_claims, **userinfo_claims}

        subject = userinfo.get("sub")
        email = userinfo.get("email") or ""
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
                # Create a new user with a unique username derived from preferred_username
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

        # Always sync email and username from OIDC provider on each login
        if email and user.email != email:
            user.email = email

        # Sync username if the provider gives us something better than the raw subject
        if preferred_username and preferred_username != subject and user.username != preferred_username:
            # Only update if the target username is not already taken by a different user
            result = await db.execute(
                select(User).where(User.username == preferred_username, User.id != user.id)
            )
            if result.scalar_one_or_none() is None:
                user.username = preferred_username

        await db.flush()

        request.session["user_id"] = str(user.id)
        # No flash needed for OIDC login
        return RedirectResponse(url="/events/", status_code=302)
