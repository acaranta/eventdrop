from abc import ABC, abstractmethod
from typing import BinaryIO, Optional


class StorageBackend(ABC):
    @abstractmethod
    async def store(self, path: str, file: BinaryIO, content_type: str) -> str: ...

    @abstractmethod
    async def retrieve(self, path: str) -> BinaryIO: ...

    @abstractmethod
    async def delete(self, path: str) -> bool: ...

    @abstractmethod
    async def exists(self, path: str) -> bool: ...

    @abstractmethod
    async def get_url(self, path: str, expires: int = 3600) -> str: ...

    @abstractmethod
    async def get_size(self, path: str) -> int: ...
