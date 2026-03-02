from __future__ import annotations

import base64
from datetime import datetime, timezone
from urllib.parse import quote_plus

import httpx
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret
from app.models.connectors.code_repo_connector import CodeRepoConnector
from app.services.connectors.common import finish_sync_run, start_sync_run, upsert_document


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def test_connection(connector: CodeRepoConnector) -> tuple[bool, str]:
    token = decrypt_secret(connector.token_encrypted)
    base = connector.base_url.rstrip("/")
    url = f"{base}/user" if connector.provider == "github" else f"{base}/api/v4/user"

    try:
        with httpx.Client(timeout=20) as client:
            response = client.get(url, headers=_headers(token))
            response.raise_for_status()
        return True, "Connected to repository provider"
    except Exception as exc:
        return False, f"Repo connector test failed: {exc}"


def _github_sync(client: httpx.Client, connector: CodeRepoConnector, token: str, db: Session) -> int:
    count = 0
    base = connector.base_url.rstrip("/")
    headers = _headers(token)

    for repo in connector.repositories:
        if connector.include_readme:
            readme = client.get(f"{base}/repos/{repo}/readme", headers=headers)
            if readme.status_code == 200:
                payload = readme.json()
                content = payload.get("content", "")
                decoded = base64.b64decode(content).decode("utf-8", errors="ignore") if content else ""
                upsert_document(
                    db,
                    tenant_id=connector.tenant_id,
                    source_type="github",
                    source_id=f"{repo}:readme",
                    url=f"{base}/{repo}#readme",
                    title=f"{repo} README",
                    author=None,
                    source_created_at=datetime.now(timezone.utc),
                    source_updated_at=datetime.now(timezone.utc),
                    raw_text=decoded,
                    metadata_json={"repo": repo, "type": "readme"},
                )
                count += 1

        if connector.include_issues:
            issues = client.get(f"{base}/repos/{repo}/issues", headers=headers, params={"state": "all", "per_page": 50})
            if issues.status_code == 200:
                for issue in issues.json():
                    if "pull_request" in issue:
                        continue
                    upsert_document(
                        db,
                        tenant_id=connector.tenant_id,
                        source_type="github",
                        source_id=f"{repo}:issue:{issue['number']}",
                        url=issue.get("html_url"),
                        title=issue.get("title", f"Issue {issue['number']}"),
                        author=(issue.get("user") or {}).get("login"),
                        source_created_at=datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00")),
                        source_updated_at=datetime.fromisoformat(issue["updated_at"].replace("Z", "+00:00")),
                        raw_text=issue.get("body", ""),
                        metadata_json={"repo": repo, "issue": issue},
                    )
                    count += 1

        if connector.include_prs:
            prs = client.get(f"{base}/repos/{repo}/pulls", headers=headers, params={"state": "all", "per_page": 50})
            if prs.status_code == 200:
                for pr in prs.json():
                    upsert_document(
                        db,
                        tenant_id=connector.tenant_id,
                        source_type="github",
                        source_id=f"{repo}:pr:{pr['number']}",
                        url=pr.get("html_url"),
                        title=pr.get("title", f"PR {pr['number']}"),
                        author=(pr.get("user") or {}).get("login"),
                        source_created_at=datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00")),
                        source_updated_at=datetime.fromisoformat(pr["updated_at"].replace("Z", "+00:00")),
                        raw_text=pr.get("body", ""),
                        metadata_json={"repo": repo, "pr": pr},
                    )
                    count += 1

    return count


def _gitlab_sync(client: httpx.Client, connector: CodeRepoConnector, token: str, db: Session) -> int:
    count = 0
    base = connector.base_url.rstrip("/")
    headers = {"PRIVATE-TOKEN": token, "Accept": "application/json"}

    for repo in connector.repositories:
        encoded_repo = quote_plus(repo)
        if connector.include_issues:
            issues = client.get(f"{base}/api/v4/projects/{encoded_repo}/issues", headers=headers)
            if issues.status_code == 200:
                for issue in issues.json():
                    upsert_document(
                        db,
                        tenant_id=connector.tenant_id,
                        source_type="gitlab",
                        source_id=f"{repo}:issue:{issue['iid']}",
                        url=issue.get("web_url"),
                        title=issue.get("title", f"Issue {issue['iid']}"),
                        author=(issue.get("author") or {}).get("username"),
                        source_created_at=datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00")),
                        source_updated_at=datetime.fromisoformat(issue["updated_at"].replace("Z", "+00:00")),
                        raw_text=issue.get("description", ""),
                        metadata_json={"repo": repo, "issue": issue},
                    )
                    count += 1

    return count


def sync_connector(db: Session, connector: CodeRepoConnector) -> int:
    run = start_sync_run(db, connector.tenant_id, "code_repo", connector.id)

    try:
        token = decrypt_secret(connector.token_encrypted)
        with httpx.Client(timeout=30) as client:
            if connector.provider == "github":
                count = _github_sync(client, connector, token, db)
            else:
                count = _gitlab_sync(client, connector, token, db)

        connector.last_items_synced = count
        connector.last_error = None
        connector.last_sync_at = datetime.now(timezone.utc)
        db.commit()

        finish_sync_run(db, run, status="success", items_synced=count)
        return count
    except Exception as exc:
        connector.last_error = str(exc)
        db.commit()
        finish_sync_run(db, run, status="failed", items_synced=0, error_message=str(exc))
        raise
