import asyncio
import logging
import os
import secrets
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eventdrop.config import settings
from eventdrop.database.models import ArchiveRequest, MediaFile

logger = logging.getLogger(__name__)


async def enqueue_archive(
    db: AsyncSession,
    event_id: str,
    media_ids: List[str],
    event_name: str,
) -> ArchiveRequest:
    """Create a pending ArchiveRequest and launch a background task to build the ZIP."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.download_link_expiry_hours)
    archive_id = str(uuid.uuid4())

    archive_req = ArchiveRequest(
        id=archive_id,
        event_id=event_id,
        token=token,
        file_path=None,
        file_count=0,
        file_size=None,
        status="pending",
        expires_at=expires_at,
    )
    db.add(archive_req)
    await db.commit()

    asyncio.create_task(_build_archive_task(archive_id, event_id, media_ids, event_name))
    return archive_req


async def _build_archive_task(
    archive_id: str,
    event_id: str,
    media_ids: List[str],
    event_name: str,
) -> None:
    from eventdrop.database.engine import AsyncSessionLocal
    from eventdrop.storage import get_storage

    zip_path = None
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(ArchiveRequest).where(ArchiveRequest.id == archive_id)
            )
            archive = result.scalar_one()
            archive.status = "processing"
            await db.commit()
            logger.info(f"Building archive {archive_id} for event {event_id}")

            storage = get_storage()

            result = await db.execute(
                select(MediaFile).where(
                    MediaFile.id.in_(media_ids),
                    MediaFile.event_id == event_id,
                )
            )
            media_files = list(result.scalars().all())

            file_data_list = []
            for mf in media_files:
                try:
                    file_obj = await storage.retrieve(mf.stored_path)
                    dt = mf.file_datetime or mf.uploaded_at
                    prefix = dt.strftime("%Y-%m-%d_%H%M%S_") if dt else ""
                    file_data_list.append((f"{prefix}{mf.original_filename}", file_obj.read()))
                except Exception as e:
                    logger.warning(f"Could not retrieve {mf.stored_path}: {e}")

            os.makedirs(settings.archive_temp_path, exist_ok=True)
            zip_filename = (
                f"{event_name.replace(' ', '_')}_"
                f"{datetime.now(timezone.utc).strftime('%Y%m%d')}_"
                f"{len(file_data_list)}files.zip"
            )
            zip_path = os.path.join(
                settings.archive_temp_path, f"{uuid.uuid4()}_{zip_filename}"
            )

            def make_zip():
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for filename, data in file_data_list:
                        zf.writestr(filename, data)
                return os.path.getsize(zip_path)

            zip_size = await asyncio.to_thread(make_zip)

            result = await db.execute(
                select(ArchiveRequest).where(ArchiveRequest.id == archive_id)
            )
            archive = result.scalar_one()
            archive.file_path = zip_path
            archive.file_count = len(file_data_list)
            archive.file_size = zip_size
            archive.status = "ready"
            await db.commit()
            logger.info(f"Archive {archive_id} ready: {zip_path} ({zip_size} bytes)")

        except Exception as e:
            logger.error(f"Archive {archive_id} failed: {e}")
            try:
                if zip_path and os.path.exists(zip_path):
                    os.remove(zip_path)
            except Exception:
                pass
            try:
                result = await db.execute(
                    select(ArchiveRequest).where(ArchiveRequest.id == archive_id)
                )
                archive = result.scalar_one()
                archive.status = "failed"
                archive.error_message = str(e)
                await db.commit()
            except Exception as db_err:
                logger.error(f"Could not update archive {archive_id} to failed: {db_err}")


async def get_archive_by_token(db: AsyncSession, token: str):
    result = await db.execute(
        select(ArchiveRequest).where(ArchiveRequest.token == token)
    )
    return result.scalar_one_or_none()


async def archive_cleanup_loop():
    """Background task to clean up expired archive files."""
    from eventdrop.database.engine import AsyncSessionLocal

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
                        if ar.file_path and os.path.exists(ar.file_path):
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
