"""Runtime settings. Credentials come from the environment only."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = ""
    cors_origins: str = "http://127.0.0.1:8765,http://localhost:8765"
    bobgo_base_url: str = "https://api.sandbox.bobgo.co.za/v2"
    bobgo_api_token: str = ""
    bobgo_timeout_seconds: float = 20
    auth_session_ttl_seconds: int = 43200
    auth_session_idle_seconds: int = 7200
    auth_login_max_failures: int = 5
    auth_login_window_seconds: int = 900

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_origins(cls, value: str) -> str:
        origins = [item.strip() for item in value.split(",") if item.strip()]
        if "*" in origins:
            raise ValueError("Wildcard CORS is not allowed.")
        return ",".join(origins)

    @field_validator("bobgo_base_url")
    @classmethod
    def sandbox_bobgo_only(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if normalized != "https://api.sandbox.bobgo.co.za/v2":
            raise ValueError("Bob Go must use the sandbox API.")
        return normalized

    @field_validator("bobgo_timeout_seconds")
    @classmethod
    def positive_bobgo_timeout(cls, value: float) -> float:
        if value <= 0 or value > 60:
            raise ValueError("Bob Go timeout must be greater than 0 and at most 60 seconds.")
        return value

    @field_validator("auth_session_ttl_seconds", "auth_session_idle_seconds", "auth_login_window_seconds")
    @classmethod
    def positive_auth_window(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Authentication time limits must be positive.")
        return value

    @field_validator("auth_login_max_failures")
    @classmethod
    def positive_login_limit(cls, value: int) -> int:
        if value < 1:
            raise ValueError("The login attempt limit must be at least 1.")
        return value

    def origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def cookie_secure(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
