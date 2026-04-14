from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Admin
    admin_username: str = "admin"
    admin_password: str = "changeme"
    secret_key: str = "dev-secret-key-change-in-production"

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
    archive_expiry_minutes: int = 15

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


settings = Settings()
