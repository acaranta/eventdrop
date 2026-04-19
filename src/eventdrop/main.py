import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from eventdrop.config import settings
from eventdrop.database.engine import engine
from eventdrop.database.models import Base
from eventdrop.templating import templates

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent


async def create_admin_user():
    """Create the admin user from environment variables on first run only."""
    from sqlalchemy import select
    from eventdrop.database.engine import AsyncSessionLocal
    from eventdrop.database.models import User
    from eventdrop.auth.passwords import hash_password

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.username == settings.admin_username)
        )
        admin = result.scalar_one_or_none()
        if admin is None:
            using_default_password = settings.admin_password == "changeme"
            admin = User(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                is_admin=True,
                password_change_required=using_default_password,
            )
            session.add(admin)
            await session.commit()
            if using_default_password:
                logger.warning(
                    f"Admin user '{settings.admin_username}' created with default password. "
                    "A password change will be required on first login."
                )
            else:
                logger.info(f"Admin user '{settings.admin_username}' created.")
        else:
            logger.info(f"Admin user '{settings.admin_username}' already exists, skipping credential update.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables (alembic handles migrations in production, but create_all is safe for dev)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await create_admin_user()

    background_tasks = []

    if settings.email_ingestion_enabled:
        from eventdrop.services.email_ingestion import email_ingestion_loop
        task = asyncio.create_task(email_ingestion_loop())
        background_tasks.append(task)
        logger.info("Email ingestion background task started.")

    from eventdrop.services.archive_service import archive_cleanup_loop
    cleanup_task = asyncio.create_task(archive_cleanup_loop())
    background_tasks.append(cleanup_task)

    yield

    for task in background_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await engine.dispose()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


app = FastAPI(title="EventDrop", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.base_url.rstrip("/")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

# Mount static files
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# Serve local media files
@app.get("/media/{path:path}")
async def serve_media(path: str):
    storage_root = os.path.normpath(settings.storage_local_path)
    full_path = os.path.normpath(os.path.join(storage_root, path))
    # Reject any path that escapes the storage root directory
    if not full_path.startswith(storage_root + os.sep) and full_path != storage_root:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(full_path)


# Register routers
from eventdrop.routes import admin, events, upload, gallery, api  # noqa: E402
from eventdrop.auth.routes import router as auth_router  # noqa: E402
from eventdrop.routes.account import router as account_router  # noqa: E402
from eventdrop.routes.lang import router as lang_router  # noqa: E402
from eventdrop.routes.downloads import router as downloads_router  # noqa: E402

app.include_router(auth_router)
app.include_router(account_router)
app.include_router(lang_router)
app.include_router(admin.router)
app.include_router(events.router)
app.include_router(upload.router)
app.include_router(gallery.router)
app.include_router(downloads_router)
app.include_router(api.router)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    from sqlalchemy import select
    from eventdrop.database.engine import AsyncSessionLocal
    from eventdrop.database.models import User as UserModel
    from eventdrop.utils.context import build_ctx

    user = None
    user_id = request.session.get("user_id")
    async with AsyncSessionLocal() as session:
        if user_id:
            result = await session.execute(select(UserModel).where(UserModel.id == user_id))
            user = result.scalar_one_or_none()

    if user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/events/")

    return templates.TemplateResponse(
        request,
        "index.html",
        await build_ctx(request, user=None),
    )


@app.exception_handler(404)
async def not_found(request: Request, exc):
    from eventdrop.utils.context import build_ctx
    return templates.TemplateResponse(
        request,
        "errors/404.html",
        await build_ctx(request, user=None),
        status_code=404,
    )


@app.exception_handler(500)
async def server_error(request: Request, exc):
    from eventdrop.utils.context import build_ctx
    return templates.TemplateResponse(
        request,
        "errors/500.html",
        await build_ctx(request, user=None),
        status_code=500,
    )
