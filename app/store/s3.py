"""S3 helper: upload a file, make a short-lived signed link. The bucket stays private.
Tests never call the service: signing a link is done locally, uploading is not."""

import asyncio

import boto3
from botocore.config import Config

from app.config import Settings


def _plain(value) -> str | None:
    return value.get_secret_value() if value else None


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
                # No keys (the server): boto3 uses the instance role.
                aws_access_key_id=_plain(s.aws_access_key_id),
                aws_secret_access_key=_plain(s.aws_secret_access_key),
                aws_session_token=_plain(s.aws_session_token),
                # max_attempts counts the first try, so 2 means one retry.
                # "virtual" puts the region in the host (bucket.s3.<region>.amazonaws.com), so a
                # signed link is answered directly. Without it the link goes to the global host,
                # which answers a new bucket with a redirect.
                config=Config(
                    connect_timeout=5, read_timeout=30, retries={"max_attempts": 2},
                    s3={"addressing_style": "virtual"},
                ),
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
