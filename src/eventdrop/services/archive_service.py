import asyncio
import logging
from datetime import datetime

from eventdrop.config import settings

logger = logging.getLogger(__name__)


async def archive_cleanup_loop() -> None:
    """Background task that periodically removes expired archive files."""
    while True:
        try:
            await _cleanup_expired_archives()
        except asyncio.CancelledError:
            logger.info("Archive cleanup task cancelled.")
            raise
        except Exception as exc:
            logger.exception("Error during archive cleanup: %s", exc)

        # Check every minute
        await asyncio.sleep(60)


async def _cleanup_expired_archives() -> None:
    """Delete archive files whose expiry time has passed."""
    import os
    from sqlalchemy import select
    from eventdrop.database.engine import AsyncSessionLocal
    from eventdrop.database.models import ArchiveRequest

    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ArchiveRequest).where(
                ArchiveRequest.expires_at < now,
                ArchiveRequest.downloaded == False,  # noqa: E712
            )
        )
        expired = result.scalars().all()

        for archive in expired:
            if archive.file_path and os.path.exists(archive.file_path):
                try:
                    os.remove(archive.file_path)
                    logger.info("Deleted expired archive: %s", archive.file_path)
                except OSError as exc:
                    logger.warning("Could not delete archive %s: %s", archive.file_path, exc)

            archive.downloaded = True  # Mark as consumed to avoid re-processing
            session.add(archive)

        await session.commit()
