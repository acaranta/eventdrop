"""Tests for storage backends."""
import io
import os
import pytest
import pytest_asyncio

from eventdrop.storage.local import LocalStorage
from eventdrop.config import settings


@pytest_asyncio.fixture
async def local_storage(tmp_path):
    """Create a LocalStorage instance pointing at a temporary directory."""
    storage = LocalStorage.__new__(LocalStorage)
    # Override the settings path so files go to tmp_path
    original_path = settings.storage_local_path
    settings.storage_local_path = str(tmp_path)
    yield storage
    settings.storage_local_path = original_path


@pytest.mark.asyncio
async def test_local_storage_store_writes_file(local_storage: LocalStorage, tmp_path):
    """LocalStorage.store() should write data to the correct path."""
    content = b"hello test storage"
    await local_storage.store("event1/file.txt", io.BytesIO(content), "text/plain")
    full_path = os.path.join(str(tmp_path), "event1/file.txt")
    assert os.path.exists(full_path)
    with open(full_path, "rb") as f:
        assert f.read() == content


@pytest.mark.asyncio
async def test_local_storage_retrieve_reads_file(local_storage: LocalStorage, tmp_path):
    """LocalStorage.retrieve() should return the stored content."""
    content = b"retrieve this content"
    await local_storage.store("event1/retrieve.txt", io.BytesIO(content), "text/plain")
    result = await local_storage.retrieve("event1/retrieve.txt")
    assert result.read() == content


@pytest.mark.asyncio
async def test_local_storage_delete_removes_file(local_storage: LocalStorage, tmp_path):
    """LocalStorage.delete() should remove a stored file."""
    content = b"delete me"
    await local_storage.store("event1/todelete.txt", io.BytesIO(content), "text/plain")
    full_path = os.path.join(str(tmp_path), "event1/todelete.txt")
    assert os.path.exists(full_path)

    result = await local_storage.delete("event1/todelete.txt")
    assert result is True
    assert not os.path.exists(full_path)


@pytest.mark.asyncio
async def test_local_storage_delete_nonexistent_returns_false(
    local_storage: LocalStorage,
):
    """LocalStorage.delete() on a missing file should return False without raising."""
    result = await local_storage.delete("event1/doesnotexist.txt")
    assert result is False


@pytest.mark.asyncio
async def test_local_storage_exists_returns_true_when_file_present(
    local_storage: LocalStorage,
):
    """LocalStorage.exists() should return True after storing a file."""
    await local_storage.store("event1/exists.txt", io.BytesIO(b"data"), "text/plain")
    assert await local_storage.exists("event1/exists.txt") is True


@pytest.mark.asyncio
async def test_local_storage_exists_returns_false_when_missing(
    local_storage: LocalStorage,
):
    """LocalStorage.exists() should return False for a file that was never stored."""
    assert await local_storage.exists("event1/nope.txt") is False


@pytest.mark.asyncio
async def test_local_storage_get_url_returns_correct_format(
    local_storage: LocalStorage,
):
    """LocalStorage.get_url() should return a URL under /media/."""
    url = await local_storage.get_url("event1/photo.jpg")
    assert "/media/event1/photo.jpg" in url
    assert url.startswith("http")


@pytest.mark.asyncio
async def test_local_storage_get_size_returns_correct_size(
    local_storage: LocalStorage,
):
    """LocalStorage.get_size() should return the exact number of bytes stored."""
    content = b"size check content"
    await local_storage.store("event1/sizefile.txt", io.BytesIO(content), "text/plain")
    size = await local_storage.get_size("event1/sizefile.txt")
    assert size == len(content)


@pytest.mark.asyncio
async def test_local_storage_creates_nested_directories(
    local_storage: LocalStorage, tmp_path
):
    """LocalStorage.store() should create intermediate directories."""
    await local_storage.store(
        "deep/nested/dirs/file.bin", io.BytesIO(b"nested"), "application/octet-stream"
    )
    full_path = os.path.join(str(tmp_path), "deep/nested/dirs/file.bin")
    assert os.path.exists(full_path)
