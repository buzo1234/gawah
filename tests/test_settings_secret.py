"""Settings on the server: the secret named by GAWAH_SECRET_ID, between the environment and .env."""

import json

import pytest

from app import secret_store
from app.config import Settings
from app.whatsapp.settings import WhatsAppSettings

SECRET = {
    "OPENAI_API_KEY": "sk-from-secret",
    "S3_BUCKET": "bucket-from-secret",
    "REPLY_TIMEOUT_SECONDS": "30",
    "DEV_ROUTES": "false",
    "ACCESS_KEY": "key-from-secret",
    "META_APP_SECRET": "meta-from-secret",
    "SOMETHING_ELSE": "ignored",
}


@pytest.fixture
def dotenv(tmp_path):
    path = tmp_path / ".env"
    path.write_text("OPENAI_API_KEY=sk-from-dotenv\nPUBLIC_BASE_URL=https://dotenv.example\nS3_BUCKET=bucket-from-dotenv\n")
    return path


@pytest.fixture
def secret(monkeypatch):
    asked = []

    def read(secret_id):
        asked.append(secret_id)
        return SECRET

    monkeypatch.setattr(secret_store, "read_secret", read)
    return asked


def test_the_environment_wins_over_the_secret_and_the_secret_over_dotenv(monkeypatch, dotenv, secret):
    monkeypatch.setenv("GAWAH_SECRET_ID", "gawah/prod")
    monkeypatch.setenv("S3_BUCKET", "bucket-from-env")
    s = Settings(_env_file=dotenv)
    assert secret and set(secret) == {"gawah/prod"}
    assert s.require("openai_api_key") == "sk-from-secret"  # secret over .env
    assert s.s3_bucket == "bucket-from-env"  # environment over secret
    assert s.public_base_url == "https://dotenv.example"  # only in .env
    assert s.reply_timeout_seconds == 30 and s.dev_routes is False  # typed from the secret's strings
    assert s.require("access_key") == "key-from-secret"
    assert Settings(_env_file=dotenv, s3_bucket="given").s3_bucket == "given"  # values in code win
    assert WhatsAppSettings(_env_file=dotenv).require("meta_app_secret") != "meta-from-secret"  # conftest's env wins
    monkeypatch.delenv("META_APP_SECRET")
    assert WhatsAppSettings(_env_file=dotenv).require("meta_app_secret") == "meta-from-secret"


def test_no_secret_id_means_no_aws_call(monkeypatch, dotenv, secret):
    s = Settings(_env_file=dotenv)
    assert secret == []
    assert s.require("openai_api_key") == "sk-from-dotenv" and s.access_key is None


class FakeSecrets:
    def __init__(self, text):
        self.text = text

    def get_secret_value(self, SecretId):
        return {"SecretString": self.text}


def test_the_client_has_a_timeout_and_one_retry_and_reads_json(monkeypatch):
    made = []

    def client(service, region_name, config):
        made.append((service, region_name, config))
        return FakeSecrets(json.dumps({"OPENAI_API_KEY": "sk-x", "EMPTY": None}))

    monkeypatch.setattr(secret_store.boto3, "client", client)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    secret_store.read_secret.cache_clear()
    assert secret_store.read_secret("gawah/prod") == {"OPENAI_API_KEY": "sk-x"}
    secret_store.read_secret("gawah/prod")
    [(service, region, config)] = made  # read once, then cached
    assert service == "secretsmanager" and region == "us-west-2"
    assert config.retries["max_attempts"] == 2 and config.connect_timeout == 5 and config.read_timeout == 10

    monkeypatch.setattr(secret_store.boto3, "client", lambda *a, **k: FakeSecrets("OPENAI_API_KEY=sk-not-json"))
    secret_store.read_secret.cache_clear()
    with pytest.raises(RuntimeError, match="not a JSON object") as error:
        secret_store.read_secret("gawah/prod")
    assert "sk-not-json" not in str(error.value)
    secret_store.read_secret.cache_clear()
