import asyncio
import logging

from eventdrop.config import settings

logger = logging.getLogger(__name__)


async def email_ingestion_loop() -> None:
    """Background task that periodically polls configured email accounts for new media."""
    while True:
        try:
            await _poll_all_email_configs()
        except asyncio.CancelledError:
            logger.info("Email ingestion task cancelled.")
            raise
        except Exception as exc:
            logger.exception("Error during email ingestion: %s", exc)

        await asyncio.sleep(settings.email_poll_interval_seconds)


async def _poll_all_email_configs() -> None:
    """Fetch all enabled email configs and ingest any new messages."""
    from sqlalchemy import select
    from eventdrop.database.engine import AsyncSessionLocal
    from eventdrop.database.models import EventEmailConfig

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(EventEmailConfig).where(EventEmailConfig.is_enabled == True)  # noqa: E712
        )
        configs = result.scalars().all()

    for config in configs:
        try:
            await _ingest_email_config(config)
        except Exception as exc:
            logger.exception(
                "Error ingesting emails for config %s: %s", config.id, exc
            )


async def _ingest_email_config(config) -> None:
    """Poll a single email config for new attachments. Full implementation pending."""
    logger.debug("Polling email config %s (%s)", config.id, config.email_address)
    # Full IMAP/POP3 ingestion logic will be implemented here.
