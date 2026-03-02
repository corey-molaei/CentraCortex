from __future__ import annotations

import base64
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret
from app.models.connectors.confluence_connector import ConfluenceConnector
from app.services.connectors.common import finish_sync_run, start_sync_run, upsert_document


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "")


def _headers(email: str, token: str) -> dict[str, str]:
    basic = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {"Authorization": f"Basic {basic}", "Accept": "application/json"}


def test_connection(connector: ConfluenceConnector) -> tuple[bool, str]:
    token = decrypt_secret(connector.api_token_encrypted)
    url = f"{connector.base_url.rstrip('/')}/wiki/rest/api/space"

    try:
        with httpx.Client(timeout=20) as client:
            response = client.get(url, headers=_headers(connector.email, token), params={"limit": 1})
            response.raise_for_status()
        return True, "Connected to Confluence successfully"
    except Exception as exc:
        return False, f"Confluence connection failed: {exc}"


def sync_connector(db: Session, connector: ConfluenceConnector) -> int:
    run = start_sync_run(db, connector.tenant_id, "confluence", connector.id)

    try:
        token = decrypt_secret(connector.api_token_encrypted)
        base = connector.base_url.rstrip("/")
        count = 0

        with httpx.Client(timeout=30) as client:
            for space_key in connector.space_keys:
                response = client.get(
                    f"{base}/wiki/rest/api/content",
                    headers=_headers(connector.email, token),
                    params={"type": "page", "spaceKey": space_key, "limit": 50, "expand": "body.storage,version,history"},
                )
                response.raise_for_status()
                pages = response.json().get("results", [])

                for page in pages:
                    html = (((page.get("body") or {}).get("storage") or {}).get("value") or "")
                    content_text = _strip_html(html)
                    title = page.get("title", "Confluence Page")
                    page_id = page.get("id", "unknown")

                    upsert_document(
                        db,
                        tenant_id=connector.tenant_id,
                        source_type="confluence",
                        source_id=page_id,
                        url=f"{base}/wiki{(page.get('_links') or {}).get('webui', '')}",
                        title=title,
                        author=((page.get("history") or {}).get("createdBy") or {}).get("displayName"),
                        source_created_at=datetime.now(timezone.utc),
                        source_updated_at=datetime.now(timezone.utc),
                        raw_text=content_text,
                        metadata_json={"space_key": space_key, "page": page},
                    )
                    count += 1

        connector.last_sync_at = datetime.now(timezone.utc)
        connector.last_items_synced = count
        connector.last_error = None
        db.commit()

        finish_sync_run(db, run, status="success", items_synced=count)
        return count
    except Exception as exc:
        connector.last_error = str(exc)
        db.commit()
        finish_sync_run(db, run, status="failed", items_synced=0, error_message=str(exc))
        raise
