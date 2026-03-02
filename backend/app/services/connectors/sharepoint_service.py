from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret
from app.models.connectors.sharepoint_connector import SharePointConnector
from app.services.connectors.common import finish_sync_run, start_sync_run, upsert_document

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"


def _get_access_token(connector: SharePointConnector) -> str:
    secret = decrypt_secret(connector.client_secret_encrypted)
    token_url = f"https://login.microsoftonline.com/{connector.azure_tenant_id}/oauth2/v2.0/token"

    with httpx.Client(timeout=20) as client:
        response = client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": connector.client_id,
                "client_secret": secret,
                "scope": "https://graph.microsoft.com/.default",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.json()["access_token"]


def test_connection(connector: SharePointConnector) -> tuple[bool, str]:
    try:
        token = _get_access_token(connector)
        with httpx.Client(timeout=20) as client:
            response = client.get(
                f"{GRAPH_ROOT}/sites?search=*",
                headers={"Authorization": f"Bearer {token}"},
                params={"$top": 1},
            )
            response.raise_for_status()
        return True, "Connected to Microsoft Graph successfully"
    except Exception as exc:
        return False, f"SharePoint/Graph connection failed: {exc}"


def sync_connector(db: Session, connector: SharePointConnector) -> int:
    run = start_sync_run(db, connector.tenant_id, "sharepoint", connector.id)

    try:
        token = _get_access_token(connector)
        headers = {"Authorization": f"Bearer {token}"}
        count = 0

        with httpx.Client(timeout=30) as client:
            for drive_id in connector.drive_ids:
                response = client.get(f"{GRAPH_ROOT}/drives/{drive_id}/root/children", headers=headers)
                response.raise_for_status()
                items = response.json().get("value", [])

                for item in items:
                    upsert_document(
                        db,
                        tenant_id=connector.tenant_id,
                        source_type="sharepoint",
                        source_id=item.get("id", "unknown"),
                        url=(item.get("webUrl") or None),
                        title=item.get("name", "SharePoint item"),
                        author=((item.get("createdBy") or {}).get("user") or {}).get("displayName"),
                        source_created_at=datetime.now(timezone.utc),
                        source_updated_at=datetime.now(timezone.utc),
                        raw_text=f"SharePoint item: {item.get('name')} ({item.get('id')})",
                        metadata_json={"drive_id": drive_id, "item": item},
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
