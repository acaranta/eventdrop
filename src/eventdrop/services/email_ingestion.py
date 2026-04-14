import asyncio
import base64
import email
import email.policy
import hashlib
import imaplib
import io
import logging
import poplib
import uuid
from datetime import datetime, timezone
from email import message_from_bytes
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eventdrop.config import settings
from eventdrop.database.models import EventEmailConfig, ProcessedEmail
from eventdrop.services.media_service import store_media_file, ALLOWED_MIME_TYPES

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_VIDEO_MIMES = ALLOWED_MIME_TYPES


def decrypt_password(encrypted_password: str) -> str:
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    f = Fernet(key)
    return f.decrypt(encrypted_password.encode()).decode()


def get_filename_from_part(part) -> Optional[str]:
    filename = part.get_filename()
    if filename:
        # Decode RFC2047 encoded filename
        from email.header import decode_header
        decoded = decode_header(filename)
        parts = []
        for data, charset in decoded:
            if isinstance(data, bytes):
                parts.append(data.decode(charset or "utf-8", errors="replace"))
            else:
                parts.append(data)
        return "".join(parts)
    return None


def mime_type_to_extension(mime_type: str) -> str:
    mapping = {
        "image/jpeg": ".jpg", "image/png": ".png", "image/heic": ".heic",
        "image/heif": ".heif", "image/webp": ".webp", "image/gif": ".gif",
        "video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-msvideo": ".avi",
        "video/x-matroska": ".mkv", "video/webm": ".webm",
    }
    return mapping.get(mime_type, ".bin")


def extract_media_from_email(msg) -> list[dict]:
    """Extract all media attachments from an email message."""
    attachments = []
    for part in msg.walk():
        content_type = part.get_content_type()
        if content_type not in ALLOWED_IMAGE_VIDEO_MIMES:
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        filename = get_filename_from_part(part)
        if not filename:
            ext = mime_type_to_extension(content_type)
            filename = f"email_attachment{ext}"
        attachments.append({
            "filename": filename,
            "mime_type": content_type,
            "data": payload,
        })
    return attachments


async def poll_imap(config: EventEmailConfig, db: AsyncSession):
    """Poll an IMAP mailbox for new media."""
    from eventdrop.storage import get_storage
    storage = get_storage()

    password = decrypt_password(config.password)
    media_count = 0

    def imap_work():
        results = []
        if config.use_ssl:
            mail = imaplib.IMAP4_SSL(config.server_host, config.server_port)
        else:
            mail = imaplib.IMAP4(config.server_host, config.server_port)
        mail.login(config.username, password)
        mail.select("INBOX")
        _, msg_nums = mail.search(None, "UNSEEN")
        msg_list = msg_nums[0].split() if msg_nums[0] else []
        for num in msg_list:
            _, msg_data = mail.fetch(num, "(RFC822)")
            raw = msg_data[0][1]
            msg = message_from_bytes(raw)
            sender = email.utils.parseaddr(msg.get("From", ""))[1] or "unknown@unknown.com"
            attachments = extract_media_from_email(msg)
            for att in attachments:
                results.append({"sender": sender, "attachment": att})
            if config.delete_after_ingestion:
                mail.store(num, "+FLAGS", "\\Deleted")
            else:
                mail.store(num, "+FLAGS", "\\Seen")
        if config.delete_after_ingestion:
            mail.expunge()
        mail.logout()
        return results

    results = await asyncio.to_thread(imap_work)

    for item in results:
        try:
            await store_media_file(
                db=db,
                storage=storage,
                event_id=config.event_id,
                uploader_email=item["sender"],
                original_filename=item["attachment"]["filename"],
                file_data=item["attachment"]["data"],
                mime_type=item["attachment"]["mime_type"],
                source="email",
            )
            media_count += 1
        except Exception as e:
            logger.warning(f"Failed to store email attachment: {e}")

    return media_count


async def poll_pop3(config: EventEmailConfig, db: AsyncSession):
    """Poll a POP3 mailbox for new media."""
    from eventdrop.storage import get_storage
    storage = get_storage()

    password = decrypt_password(config.password)
    media_count = 0

    # Get already-processed UIDs
    result = await db.execute(
        select(ProcessedEmail).where(
            ProcessedEmail.event_email_config_id == config.id
        )
    )
    processed_uids = {pe.message_uid for pe in result.scalars().all()}

    def pop3_work():
        results = []
        if config.use_ssl:
            mail = poplib.POP3_SSL(config.server_host, config.server_port)
        else:
            mail = poplib.POP3(config.server_host, config.server_port)
        mail.user(config.username)
        mail.pass_(password)

        # Get UIDs via UIDL
        response, listings, _ = mail.uidl()
        uid_map = {}
        for listing in listings:
            if isinstance(listing, bytes):
                listing = listing.decode()
            parts = listing.split()
            if len(parts) >= 2:
                uid_map[parts[0]] = parts[1]

        to_delete = []
        for msg_num, uid in uid_map.items():
            if uid in processed_uids:
                continue
            response, lines, _ = mail.retr(int(msg_num))
            raw = b"\n".join(lines)
            msg = message_from_bytes(raw)
            sender = email.utils.parseaddr(msg.get("From", ""))[1] or "unknown@unknown.com"
            attachments = extract_media_from_email(msg)
            for att in attachments:
                results.append({"sender": sender, "attachment": att, "uid": uid})
            if config.delete_after_ingestion:
                to_delete.append(msg_num)

        for msg_num in to_delete:
            mail.dele(int(msg_num))
        mail.quit()
        return results

    results = await asyncio.to_thread(pop3_work)

    # Track which UIDs we've already recorded in this session to avoid
    # duplicate ProcessedEmail inserts when one message has multiple attachments.
    newly_recorded_uids: set[str] = set()

    for item in results:
        try:
            await store_media_file(
                db=db,
                storage=storage,
                event_id=config.event_id,
                uploader_email=item["sender"],
                original_filename=item["attachment"]["filename"],
                file_data=item["attachment"]["data"],
                mime_type=item["attachment"]["mime_type"],
                source="email",
            )
            media_count += 1
        except Exception as e:
            logger.warning(f"Failed to store email attachment: {e}")
            continue

        # Record message as processed only once per UID
        uid = item["uid"]
        if uid not in newly_recorded_uids:
            pe = ProcessedEmail(
                id=str(uuid.uuid4()),
                event_email_config_id=config.id,
                message_uid=uid,
            )
            db.add(pe)
            newly_recorded_uids.add(uid)

    await db.flush()
    return media_count


async def poll_mailbox(config: EventEmailConfig):
    """Poll a single mailbox configuration."""
    from eventdrop.database.engine import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        try:
            if config.protocol.lower() == "imap":
                count = await poll_imap(config, db)
            else:
                count = await poll_pop3(config, db)

            config.last_poll_at = datetime.now(timezone.utc)
            config.last_poll_status = "success"
            config.last_poll_error = None
            config.last_poll_media_count = count
            await db.commit()
            logger.info(f"Polled event {config.event_id}: {count} media files ingested.")
        except Exception as e:
            logger.error(f"Error polling mailbox for event {config.event_id}: {e}")
            try:
                config.last_poll_at = datetime.now(timezone.utc)
                config.last_poll_status = "error"
                config.last_poll_error = str(e)
                await db.commit()
            except Exception:
                pass


async def email_ingestion_loop():
    """Background task that polls all enabled email configurations."""
    from eventdrop.database.engine import AsyncSessionLocal

    while True:
        try:
            await asyncio.sleep(settings.email_poll_interval_seconds)
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(EventEmailConfig).where(EventEmailConfig.is_enabled == True)  # noqa: E712
                )
                configs = list(result.scalars().all())

            for config in configs:
                try:
                    await poll_mailbox(config)
                except Exception as e:
                    logger.error(f"Failed to poll mailbox for config {config.id}: {e}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Email ingestion loop error: {e}")
