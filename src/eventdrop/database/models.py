import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    String,
    Boolean,
    Integer,
    BigInteger,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    oidc_subject: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)

    # Relationships
    events: Mapped[List["Event"]] = relationship("Event", back_populates="owner")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    is_gallery_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allow_public_download: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="events")
    media_files: Mapped[List["MediaFile"]] = relationship("MediaFile", back_populates="event")
    email_config: Mapped[Optional["EventEmailConfig"]] = relationship(
        "EventEmailConfig", back_populates="event", uselist=False
    )
    archive_requests: Mapped[List["ArchiveRequest"]] = relationship(
        "ArchiveRequest", back_populates="event"
    )


class EventEmailConfig(Base):
    __tablename__ = "event_email_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(
        String(8), ForeignKey("events.id"), unique=True, nullable=False
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    protocol: Mapped[str] = mapped_column(String(10), nullable=False, default="imap")
    server_host: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    server_port: Mapped[int] = mapped_column(Integer, nullable=False, default=993)
    use_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    password: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    email_address: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    delete_after_ingestion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_poll_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_poll_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_poll_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_poll_media_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="email_config")
    processed_emails: Mapped[List["ProcessedEmail"]] = relationship(
        "ProcessedEmail", back_populates="email_config"
    )


class MediaFile(Base):
    __tablename__ = "media_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(8), ForeignKey("events.id"), nullable=False)
    uploader_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    thumb_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    file_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="upload")
    upload_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="media_files")


class UploaderSession(Base):
    __tablename__ = "uploader_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class ArchiveRequest(Base):
    __tablename__ = "archive_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(8), ForeignKey("events.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    downloaded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="archive_requests")


class ProcessedEmail(Base):
    __tablename__ = "processed_emails"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_email_config_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("event_email_configs.id"), nullable=False
    )
    message_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("event_email_config_id", "message_uid", name="uq_processed_email"),
    )

    # Relationships
    email_config: Mapped["EventEmailConfig"] = relationship(
        "EventEmailConfig", back_populates="processed_emails"
    )
