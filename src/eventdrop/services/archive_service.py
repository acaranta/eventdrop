import asyncio
import logging
import os
import secrets
import shutil
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eventdrop.config import settings
from eventdrop.database.models import ArchiveRequest, MediaFile

logger = logging.getLogger(__name__)

ITEMS_PER_ARCHIVE = 100


async def enqueue_archive_batch(
    db: AsyncSession,
    event_id: str,
    media_ids: List[str],
    event_name: str,
) -> Tuple[List[ArchiveRequest], str]:
    """Split media_ids into chunks, create all DB records upfront, then build them sequentially."""
    chunks = [media_ids[i:i + ITEMS_PER_ARCHIVE] for i in range(0, len(media_ids), ITEMS_PER_ARCHIVE)]
    batch_id = str(uuid.uuid4())
    total_parts = len(chunks)
    archives = []
    chunk_map = []  # (archive_id, media_ids) pairs for the sequential task
    for idx, chunk in enumerate(chunks):
        archive = await enqueue_archive(
            db, event_id, chunk, event_name,
            batch_id=batch_id, part_index=idx, total_parts=total_parts,
            spawn_task=False,
        )
        archives.append(archive)
        chunk_map.append((archive.id, event_id, chunk, event_name))

    asyncio.create_task(_build_batch_sequential(chunk_map))
    return archives, batch_id


async def _build_batch_sequential(chunk_map: List[Tuple[str, str, List[str], str]]) -> None:
    """Build each archive in the batch one at a time."""
    for archive_id, event_id, media_ids, event_name in chunk_map:
        await _build_archive_task(archive_id, event_id, media_ids, event_name)


async def enqueue_archive(
    db: AsyncSession,
    event_id: str,
    media_ids: List[str],
    event_name: str,
    batch_id: str = None,
    part_index: int = 0,
    total_parts: int = 1,
    spawn_task: bool = True,
) -> ArchiveRequest:
    """Create a pending ArchiveRequest and optionally launch a background task to build the ZIP."""
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
        batch_id=batch_id,
        part_index=part_index,
        total_parts=total_parts,
    )
    db.add(archive_req)
    await db.commit()

    if spawn_task:
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
    tmp_dir = None
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(ArchiveRequest).where(ArchiveRequest.id == archive_id)
            )
            archive = result.scalar_one()
            archive.status = "processing"
            archive.phase = "retrieving"
            await db.commit()
            logger.info(f"Building archive {archive_id} for event {event_id}")

            # Re-check: admin may have cancelled while we were starting
            await db.refresh(archive)
            if archive.status == "cancelled":
                logger.info(f"Archive {archive_id} was cancelled before build started")
                return

            storage = get_storage()

            result = await db.execute(
                select(MediaFile).where(
                    MediaFile.id.in_(media_ids),
                    MediaFile.event_id == event_id,
                )
            )
            media_files = list(result.scalars().all())

            # Stage 1: retrieve each file to a temp dir on disk (one file in RAM at a time)
            os.makedirs(settings.archive_temp_path, exist_ok=True)
            tmp_dir = os.path.join(settings.archive_temp_path, f"tmp_{archive_id}")
            os.makedirs(tmp_dir, exist_ok=True)

            file_entries = []  # (disk_path, arcname) pairs for ZIP assembly
            for mf in media_files:
                try:
                    file_obj = await storage.retrieve(mf.stored_path)
                    dt = mf.file_datetime or mf.uploaded_at
                    prefix = dt.strftime("%Y-%m-%d_%H%M%S_") if dt else ""
                    arcname = f"{prefix}{mf.original_filename}"
                    dest_path = os.path.join(tmp_dir, arcname)
                    with open(dest_path, "wb") as f:
                        f.write(file_obj.read())
                    file_entries.append((dest_path, arcname))
                except Exception as e:
                    logger.warning(f"Could not retrieve {mf.stored_path}: {e}")

            # Stage 2: update phase to archiving, then build ZIP from disk
            result = await db.execute(
                select(ArchiveRequest).where(ArchiveRequest.id == archive_id)
            )
            archive = result.scalar_one()
            archive.phase = "archiving"
            await db.commit()

            part_suffix = f"_part{archive.part_index + 1}" if archive.total_parts > 1 else ""
            zip_filename = (
                f"{event_name.replace(' ', '_')}_"
                f"{datetime.now(timezone.utc).strftime('%Y%m%d')}_"
                f"{len(file_entries)}files{part_suffix}.zip"
            )
            zip_path = os.path.join(
                settings.archive_temp_path, f"{uuid.uuid4()}_{zip_filename}"
            )

            def make_zip():
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for disk_path, arcname in file_entries:
                        zf.write(disk_path, arcname=arcname)
                return os.path.getsize(zip_path)

            zip_size = await asyncio.to_thread(make_zip)

            # Stage 3: clean up temp dir, mark ready
            shutil.rmtree(tmp_dir, ignore_errors=True)
            tmp_dir = None

            result = await db.execute(
                select(ArchiveRequest).where(ArchiveRequest.id == archive_id)
            )
            archive = result.scalar_one()
            archive.file_path = zip_path
            archive.file_count = len(file_entries)
            archive.file_size = zip_size
            archive.status = "ready"
            archive.phase = None
            await db.commit()
            logger.info(f"Archive {archive_id} ready: {zip_path} ({zip_size} bytes)")

        except Exception as e:
            logger.error(f"Archive {archive_id} failed: {e}")
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
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
                archive.phase = None
                archive.error_message = str(e)
                await db.commit()
            except Exception as db_err:
                logger.error(f"Could not update archive {archive_id} to failed: {db_err}")


async def get_archive_by_token(db: AsyncSession, token: str):
    result = await db.execute(
        select(ArchiveRequest).where(ArchiveRequest.token == token)
    )
    return result.scalar_one_or_none()


async def get_archives_by_batch_id(db: AsyncSession, batch_id: str) -> List[ArchiveRequest]:
    result = await db.execute(
        select(ArchiveRequest)
        .where(ArchiveRequest.batch_id == batch_id)
        .order_by(ArchiveRequest.part_index)
    )
    return list(result.scalars().all())


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
