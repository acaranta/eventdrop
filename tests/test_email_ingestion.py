"""Tests for email ingestion utilities."""
import base64
import email
import hashlib
import io
import pytest
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.mime.text import MIMEText
from unittest.mock import AsyncMock, MagicMock, patch

from eventdrop.services.email_ingestion import (
    extract_media_from_email,
    decrypt_password,
    email_ingestion_loop,
)


def _make_email_with_image_attachment(
    sender: str = "sender@example.com",
    image_data: bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 20,  # minimal JPEG-like bytes
) -> email.message.Message:
    """Build a test email with a JPEG attachment."""
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = "event@example.com"
    msg["Subject"] = "Test photo upload"

    # Plain text body
    msg.attach(MIMEText("Please find my photo attached.", "plain"))

    # Image attachment
    img_part = MIMEImage(image_data, _subtype="jpeg")
    img_part.add_header("Content-Disposition", "attachment", filename="photo.jpg")
    msg.attach(img_part)

    return msg


def _encrypt_password(plaintext: str) -> str:
    """Helper that mirrors the encryption used in upsert_email_config."""
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(
        hashlib.sha256("test-secret-key-for-testing-only".encode()).digest()
    )
    f = Fernet(key)
    return f.encrypt(plaintext.encode()).decode()


class TestExtractMediaFromEmail:
    def test_extracts_image_attachment(self):
        """extract_media_from_email should return one entry for a JPEG attachment."""
        image_data = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        msg = _make_email_with_image_attachment(image_data=image_data)
        attachments = extract_media_from_email(msg)
        assert len(attachments) == 1
        att = attachments[0]
        assert att["mime_type"] == "image/jpeg"
        assert att["filename"] == "photo.jpg"
        assert att["data"] == image_data

    def test_returns_empty_for_text_only_email(self):
        """extract_media_from_email should return [] for an email with no media."""
        msg = MIMEText("Just a plain text email, no attachments.", "plain")
        attachments = extract_media_from_email(msg)
        assert attachments == []

    def test_generates_filename_when_none_provided(self):
        """A MIME part without a filename should get an auto-generated filename."""
        image_data = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        msg = MIMEMultipart()
        msg["From"] = "sender@example.com"
        img_part = MIMEImage(image_data, _subtype="jpeg")
        # No Content-Disposition / filename header
        msg.attach(img_part)
        attachments = extract_media_from_email(msg)
        assert len(attachments) == 1
        assert attachments[0]["filename"].startswith("email_attachment")

    def test_extracts_multiple_attachments(self):
        """extract_media_from_email should handle multiple image attachments."""
        msg = MIMEMultipart()
        msg["From"] = "multi@example.com"
        for i in range(3):
            img_part = MIMEImage(b"\x89PNG" + b"\x00" * 50, _subtype="png")
            img_part.add_header(
                "Content-Disposition", "attachment", filename=f"image{i}.png"
            )
            msg.attach(img_part)
        attachments = extract_media_from_email(msg)
        assert len(attachments) == 3


class TestDecryptPassword:
    def test_decrypt_roundtrip(self):
        """decrypt_password should recover the original plaintext."""
        plaintext = "super-secret-mail-password"
        encrypted = _encrypt_password(plaintext)
        result = decrypt_password(encrypted)
        assert result == plaintext

    def test_decrypt_different_passwords(self):
        """Different plaintexts encrypt and decrypt independently."""
        pw1 = "password_one"
        pw2 = "password_two"
        enc1 = _encrypt_password(pw1)
        enc2 = _encrypt_password(pw2)
        assert decrypt_password(enc1) == pw1
        assert decrypt_password(enc2) == pw2
        assert enc1 != enc2


class TestEmailIngestionLoop:
    @pytest.mark.asyncio
    async def test_loop_exits_cleanly_when_cancelled(self):
        """email_ingestion_loop should handle CancelledError gracefully."""
        import asyncio

        # Patch the database session to return no configs, and cancel quickly
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "eventdrop.services.email_ingestion.settings"
        ) as mock_settings, patch(
            "eventdrop.database.engine.AsyncSessionLocal",
            return_value=mock_session_cm,
        ):
            # Set a very short poll interval so the loop actually hits the sleep
            mock_settings.email_poll_interval_seconds = 0

            task = asyncio.create_task(email_ingestion_loop())
            # Give the loop a moment to start then cancel it
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass  # Expected — loop should propagate CancelledError

    @pytest.mark.asyncio
    async def test_loop_does_not_crash_with_no_configs(self):
        """email_ingestion_loop should complete a cycle without errors when no configs exist."""
        import asyncio

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "eventdrop.services.email_ingestion.settings"
        ) as mock_settings, patch(
            "eventdrop.database.engine.AsyncSessionLocal",
            return_value=mock_session_cm,
        ):
            mock_settings.email_poll_interval_seconds = 0

            task = asyncio.create_task(email_ingestion_loop())
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            # If we get here the loop didn't crash
