import hashlib
import io
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, BinaryIO

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from eventdrop.database.models import MediaFile, UploaderSession
from eventdrop.storage.base import StorageBackend


def compute_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def email_hash(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()[:8]


def build_storage_path(event_id: str, uploader_email: str,
                       original_filename: str,
                       file_datetime: Optional[datetime] = None,
                       prefix: str = "") -> str:
    """Build the canonical storage path for a media file."""
    email_dir = email_hash(uploader_email)
    dt = file_datetime or datetime.now(timezone.utc)
    dt_str = dt.strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}{dt_str}_{original_filename}"
    return f"{event_id}/{email_dir}/{filename}"


def extract_exif_datetime(data: bytes, mime_type: str) -> Optional[datetime]:
    """Extract datetime from image EXIF data."""
    if not mime_type.startswith("image/"):
        return None
    try:
        import exifread
        tags = exifread.process_file(io.BytesIO(data), stop_tag="DateTimeOriginal", details=False)
        tag = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
        if tag:
            return datetime.strptime(str(tag), "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        pass
    return None


def generate_thumbnail(data: bytes, mime_type: str) -> Optional[bytes]:
    """Generate a thumbnail for an image. Returns None for videos."""
    if not mime_type.startswith("image/"):
        return None
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.thumbnail((400, 400))
        # Convert RGBA/P to RGB for JPEG output
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return None


async def store_media_file(
    db: AsyncSession,
    storage: StorageBackend,
    event_id: str,
    uploader_email: str,
    original_filename: str,
    file_data: bytes,
    mime_type: str,
    source: str = "upload",
) -> MediaFile:
    """Store a media file and create/update the DB record."""
    file_datetime = extract_exif_datetime(file_data, mime_type)
    stored_path = build_storage_path(event_id, uploader_email, original_filename, file_datetime)
    thumb_path = build_storage_path(event_id, uploader_email, original_filename, file_datetime, prefix="thumb_")

    # Check for existing record (overwrite logic)
    result = await db.execute(
        select(MediaFile).where(
            MediaFile.event_id == event_id,
            MediaFile.uploader_email == uploader_email,
            MediaFile.original_filename == original_filename,
        )
    )
    existing = result.scalar_one_or_none()

    # Store file
    await storage.store(stored_path, io.BytesIO(file_data), mime_type)

    # Generate and store thumbnail
    thumb_data = generate_thumbnail(file_data, mime_type)
    stored_thumb_path = None
    if thumb_data:
        await storage.store(thumb_path, io.BytesIO(thumb_data), "image/jpeg")
        stored_thumb_path = thumb_path

    checksum = compute_checksum(file_data)

    if existing:
        # Delete old storage files if paths changed
        if existing.stored_path != stored_path:
            try:
                await storage.delete(existing.stored_path)
            except Exception:
                pass
        if existing.thumb_path and existing.thumb_path != stored_thumb_path:
            try:
                await storage.delete(existing.thumb_path)
            except Exception:
                pass
        existing.stored_path = stored_path
        existing.thumb_path = stored_thumb_path
        existing.file_size = len(file_data)
        existing.mime_type = mime_type
        existing.file_datetime = file_datetime
        existing.uploaded_at = datetime.now(timezone.utc)
        existing.checksum = checksum
        existing.source = source
        await db.flush()
        return existing
    else:
        media_file = MediaFile(
            id=str(uuid.uuid4()),
            event_id=event_id,
            uploader_email=uploader_email,
            original_filename=original_filename,
            stored_path=stored_path,
            thumb_path=stored_thumb_path,
            file_size=len(file_data),
            mime_type=mime_type,
            file_datetime=file_datetime,
            checksum=checksum,
            source=source,
        )
        db.add(media_file)
        await db.flush()
        return media_file


async def delete_media_file(db: AsyncSession, storage: StorageBackend, media_id: str) -> bool:
    """Delete a media file from storage and DB."""
    result = await db.execute(select(MediaFile).where(MediaFile.id == media_id))
    mf = result.scalar_one_or_none()
    if not mf:
        return False
    try:
        await storage.delete(mf.stored_path)
    except Exception:
        pass
    if mf.thumb_path:
        try:
            await storage.delete(mf.thumb_path)
        except Exception:
            pass
    await db.delete(mf)
    await db.flush()
    return True


async def list_event_media(db: AsyncSession, event_id: str) -> list[MediaFile]:
    result = await db.execute(
        select(MediaFile)
        .where(MediaFile.event_id == event_id)
        .order_by(MediaFile.uploaded_at.desc())
    )
    return list(result.scalars().all())


async def get_or_create_uploader_session(db: AsyncSession, email: str) -> UploaderSession:
    """Create a new uploader session for the given email."""
    import secrets
    token = secrets.token_urlsafe(32)
    session = UploaderSession(
        id=str(uuid.uuid4()),
        email=email,
        token=token,
    )
    db.add(session)
    await db.flush()
    return session


async def get_uploader_by_token(db: AsyncSession, token: str) -> Optional[UploaderSession]:
    result = await db.execute(
        select(UploaderSession).where(UploaderSession.token == token)
    )
    session = result.scalar_one_or_none()
    if session:
        session.last_used_at = datetime.now(timezone.utc)
        await db.flush()
    return session


ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/heic", "image/heif",
    "image/webp", "image/gif",
    "video/mp4", "video/quicktime", "video/x-msvideo",
    "video/x-matroska", "video/webm",
}
