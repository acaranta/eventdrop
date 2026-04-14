from eventdrop.storage.base import StorageBackend
from eventdrop.config import settings


def get_storage() -> StorageBackend:
    if settings.storage_type == "s3":
        from eventdrop.storage.s3 import S3Storage
        return S3Storage()
    from eventdrop.storage.local import LocalStorage
    return LocalStorage()
