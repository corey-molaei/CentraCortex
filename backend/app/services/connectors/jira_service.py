from __future__ import annotations

import base64
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret
from app.models.connectors.jira_connector import JiraConnector
from app.services.connectors.common import finish_sync_run, start_sync_run, upsert_document


def _parse_jira_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None


def _jira_auth_header(email: str, api_token: str) -> dict[str, str]:
    basic = base64.b64encode(f"{email}:{api_token}".encode()).decode()
    return {"Authorization": f"Basic {basic}", "Accept": "application/json"}


def test_connection(connector: JiraConnector) -> tuple[bool, str]:
    token = decrypt_secret(connector.api_token_encrypted)
    headers = _jira_auth_header(connector.email, token)
    url = f"{connector.base_url.rstrip('/')}/rest/api/3/myself"

    try:
        with httpx.Client(timeout=20) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
        return True, "Connected to Jira successfully"
    except Exception as exc:
        return False, f"Jira connection failed: {exc}"


def sync_connector(db: Session, connector: JiraConnector) -> int:
    run = start_sync_run(db, connector.tenant_id, "jira", connector.id)
    token = decrypt_secret(connector.api_token_encrypted)
    headers = _jira_auth_header(connector.email, token)

    try:
        base = connector.base_url.rstrip("/")
        latest_updated = connector.sync_cursor.get("updated")
        jql_parts: list[str] = []

        if connector.project_keys:
            projects = ",".join(f"\"{p}\"" for p in connector.project_keys)
            jql_parts.append(f"project in ({projects})")
        if connector.issue_types:
            issue_types = ",".join(f"\"{it}\"" for it in connector.issue_types)
            jql_parts.append(f"issuetype in ({issue_types})")
        if latest_updated:
            jql_parts.append(f"updated >= '{latest_updated}'")

        jql_parts.append("order by updated asc")
        jql = " AND ".join(jql_parts)

        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{base}/rest/api/3/search",
                headers=headers,
                params={"jql": jql, "maxResults": 50},
            )
            resp.raise_for_status()
            issues = resp.json().get("issues", [])

        count = 0
        max_updated = latest_updated

        for issue in issues:
            fields = issue.get("fields", {})
            comments = fields.get("comment", {}).get("comments", [])
            comment_text = "\n".join(str(c.get("body", "")) for c in comments)

            summary = fields.get("summary", "")
            description = fields.get("description", "")
            raw_text = f"Summary: {summary}\nDescription: {description}\nComments:\n{comment_text}".strip()

            updated = fields.get("updated")
            if updated and (max_updated is None or updated > max_updated):
                max_updated = updated

            upsert_document(
                db,
                tenant_id=connector.tenant_id,
                source_type="jira",
                source_id=issue.get("key", issue.get("id", "unknown")),
                url=f"{base}/browse/{issue.get('key', '')}",
                title=summary or issue.get("key", "Jira Item"),
                author=(fields.get("creator") or {}).get("displayName"),
                source_created_at=_parse_jira_datetime(fields.get("created")),
                source_updated_at=_parse_jira_datetime(updated),
                raw_text=raw_text,
                metadata_json={
                    "issue_id": issue.get("id"),
                    "issue_key": issue.get("key"),
                    "project": (fields.get("project") or {}).get("key"),
                    "status": (fields.get("status") or {}).get("name"),
                    "priority": (fields.get("priority") or {}).get("name"),
                    "raw": issue,
                },
            )
            count += 1

        connector.sync_cursor = {"updated": max_updated} if max_updated else connector.sync_cursor
        connector.last_items_synced = count
        connector.last_error = None
        connector.last_sync_at = datetime.now().astimezone()
        db.commit()

        finish_sync_run(db, run, status="success", items_synced=count)
        return count
    except Exception as exc:
        connector.last_error = str(exc)
        db.commit()
        finish_sync_run(db, run, status="failed", items_synced=0, error_message=str(exc))
        raise
