from __future__ import annotations

from io import BytesIO

import pytest
from sqlalchemy import select

from app.core.security import encrypt_secret, get_password_hash
from app.models.connector_sync_run import ConnectorSyncRun
from app.models.connectors.file_connector import FileConnector
from app.models.connectors.jira_connector import JiraConnector
from app.models.connectors.slack_connector import SlackConnector
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User
from app.services.connectors.jira_service import sync_connector as sync_jira
from app.services.connectors.slack_service import sync_connector as sync_slack


@pytest.fixture(autouse=True)
def mock_raw_blob_storage(monkeypatch):
    def _stub_blob_store(tenant_id: str, source_type: str, source_id: str, payload: dict) -> str:
        return f"{tenant_id}/{source_type}/{source_id}.json"

    monkeypatch.setattr("app.services.connectors.common.put_raw_document_blob", _stub_blob_store)


def _seed_admin(db_session):
    tenant = Tenant(name="Connector Tenant", slug="connector-tenant")
    admin = User(email="connect-admin@example.com", full_name="Connector Admin", hashed_password=get_password_hash("password123"))
    db_session.add_all([tenant, admin])
    db_session.flush()
    db_session.add(TenantMembership(user_id=admin.id, tenant_id=tenant.id, role="Owner", is_default=True))
    db_session.commit()
    return tenant, admin


def _login(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "connect-admin@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_jira_service_sync(db_session, monkeypatch):
    tenant, _ = _seed_admin(db_session)

    connector = JiraConnector(
        tenant_id=tenant.id,
        base_url="https://jira.example.com",
        email="jira@example.com",
        api_token_encrypted=encrypt_secret("token"),
        project_keys=["ENG"],
        issue_types=["Bug"],
        fields_mapping={},
    )
    db_session.add(connector)
    db_session.commit()

    class DummyResp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def get(self, url, headers=None, params=None):
            if url.endswith("/rest/api/3/search"):
                return DummyResp(
                    {
                        "issues": [
                            {
                                "id": "1001",
                                "key": "ENG-1",
                                "fields": {
                                    "summary": "Sync issue",
                                    "description": "Issue body",
                                    "created": "2026-02-10T12:00:00.000+0000",
                                    "updated": "2026-02-10T13:00:00.000+0000",
                                    "creator": {"displayName": "Alice"},
                                    "project": {"key": "ENG"},
                                    "status": {"name": "Open"},
                                    "priority": {"name": "High"},
                                    "comment": {"comments": [{"body": "A comment"}]},
                                },
                            }
                        ]
                    }
                )
            return DummyResp({"self": "ok"})

    monkeypatch.setattr("app.services.connectors.jira_service.httpx.Client", DummyClient)
    items = sync_jira(db_session, connector)

    assert items == 1
    docs = db_session.execute(select(Document).where(Document.tenant_id == tenant.id, Document.source_type == "jira")).scalars().all()
    assert len(docs) == 1
    assert docs[0].title == "Sync issue"


def test_slack_service_sync(db_session, monkeypatch):
    tenant, _ = _seed_admin(db_session)

    connector = SlackConnector(
        tenant_id=tenant.id,
        workspace_name="Acme",
        bot_token_encrypted=encrypt_secret("xoxb-test"),
        team_id="T123",
        channel_ids=["C123"],
        sync_cursor={},
    )
    db_session.add(connector)
    db_session.commit()

    class DummyResp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def get(self, url, headers=None, params=None):
            if "conversations.history" in url:
                return DummyResp(
                    {
                        "ok": True,
                        "messages": [
                            {
                                "ts": "1707600000.123",
                                "text": "Main message",
                                "user": "U1",
                                "thread_ts": "1707600000.123",
                                "reply_count": 1,
                            }
                        ],
                    }
                )
            if "conversations.replies" in url:
                return DummyResp({"ok": True, "messages": [{"text": "Main"}, {"text": "Reply"}]})
            return DummyResp({"ok": True})

    monkeypatch.setattr("app.services.connectors.slack_service.httpx.Client", DummyClient)
    items = sync_slack(db_session, connector)

    assert items == 1
    docs = db_session.execute(select(Document).where(Document.tenant_id == tenant.id, Document.source_type == "slack")).scalars().all()
    assert len(docs) == 1
    assert "Main message" in docs[0].raw_text


def test_file_upload_connector_route(client, db_session):
    tenant, _ = _seed_admin(db_session)
    db_session.add(FileConnector(tenant_id=tenant.id, allowed_extensions=["txt", "pdf", "docx"]))
    db_session.commit()

    token = _login(client)

    response = client.post(
        "/api/v1/connectors/file-upload/upload",
        headers={"Authorization": f"Bearer {token}"},
        files=[("files", ("notes.txt", b"hello from file upload", "text/plain"))],
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["items_synced"] == 1
    assert payload["indexing_queued"] is True

    docs = db_session.execute(
        select(Document).where(Document.tenant_id == tenant.id, Document.source_type == "file_upload")
    ).scalars().all()
    assert len(docs) == 1
    assert "hello from file upload" in docs[0].raw_text
    assert docs[0].index_status == "pending"
    assert docs[0].current_chunk_version == 0

    chunks = db_session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == docs[0].id, DocumentChunk.tenant_id == tenant.id)
    ).scalars().all()
    assert chunks == []


def test_file_upload_connector_rejects_disallowed_extension(client, db_session):
    tenant, _ = _seed_admin(db_session)
    db_session.add(FileConnector(tenant_id=tenant.id, allowed_extensions=["txt"]))
    db_session.commit()

    token = _login(client)
    response = client.post(
        "/api/v1/connectors/file-upload/upload",
        headers={"Authorization": f"Bearer {token}"},
        files=[("files", ("report.pdf", b"pdf bytes", "application/pdf"))],
    )
    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"]

    runs = db_session.execute(
        select(ConnectorSyncRun).where(
            ConnectorSyncRun.tenant_id == tenant.id,
            ConnectorSyncRun.connector_type == "file_upload",
        )
    ).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == "failed"


def test_file_upload_connector_ingests_xlsx(client, db_session):
    openpyxl = pytest.importorskip("openpyxl")
    tenant, _ = _seed_admin(db_session)
    db_session.add(FileConnector(tenant_id=tenant.id, allowed_extensions=["txt", "xlsx"]))
    db_session.commit()

    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Leads"
    worksheet.append(["Name", "Email"])
    worksheet.append(["Maryam Asadi", "maryam@example.com"])
    stream = BytesIO()
    workbook.save(stream)

    token = _login(client)
    response = client.post(
        "/api/v1/connectors/file-upload/upload",
        headers={"Authorization": f"Bearer {token}"},
        files=[
            (
                "files",
                (
                    "leads.xlsx",
                    stream.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            )
        ],
    )
    assert response.status_code == 200

    docs = db_session.execute(
        select(Document).where(Document.tenant_id == tenant.id, Document.source_type == "file_upload")
    ).scalars().all()
    assert len(docs) == 1
    assert "Maryam Asadi, maryam@example.com" in docs[0].raw_text


def test_file_upload_connector_ingests_doc_when_antiword_parses(client, db_session, monkeypatch):
    tenant, _ = _seed_admin(db_session)
    db_session.add(FileConnector(tenant_id=tenant.id, allowed_extensions=["doc"]))
    db_session.commit()

    def fake_run(*args, **kwargs):  # noqa: ARG001
        class Proc:
            returncode = 0
            stdout = "Legacy DOC content"
            stderr = ""

        return Proc()

    monkeypatch.setattr("app.services.connectors.file_text_extractor.subprocess.run", fake_run)

    token = _login(client)
    response = client.post(
        "/api/v1/connectors/file-upload/upload",
        headers={"Authorization": f"Bearer {token}"},
        files=[("files", ("legacy.doc", b"doc bytes", "application/msword"))],
    )
    assert response.status_code == 200

    docs = db_session.execute(
        select(Document).where(Document.tenant_id == tenant.id, Document.source_type == "file_upload")
    ).scalars().all()
    assert len(docs) == 1
    assert "Legacy DOC content" in docs[0].raw_text


def test_email_legacy_endpoints_return_gone(client, db_session):
    tenant, _ = _seed_admin(db_session)
    token = _login(client)

    for path, method in [
        ("/api/v1/connectors/email/config", "GET"),
        ("/api/v1/connectors/email/config", "PUT"),
        ("/api/v1/connectors/email/test", "POST"),
        ("/api/v1/connectors/email/sync", "POST"),
        ("/api/v1/connectors/email/status", "GET"),
    ]:
        if method == "GET":
            response = client.get(path, headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant.id})
        elif method == "PUT":
            response = client.put(path, headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant.id}, json={})
        else:
            response = client.post(path, headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant.id})
        assert response.status_code == 410
