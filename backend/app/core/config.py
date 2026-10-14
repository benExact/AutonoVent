"""Runtime settings. Credentials come from the environment only."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = ""
    cors_origins: str = "http://127.0.0.1:8765,http://localhost:8765"

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_origins(cls, value: str) -> str:
        origins = [item.strip() for item in value.split(",") if item.strip()]
        if "*" in origins:
            raise ValueError("Wildcard CORS is not allowed.")
        return ",".join(origins)

    def origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
