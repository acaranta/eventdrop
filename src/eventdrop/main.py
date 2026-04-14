import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from eventdrop.config import settings
from eventdrop.database.engine import engine
from eventdrop.database.models import Base

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


async def create_admin_user():
    """Create or update the admin user from environment variables."""
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
            admin = User(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                is_admin=True,
            )
            session.add(admin)
        else:
            admin.password_hash = hash_password(settings.admin_password)
            admin.is_admin = True
        await session.commit()
        logger.info(f"Admin user '{settings.admin_username}' ready.")


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


app = FastAPI(title="EventDrop", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

# Mount static files
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# Serve local media files
@app.get("/media/{path:path}")
async def serve_media(path: str):
    file_path = os.path.join(settings.storage_local_path, path)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


# Register routers
from eventdrop.routes import admin, events, upload, gallery, api  # noqa: E402
from eventdrop.auth.routes import router as auth_router  # noqa: E402

app.include_router(auth_router)
app.include_router(admin.router)
app.include_router(events.router)
app.include_router(upload.router)
app.include_router(gallery.router)
app.include_router(api.router)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    from eventdrop.auth.dependencies import get_current_user_optional
    user = await get_current_user_optional(request)
    if user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/events/")
    return templates.TemplateResponse("index.html", {"request": request})


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return templates.TemplateResponse("errors/404.html", {"request": request}, status_code=404)


@app.exception_handler(500)
async def server_error(request: Request, exc):
    return templates.TemplateResponse("errors/500.html", {"request": request}, status_code=500)
