"""Application settings.

Environment variable names are the field names uppercased, no prefix (`DATABASE_URL`,
`REDIS_URL`, `S3_BUCKET`, ...). `.env` is read only in `development`; in `staging`/
`production` configuration arrives exclusively via ConfigMap/Secret-injected environment
variables (addendum §4.3, §6.1).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings"]

_ENV_FILE = ".env" if os.environ.get("ENVIRONMENT") == "development" else None


class Settings(BaseSettings):
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"

    database_url: PostgresDsn
    redis_url: RedisDsn

    s3_endpoint_url: AnyHttpUrl | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str
    s3_access_key_id: SecretStr
    s3_secret_access_key: SecretStr
    s3_use_path_style: bool = True

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = []
    trusted_hosts: list[str] = []

    solver_default_timeout_seconds: int = 60
    solver_max_timeout_seconds: int = 600
    worker_concurrency: int = 1
    worker_metrics_port: int = 9100
    worker_heartbeat_path: str = "/tmp/worker-heartbeat"

    job_lock_ttl_seconds: int = 900
    export_retention_days: int = 7

    build_sha: str = "unknown"
    image_tag: str = "unknown"

    otel_exporter_otlp_endpoint: AnyHttpUrl | None = None

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_nested_delimiter="__",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
