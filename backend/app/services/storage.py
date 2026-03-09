from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import structlog
from google.api_core.exceptions import NotFound
from google.cloud import storage

from app.core.config import settings

logger = structlog.get_logger(__name__)


def _storage_backend() -> str:
    return (settings.storage_backend or "").strip().lower()


def _gcs_client() -> storage.Client:
    if settings.gcs_project_id:
        return storage.Client(project=settings.gcs_project_id)
    return storage.Client()


def _gcs_bucket() -> storage.Bucket:
    bucket_name = (settings.gcs_bucket_raw_documents or "").strip()
    if not bucket_name:
        raise ValueError("GCS_BUCKET_RAW_DOCUMENTS is required when STORAGE_BACKEND=gcs")
    return _gcs_client().bucket(bucket_name)


def _local_root() -> Path:
    root = Path(settings.raw_documents_local_path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _local_file_for_key(object_key: str) -> Path:
    path = _local_root() / object_key
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def ensure_raw_storage_ready() -> str:
    backend = _storage_backend()
    if backend == "local":
        _local_root()
        return "local"

    if backend != "gcs":
        raise ValueError("Unsupported STORAGE_BACKEND. Use 'gcs' or 'local'.")

    bucket = _gcs_bucket()
    if bucket.exists():
        return "gcs"

    if settings.gcs_auto_create_bucket:
        _gcs_client().create_bucket(bucket, location=settings.gcs_bucket_location)
        return "gcs"

    raise RuntimeError("Configured GCS bucket does not exist. Create it or enable GCS_AUTO_CREATE_BUCKET.")


def put_raw_document_blob(object_key: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, default=str).encode("utf-8")
    backend = ensure_raw_storage_ready()
    if backend == "local":
        local_path = _local_file_for_key(object_key)
        local_path.write_bytes(raw)
        return object_key

    # Use upload_from_file to avoid loading large content twice in memory.
    stream = io.BytesIO(raw)
    _gcs_bucket().blob(object_key).upload_from_file(stream, content_type="application/json")
    return object_key


def delete_raw_document_blob(object_key: str) -> None:
    if not object_key:
        return

    backend = _storage_backend()
    if backend == "local":
        local_path = _local_root() / object_key
        if local_path.exists():
            local_path.unlink()
        return

    if backend != "gcs":
        logger.warning("raw_storage_delete_unsupported_backend", backend=backend, object_key=object_key)
        return

    try:
        _gcs_bucket().blob(object_key).delete()
    except NotFound:
        return
