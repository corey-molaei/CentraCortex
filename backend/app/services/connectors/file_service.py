from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.connectors.file_connector import FileConnector
from app.services.connectors.common import ensure_bucket, upsert_document

try:
    from docx import Document as DocxDocument
except Exception:  # pragma: no cover
    DocxDocument = None

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


def _extract_text(extension: str, content: bytes) -> str:
    ext = extension.lower()
    if ext == "txt":
        return content.decode("utf-8", errors="ignore")
    if ext == "pdf":
        if PdfReader is None:
            raise ValueError("PDF support requires optional dependency 'pypdf'")
        reader = PdfReader(BytesIO(content))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if ext == "docx":
        if DocxDocument is None:
            raise ValueError("DOCX support requires optional dependency 'python-docx'")
        doc = DocxDocument(BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs)
    raise ValueError(f"Unsupported extension: {ext}")


def test_connection() -> tuple[bool, str]:
    try:
        backend = ensure_bucket()
        return True, f"File connector ready; {backend.upper()} raw storage is accessible"
    except Exception as exc:
        return False, f"File connector test failed: {exc}"


def ingest_file(db: Session, connector: FileConnector, *, filename: str, content: bytes, content_type: str | None = None) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    allowed = set(connector.allowed_extensions or [])
    if suffix not in allowed:
        raise ValueError(f"Extension '{suffix}' is not allowed")

    text = _extract_text(suffix, content)
    source_id = f"{filename}:{int(datetime.now(timezone.utc).timestamp())}"

    doc = upsert_document(
        db,
        tenant_id=connector.tenant_id,
        source_type="file_upload",
        source_id=source_id,
        url=None,
        title=filename,
        author="file-upload",
        source_created_at=datetime.now(timezone.utc),
        source_updated_at=datetime.now(timezone.utc),
        raw_text=text,
        metadata_json={
            "filename": filename,
            "content_type": content_type,
            "size_bytes": len(content),
        },
    )

    connector.last_sync_at = datetime.now(timezone.utc)
    connector.last_items_synced = (connector.last_items_synced or 0) + 1
    connector.last_error = None
    db.commit()
    return doc.id
