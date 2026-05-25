from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str
    SECRET_KEY: str = "dev-secret-change-me-min-32-characters-long"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    ALLOWED_ORIGINS: str = "http://localhost:3100,http://localhost:3000"

    # File upload settings (C3c)
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024  # 10 MB

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def upload_path(self) -> Path:
        """Absolute path to the upload directory."""
        return Path(self.UPLOAD_DIR).resolve()


settings = Settings()
