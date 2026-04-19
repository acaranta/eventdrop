from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Admin
    admin_username: str = "admin"
    admin_password: str = "changeme"
    secret_key: str = "dev-secret-key-change-in-production"
    # Separate key for encrypting stored email credentials.
    # Must be set in production; defaults to a deterministic fallback only for development.
    encryption_key: str = ""

    # Database
    db_type: str = "sqlite"  # "sqlite" or "mysql"
    db_path: str = "/data/eventdrop.db"
    db_host: str = ""
    db_port: int = 3306
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""

    # Storage
    storage_type: str = "local"  # "local" or "s3"
    storage_local_path: str = "/data/media"
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_use_ssl: bool = True

    # OIDC
    oidc_enabled: bool = False
    oidc_provider_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_display_name: str = "Login with SSO"

    # Email ingestion
    email_ingestion_enabled: bool = True
    email_poll_interval_seconds: int = 120

    # Archive
    archive_temp_path: str = "/data/tmp"
    download_link_expiry_hours: int = 48
    download_warn_max_files: int = 500
    download_warn_max_size_mb: int = 1000

    # SMTP for sending emails
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls: bool = True   # STARTTLS on port 587
    smtp_ssl: bool = False  # SSL on port 465

    # App
    base_url: str = "http://localhost:8000"
    max_upload_size_mb: int = 500

    model_config = {"env_prefix": "EVENTDROP_"}

    def get_database_url(self) -> str:
        if self.db_type == "mysql":
            return f"mysql+aiomysql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
        return f"sqlite+aiosqlite:///{self.db_path}"

    def is_oidc_configured(self) -> bool:
        return (
            self.oidc_enabled
            and bool(self.oidc_provider_url)
            and bool(self.oidc_client_id)
            and bool(self.oidc_client_secret)
        )

    def get_fernet_key(self) -> bytes:
        """Return a 32-byte URL-safe base64-encoded key suitable for Fernet.

        Uses EVENTDROP_ENCRYPTION_KEY when set; falls back to deriving from
        secret_key so that existing deployments that never set the variable keep
        working without re-encrypting stored passwords.
        """
        import base64
        import hashlib
        source = self.encryption_key if self.encryption_key else self.secret_key
        return base64.urlsafe_b64encode(hashlib.sha256(source.encode()).digest())

    def is_smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)


settings = Settings()
