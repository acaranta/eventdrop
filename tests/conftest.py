import asyncio
import os
import pytest
import pytest_asyncio

# Set test environment variables before any imports that trigger config loading
os.environ.setdefault("EVENTDROP_DB_TYPE", "sqlite")
os.environ.setdefault("EVENTDROP_DB_PATH", ":memory:")
os.environ.setdefault("EVENTDROP_STORAGE_TYPE", "local")
os.environ.setdefault("EVENTDROP_STORAGE_LOCAL_PATH", "/tmp/eventdrop_test_media")
os.environ.setdefault("EVENTDROP_EMAIL_INGESTION_ENABLED", "false")
os.environ.setdefault("EVENTDROP_SECRET_KEY", "test-secret-key-for-testing-only")

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from eventdrop.main import app
from eventdrop.database.session import get_db
from eventdrop.database.models import Base, User, Event
from eventdrop.auth.passwords import hash_password
import uuid

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    AsyncTestSession = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with AsyncTestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def test_client(test_engine):
    AsyncTestSession = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with AsyncTestSession() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session):
    user = User(
        id=str(uuid.uuid4()),
        username="testuser",
        email="test@example.com",
        password_hash=hash_password("password123"),
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    yield user
    try:
        await db_session.delete(user)
        await db_session.commit()
    except Exception:
        await db_session.rollback()


@pytest_asyncio.fixture
async def test_admin(db_session):
    admin = User(
        id=str(uuid.uuid4()),
        username="testadmin",
        email="admin@example.com",
        password_hash=hash_password("adminpass123"),
        is_admin=True,
    )
    db_session.add(admin)
    await db_session.commit()
    yield admin
    try:
        await db_session.delete(admin)
        await db_session.commit()
    except Exception:
        await db_session.rollback()


@pytest_asyncio.fixture
async def test_event(db_session, test_user):
    event = Event(
        id="testev01",
        name="Test Event",
        description="A test event",
        owner_id=test_user.id,
        is_gallery_public=True,
        allow_public_download=True,
        is_active=True,
    )
    db_session.add(event)
    await db_session.commit()
    yield event
    try:
        await db_session.delete(event)
        await db_session.commit()
    except Exception:
        await db_session.rollback()
