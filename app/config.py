"""Settings read from .env. Nothing here prints or logs a value.

A missing key never stops the server. A stream calls settings.require("...")
at the moment it needs the key, and gets a clear error if it is not set.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_ignore_empty=True, extra="ignore"
    )

    openai_api_key: SecretStr | None = None

    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    aws_session_token: SecretStr | None = None
    aws_default_region: str | None = None
    s3_bucket: str | None = None

    livekit_url: str | None = None
    livekit_api_key: SecretStr | None = None
    livekit_api_secret: SecretStr | None = None

    twilio_account_sid: SecretStr | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_whatsapp_number: str | None = Field(default=None, repr=False)
    twilio_phone_number: str | None = Field(default=None, repr=False)

    sage_api_key: SecretStr | None = None

    verified_numbers: str = Field(default="", repr=False)
    public_base_url: str | None = None

    judge_mode: Literal["live", "wrapup"] = "live"
    reply_timeout_seconds: int = 120

    meta_whatsapp_token: SecretStr | None = None
    meta_phone_number_id: str | None = None
    meta_verify_token: SecretStr | None = None

    database_path: str = str(ROOT / "gawah.db")
    dev_routes: bool = True

    def require(self, key: str) -> str:
        """The value of a setting as a plain string, or an error naming the missing key."""
        value = getattr(self, key)
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if value is None or value == "":
            raise RuntimeError(f"{key.upper()} is not set in .env")
        return str(value)

    @property
    def verified_number_list(self) -> list[str]:
        """The only numbers Gawah may message or call."""
        return [n.strip() for n in self.verified_numbers.split(",") if n.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
