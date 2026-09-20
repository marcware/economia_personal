from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    database_path: Path = BASE_DIR / "data" / "economia.db"

    enablebanking_application_id: str | None = None
    enablebanking_private_key_path: Path | None = None
    enablebanking_api_base: str = "https://api.enablebanking.com"
    enablebanking_redirect_url: str = "https://localhost:8000/conexiones/callback"

    @model_validator(mode="after")
    def _resolve_relative_paths(self) -> "Settings":
        if self.enablebanking_private_key_path and not self.enablebanking_private_key_path.is_absolute():
            self.enablebanking_private_key_path = BASE_DIR / self.enablebanking_private_key_path
        return self


settings = Settings()
