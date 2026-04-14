from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter(prefix="/auth", tags=["auth"])

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    """Display the login page."""
    return templates.TemplateResponse("auth/login.html", {"request": request, "error": None})


@router.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """Process login form submission."""
    from sqlalchemy import select
    from eventdrop.database.engine import AsyncSessionLocal
    from eventdrop.database.models import User
    from eventdrop.auth.passwords import verify_password

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

    if user is None or not user.password_hash or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=401,
        )

    request.session["user_id"] = user.id
    return RedirectResponse(url="/events/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    """Clear the user session."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


@router.get("/signup", response_class=HTMLResponse)
async def signup_get(request: Request):
    """Display the sign-up page (placeholder)."""
    return templates.TemplateResponse("auth/signup.html", {"request": request, "error": None})


@router.post("/signup")
async def signup_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    email: str = Form(default=""),
):
    """Process sign-up form submission (placeholder)."""
    from sqlalchemy import select
    from eventdrop.database.engine import AsyncSessionLocal
    from eventdrop.database.models import User
    from eventdrop.auth.passwords import hash_password
    import uuid

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        existing = result.scalar_one_or_none()
        if existing:
            return templates.TemplateResponse(
                "auth/signup.html",
                {"request": request, "error": "Username already taken"},
                status_code=400,
            )

        new_user = User(
            id=str(uuid.uuid4()),
            username=username,
            email=email or None,
            password_hash=hash_password(password),
            is_admin=False,
        )
        session.add(new_user)
        await session.commit()

    return RedirectResponse(url="/auth/login", status_code=302)
