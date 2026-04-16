import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.middleware.sessions import SessionMiddleware

from eventdrop.config import settings
from eventdrop.database.engine import engine
from eventdrop.database.models import Base

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Register tojson filter (not built-in in plain Jinja2)
def _tojson_filter(value, **kwargs):
    return Markup(json.dumps(value, **kwargs))

templates.env.filters["tojson"] = _tojson_filter


def _anonymize_email(email: str) -> str:
    """Anonymize the domain of an email address for public display.

    Keeps the local part intact, the first letter and TLD of the domain,
    and replaces the rest of the domain with 8 asterisks.
    Example: john.doe@example.com → john.doe@e********.com
    """
    try:
        local, domain = email.rsplit("@", 1)
        parts = domain.rsplit(".", 1)
        if len(parts) == 2:
            domain_name, tld = parts
            anon_domain = domain_name[0] + "********"
            return f"{local}@{anon_domain}.{tld}"
        # No TLD — just mask after first char
        return f"{local}@{domain[0]}********"
    except Exception:
        return email

templates.env.filters["anonymize_email"] = _anonymize_email


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
            admin = User(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                is_admin=True,
            )
            session.add(admin)
            await session.commit()
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
from eventdrop.routes.account import router as account_router  # noqa: E402
from eventdrop.routes.lang import router as lang_router  # noqa: E402

app.include_router(auth_router)
app.include_router(account_router)
app.include_router(lang_router)
app.include_router(admin.router)
app.include_router(events.router)
app.include_router(upload.router)
app.include_router(gallery.router)
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
