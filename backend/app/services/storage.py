from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import structlog
from minio import Minio

from app.core.config import settings

logger = structlog.get_logger(__name__)


def _minio_client() -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def _local_root() -> Path:
    root = Path(settings.raw_documents_local_path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _local_file_for_key(object_key: str) -> Path:
    path = _local_root() / object_key
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def ensure_raw_storage_ready() -> str:
    try:
        client = _minio_client()
        if not client.bucket_exists(settings.minio_bucket_raw_documents):
            client.make_bucket(settings.minio_bucket_raw_documents)
        return "minio"
    except Exception as exc:  # pragma: no cover - network-dependent path
        logger.warning("minio_unavailable_using_local_storage", error=str(exc))
        _local_root()
        return "local"


def put_raw_document_blob(object_key: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, default=str).encode("utf-8")
    stream = io.BytesIO(raw)

    try:
        ensure_raw_storage_ready()
        client = _minio_client()
        client.put_object(
            bucket_name=settings.minio_bucket_raw_documents,
            object_name=object_key,
            data=stream,
            length=len(raw),
            content_type="application/json",
        )
        return object_key
    except Exception as exc:  # pragma: no cover - fallback path validated via integration behavior
        logger.warning("minio_store_failed_fallback_local", error=str(exc), object_key=object_key)
        local_path = _local_file_for_key(object_key)
        local_path.write_bytes(raw)
        return object_key


def delete_raw_document_blob(object_key: str) -> None:
    if not object_key:
        return

    try:
        client = _minio_client()
        client.remove_object(settings.minio_bucket_raw_documents, object_key)
        return
    except Exception as exc:  # pragma: no cover - fallback path validated via integration behavior
        logger.warning("minio_delete_failed_try_local", error=str(exc), object_key=object_key)

    local_path = _local_root() / object_key
    if local_path.exists():
        local_path.unlink()
