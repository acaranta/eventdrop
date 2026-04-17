import secrets
import string
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from eventdrop.database.models import Event, MediaFile, EventEmailConfig
import uuid


def generate_event_id(length: int = 8) -> str:
    """Generate a URL-friendly alphanumeric event ID using a CSPRNG."""
    chars = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


async def create_event(db: AsyncSession, owner_id: str, name: str,
                       description: Optional[str] = None,
                       is_gallery_public: bool = False,
                       allow_public_download: bool = False) -> Event:
    # Generate unique ID
    for _ in range(10):
        event_id = generate_event_id()
        result = await db.execute(select(Event).where(Event.id == event_id))
        if not result.scalar_one_or_none():
            break

    event = Event(
        id=event_id,
        name=name,
        description=description,
        owner_id=owner_id,
        is_gallery_public=is_gallery_public,
        allow_public_download=allow_public_download,
    )
    db.add(event)
    await db.flush()
    return event


async def get_event(db: AsyncSession, event_id: str) -> Optional[Event]:
    result = await db.execute(select(Event).where(Event.id == event_id))
    return result.scalar_one_or_none()


async def get_event_with_email_config(db: AsyncSession, event_id: str) -> Optional[Event]:
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Event)
        .options(selectinload(Event.email_config))
        .where(Event.id == event_id)
    )
    return result.scalar_one_or_none()


async def list_events_by_owner(db: AsyncSession, owner_id: str) -> list[Event]:
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Event)
        .options(selectinload(Event.email_config))
        .where(Event.owner_id == owner_id)
        .order_by(Event.created_at.desc())
    )
    return list(result.scalars().all())


async def list_all_events(db: AsyncSession) -> list[Event]:
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Event)
        .options(selectinload(Event.email_config), selectinload(Event.owner))
        .order_by(Event.created_at.desc())
    )
    return list(result.scalars().all())


async def update_event(db: AsyncSession, event_id: str, **kwargs) -> Optional[Event]:
    event = await get_event(db, event_id)
    if not event:
        return None
    for k, v in kwargs.items():
        setattr(event, k, v)
    event.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return event


async def delete_event(db: AsyncSession, event_id: str, storage) -> bool:
    """Delete event and all associated media from storage and DB."""
    from sqlalchemy import delete
    from eventdrop.database.models import ArchiveRequest, ProcessedEmail, EventEmailConfig, MediaFile

    event = await get_event(db, event_id)
    if not event:
        return False

    # Delete all media files from storage
    media_result = await db.execute(select(MediaFile).where(MediaFile.event_id == event_id))
    media_files = list(media_result.scalars().all())
    for mf in media_files:
        try:
            await storage.delete(mf.stored_path)
            if mf.thumb_path:
                await storage.delete(mf.thumb_path)
        except Exception:
            pass

    # Delete archive requests (clean up temp files)
    archive_result = await db.execute(select(ArchiveRequest).where(ArchiveRequest.event_id == event_id))
    archives = list(archive_result.scalars().all())
    for ar in archives:
        try:
            import os
            if os.path.exists(ar.file_path):
                os.remove(ar.file_path)
        except Exception:
            pass

    await db.execute(delete(ArchiveRequest).where(ArchiveRequest.event_id == event_id))
    await db.execute(delete(MediaFile).where(MediaFile.event_id == event_id))

    # Delete email config and associated processed emails
    email_result = await db.execute(select(EventEmailConfig).where(EventEmailConfig.event_id == event_id))
    email_config = email_result.scalar_one_or_none()
    if email_config:
        await db.execute(
            delete(ProcessedEmail).where(ProcessedEmail.event_email_config_id == email_config.id)
        )
        await db.delete(email_config)

    await db.delete(event)
    await db.flush()
    return True


async def get_event_stats(db: AsyncSession, event_id: str) -> dict:
    """Get stats for an event: media count, total size."""
    count_result = await db.execute(
        select(func.count(MediaFile.id)).where(MediaFile.event_id == event_id)
    )
    size_result = await db.execute(
        select(func.sum(MediaFile.file_size)).where(MediaFile.event_id == event_id)
    )
    return {
        "media_count": count_result.scalar() or 0,
        "total_size": size_result.scalar() or 0,
    }


async def upsert_email_config(db: AsyncSession, event_id: str, config_data: dict) -> EventEmailConfig:
    """Create or update email config for an event."""
    from eventdrop.config import settings as app_settings
    from cryptography.fernet import Fernet

    result = await db.execute(
        select(EventEmailConfig).where(EventEmailConfig.event_id == event_id)
    )
    config = result.scalar_one_or_none()

    # Encrypt password if provided
    password = config_data.pop("password", None)
    if password:
        key = app_settings.get_fernet_key()
        f = Fernet(key)
        config_data["password"] = f.encrypt(password.encode()).decode()
    elif config and not password:
        # Keep existing password — remove from update dict so it isn't cleared
        config_data.pop("password", None)

    if config is None:
        config = EventEmailConfig(id=str(uuid.uuid4()), event_id=event_id, **config_data)
        db.add(config)
    else:
        for k, v in config_data.items():
            setattr(config, k, v)
        config.updated_at = datetime.now(timezone.utc)

    await db.flush()
    return config
