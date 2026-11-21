"""The settings' one outside call: on the server, read the secret named by GAWAH_SECRET_ID
from AWS Secrets Manager with the instance role. The secret is a JSON object of the same
names as .env (written by tools/deploy/push-secrets.sh). Nothing here logs a value."""

import json
import os
from functools import lru_cache

import boto3
from botocore.config import Config

SECRET_ID_ENV = "GAWAH_SECRET_ID"


@lru_cache
def read_secret(secret_id: str) -> dict[str, str]:
    """The secret's names and values. A failure stops the server: half its settings would be missing."""
    region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "us-west-2"
    client = boto3.client(
        "secretsmanager", region_name=region,
        # max_attempts counts the first try, so 2 means one retry.
        config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2, "mode": "standard"}),
    )
    try:
        text = client.get_secret_value(SecretId=secret_id)["SecretString"]
    except Exception as error:  # AWS's message names the secret and the permission, never a value
        raise RuntimeError(f"could not read the secret {secret_id} in {region}: {error}") from None
    try:
        values = json.loads(text)
    except ValueError:
        values = None
    if not isinstance(values, dict):
        raise RuntimeError(f"the secret {secret_id} is not a JSON object of settings")
    return {str(k): str(v) for k, v in values.items() if v is not None}
