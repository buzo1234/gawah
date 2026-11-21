"""The whatsapp stream's own settings, on top of app/config.py: which provider sends, and
Meta's app secret. Read from the same .env. They live here so app/config.py stays as it is;
if the shared settings gain these fields, they are used as they are."""

from typing import Literal

from pydantic import SecretStr

from app.config import Settings


class WhatsAppSettings(Settings):
    whatsapp_provider: Literal["twilio", "meta"] = "twilio"
    meta_app_secret: SecretStr | None = None
    meta_graph_version: str = "v27.0"  # the latest Graph version, Nov 2026


def whatsapp_settings(settings: Settings) -> WhatsAppSettings:
    """The shared settings with this stream's fields added. Every shared value is kept as
    given (a test's settings stay a test's); the added fields come from the shell or .env."""
    if isinstance(settings, WhatsAppSettings):
        return settings
    return WhatsAppSettings(**{name: getattr(settings, name) for name in Settings.model_fields})
