import os
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import aiofiles
import aiofiles.os

from eventdrop.config import settings
from eventdrop.storage.base import StorageBackend


class LocalStorage(StorageBackend):
    """Storage backend that persists files on the local filesystem."""

    def _full_path(self, path: str) -> str:
        return os.path.join(settings.storage_local_path, path)

    async def store(self, path: str, file: BinaryIO, content_type: str) -> str:
        full_path = self._full_path(path)
        # Ensure parent directories exist
        await aiofiles.os.makedirs(os.path.dirname(full_path), exist_ok=True)

        data = file.read() if hasattr(file, "read") else file

        async with aiofiles.open(full_path, "wb") as f:
            await f.write(data)

        return path

    async def retrieve(self, path: str) -> BinaryIO:
        full_path = self._full_path(path)
        async with aiofiles.open(full_path, "rb") as f:
            data = await f.read()
        return BytesIO(data)

    async def delete(self, path: str) -> bool:
        full_path = self._full_path(path)
        try:
            await aiofiles.os.remove(full_path)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            return False

    async def exists(self, path: str) -> bool:
        full_path = self._full_path(path)
        return os.path.exists(full_path)

    async def get_url(self, path: str, expires: int = 3600) -> str:
        # Local storage serves via the /media/ route
        return f"{settings.base_url}/media/{path}"

    async def get_size(self, path: str) -> int:
        full_path = self._full_path(path)
        stat = await aiofiles.os.stat(full_path)
        return stat.st_size
