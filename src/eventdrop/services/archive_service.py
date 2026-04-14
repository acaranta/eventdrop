import asyncio
import logging
import os
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eventdrop.config import settings
from eventdrop.database.models import ArchiveRequest, MediaFile
from eventdrop.storage.base import StorageBackend

logger = logging.getLogger(__name__)


async def create_archive(
    db: AsyncSession,
    storage: StorageBackend,
    event_id: str,
    media_ids: List[str],
    event_name: str,
) -> ArchiveRequest:
    """Generate a ZIP archive of selected media files and return an ArchiveRequest."""
    import uuid

    # Fetch matching media files
    result = await db.execute(
        select(MediaFile).where(
            MediaFile.id.in_(media_ids),
            MediaFile.event_id == event_id,
        )
    )
    media_files = list(result.scalars().all())

    # Collect file data asynchronously before entering the thread
    file_data_list = []
    for mf in media_files:
        try:
            file_obj = await storage.retrieve(mf.stored_path)
            file_data_list.append((mf.original_filename, file_obj.read()))
        except Exception as e:
            logger.warning(f"Could not retrieve {mf.stored_path}: {e}")

    os.makedirs(settings.archive_temp_path, exist_ok=True)
    zip_filename = (
        f"{event_name.replace(' ', '_')}_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d')}_"
        f"{len(file_data_list)}files.zip"
    )
    zip_path = os.path.join(settings.archive_temp_path, f"{uuid.uuid4()}_{zip_filename}")

    def make_zip():
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename, data in file_data_list:
                zf.writestr(filename, data)
        return os.path.getsize(zip_path)

    zip_size = await asyncio.to_thread(make_zip)

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.archive_expiry_minutes)

    archive_req = ArchiveRequest(
        id=str(uuid.uuid4()),
        event_id=event_id,
        token=token,
        file_path=zip_path,
        file_count=len(file_data_list),
        file_size=zip_size,
        expires_at=expires_at,
    )
    db.add(archive_req)
    await db.flush()
    return archive_req


async def get_archive_by_token(db: AsyncSession, token: str):
    result = await db.execute(
        select(ArchiveRequest).where(ArchiveRequest.token == token)
    )
    return result.scalar_one_or_none()


async def archive_cleanup_loop():
    """Background task to clean up expired archive files."""
    from eventdrop.database.engine import AsyncSessionLocal
    from sqlalchemy import delete

    while True:
        try:
            await asyncio.sleep(300)  # Run every 5 minutes
            async with AsyncSessionLocal() as db:
                now = datetime.now(timezone.utc)
                result = await db.execute(
                    select(ArchiveRequest).where(ArchiveRequest.expires_at < now)
                )
                expired = list(result.scalars().all())
                for ar in expired:
                    try:
                        if os.path.exists(ar.file_path):
                            os.remove(ar.file_path)
                    except Exception as e:
                        logger.warning(f"Failed to delete expired archive {ar.file_path}: {e}")
                    await db.delete(ar)
                if expired:
                    await db.commit()
                    logger.info(f"Cleaned up {len(expired)} expired archives.")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Archive cleanup error: {e}")
