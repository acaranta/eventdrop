import os
import pytest
import pytest_asyncio

# Use an in-memory SQLite database for tests
os.environ.setdefault("EVENTDROP_DB_TYPE", "sqlite")
os.environ.setdefault("EVENTDROP_DB_PATH", ":memory:")
os.environ.setdefault("EVENTDROP_STORAGE_TYPE", "local")
os.environ.setdefault("EVENTDROP_STORAGE_LOCAL_PATH", "/tmp/eventdrop_test_media")
os.environ.setdefault("EVENTDROP_EMAIL_INGESTION_ENABLED", "false")
os.environ.setdefault("EVENTDROP_SECRET_KEY", "test-secret-key")


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"
