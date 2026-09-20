"""Boto3 S3 / MinIO storage helpers.

A single module-level client is built lazily on first use so importing this
module is free of side effects. All blocking boto3 calls run inside
:func:`asyncio.to_thread` so the worker's event loop stays responsive.

Object key layout: ``projects/{project_id}/exports/{export_id}.{ext}``.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.config import Config as BotoConfig  # type: ignore[import-untyped]

from app.settings import get_settings

S3Client = Any

__all__ = [
    "build_export_key",
    "delete",
    "get_object_bytes",
    "put_object",
]


_client: S3Client | None = None
_client_lock = asyncio.Lock()


def _build_client() -> S3Client:
    """Build (or return the cached) boto3 S3 client."""
    global _client
    if _client is not None:
        return _client
    settings = get_settings()
    addressing = "path" if settings.s3_use_path_style else "auto"
    _client = boto3.client(
        "s3",
        endpoint_url=str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        config=BotoConfig(s3={"addressing_style": addressing}),
    )
    return _client


def build_export_key(project_id: str, export_id: str, ext: str) -> str:
    """Compose the canonical S3 key for an export artefact."""
    return f"projects/{project_id}/exports/{export_id}.{ext}"


async def put_object(key: str, body: bytes, content_type: str) -> tuple[int, str]:
    """Upload ``body`` to ``key``; return ``(size_bytes, sha256)``.

    The body is hashed in the worker thread so large blobs don't pin the loop.
    """

    def _upload() -> tuple[int, str]:
        client = _build_client()
        digest = hashlib.sha256(body).hexdigest()
        client.put_object(
            Bucket=get_settings().s3_bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )
        return len(body), digest

    return await asyncio.to_thread(_upload)


async def get_object_bytes(key: str, *, fallback_ct: str | None = None) -> tuple[bytes, str]:
    """Fetch an object's bytes and content-type from S3."""

    def _download() -> tuple[bytes, str]:
        client = _build_client()
        response = client.get_object(Bucket=get_settings().s3_bucket, Key=key)
        body = response["Body"].read()
        content_type = response.get("ContentType") or (fallback_ct or "application/octet-stream")
        return body, content_type

    return await asyncio.to_thread(_download)


async def delete(key: str) -> None:
    """Best-effort delete; silently swallows NoSuchKey."""

    def _delete() -> None:
        client = _build_client()
        client.delete_object(Bucket=get_settings().s3_bucket, Key=key)

    try:
        await asyncio.to_thread(_delete)
    except Exception:
        return None
