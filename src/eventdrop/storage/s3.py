import asyncio
from io import BytesIO
from typing import BinaryIO

import boto3
from botocore.exceptions import ClientError

from eventdrop.config import settings
from eventdrop.storage.base import StorageBackend


class S3Storage(StorageBackend):
    """Storage backend that persists files in an S3-compatible object store."""

    def _get_client(self):
        kwargs = {
            "aws_access_key_id": settings.s3_access_key,
            "aws_secret_access_key": settings.s3_secret_key,
            "region_name": settings.s3_region,
        }
        if settings.s3_endpoint:
            kwargs["endpoint_url"] = settings.s3_endpoint

        return boto3.client("s3", **kwargs)

    async def store(self, path: str, file: BinaryIO, content_type: str) -> str:
        data = file.read() if hasattr(file, "read") else file
        client = self._get_client()

        def _upload():
            client.put_object(
                Bucket=settings.s3_bucket,
                Key=path,
                Body=data,
                ContentType=content_type,
            )

        await asyncio.to_thread(_upload)
        return path

    async def retrieve(self, path: str) -> BinaryIO:
        client = self._get_client()

        def _download():
            response = client.get_object(Bucket=settings.s3_bucket, Key=path)
            return response["Body"].read()

        data = await asyncio.to_thread(_download)
        return BytesIO(data)

    async def delete(self, path: str) -> bool:
        client = self._get_client()

        def _delete():
            try:
                client.delete_object(Bucket=settings.s3_bucket, Key=path)
                return True
            except ClientError:
                return False

        return await asyncio.to_thread(_delete)

    async def exists(self, path: str) -> bool:
        client = self._get_client()

        def _exists():
            try:
                client.head_object(Bucket=settings.s3_bucket, Key=path)
                return True
            except ClientError:
                return False

        return await asyncio.to_thread(_exists)

    async def get_url(self, path: str, expires: int = 3600) -> str:
        client = self._get_client()

        def _presign():
            return client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.s3_bucket, "Key": path},
                ExpiresIn=expires,
            )

        return await asyncio.to_thread(_presign)

    async def get_size(self, path: str) -> int:
        client = self._get_client()

        def _head():
            response = client.head_object(Bucket=settings.s3_bucket, Key=path)
            return response["ContentLength"]

        return await asyncio.to_thread(_head)
