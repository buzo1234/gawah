"""S3 helper: upload a file, make a short-lived signed link. The bucket stays private.
Tests never call this."""

import asyncio

import boto3
from botocore.config import Config

from app.config import Settings


class S3:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None

    def _s3(self):
        if self._client is None:
            s = self._settings
            self._client = boto3.client(
                "s3",
                region_name=s.require("aws_default_region"),
                aws_access_key_id=s.require("aws_access_key_id"),
                aws_secret_access_key=s.require("aws_secret_access_key"),
                aws_session_token=s.aws_session_token.get_secret_value() if s.aws_session_token else None,
                # max_attempts counts the first try, so 2 means one retry.
                config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}),
            )
        return self._client

    async def upload(self, path: str, key: str, content_type: str | None = None) -> str:
        """Upload a local file and return its key."""
        extra = {"ContentType": content_type} if content_type else None
        bucket = self._settings.require("s3_bucket")
        await asyncio.to_thread(self._s3().upload_file, path, bucket, key, ExtraArgs=extra)
        return key

    async def signed_url(self, key: str, expires_seconds: int = 900) -> str:
        """A link to one object that stops working after expires_seconds."""
        return await asyncio.to_thread(
            self._s3().generate_presigned_url,
            "get_object",
            Params={"Bucket": self._settings.require("s3_bucket"), "Key": key},
            ExpiresIn=expires_seconds,
        )
