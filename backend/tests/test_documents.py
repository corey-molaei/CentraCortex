from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User
from app.services.connectors.common import upsert_document
from app.services.document_indexing import index_pending_documents


def _seed_users(db_session):
    tenant = Tenant(name="Docs Tenant", slug="docs-tenant")
    admin = User(email="docs-owner@example.com", full_name="Docs Owner", hashed_password=get_password_hash("password123"))
    analyst = User(email="docs-analyst@example.com", full_name="Docs Analyst", hashed_password=get_password_hash("password123"))
    db_session.add_all([tenant, admin, analyst])
    db_session.flush()
    db_session.add_all(
        [
            TenantMembership(user_id=admin.id, tenant_id=tenant.id, role="Owner", is_default=True),
            TenantMembership(user_id=analyst.id, tenant_id=tenant.id, role="User", is_default=True),
        ]
    )
    db_session.commit()
    return tenant, admin, analyst


def _login(client, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_document_reindex_and_versioning(client, db_session):
    tenant, _, _ = _seed_users(db_session)
    admin_token = _login(client, "docs-owner@example.com")

    created = client.post(
        "/api/v1/retrieval/documents",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "source_type": "manual",
            "source_id": "doc-v1",
            "title": "Quarterly Plan",
            "raw_text": "initial content for module five indexing",
        },
    )
    assert created.status_code == 200
    document_id = created.json()["id"]

    reindex_one = client.post(
        f"/api/v1/documents/{document_id}/reindex",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert reindex_one.status_code == 200
    assert reindex_one.json()["indexed_documents"] == 1
    assert reindex_one.json()["indexed_chunks"] >= 1

    detail_one = client.get(
        f"/api/v1/documents/{document_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert detail_one.status_code == 200
    assert detail_one.json()["current_chunk_version"] == 1
    assert detail_one.json()["index_status"] == "indexed"
    assert detail_one.json()["index_error"] is None
    assert detail_one.json()["index_attempts"] == 0

    doc = db_session.execute(select(Document).where(Document.id == document_id, Document.tenant_id == tenant.id)).scalar_one()
    doc.raw_text = "updated content should produce the next chunk version"
    db_session.commit()

    reindex_two = client.post(
        f"/api/v1/documents/{document_id}/reindex",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert reindex_two.status_code == 200

    detail_two = client.get(
        f"/api/v1/documents/{document_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert detail_two.status_code == 200
    assert detail_two.json()["current_chunk_version"] == 2
    assert all(chunk["chunk_version"] == 2 for chunk in detail_two.json()["chunks"])
    assert detail_two.json()["index_status"] == "indexed"
    assert detail_two.json()["index_error"] is None
    assert detail_two.json()["index_attempts"] == 0


def test_auto_index_pending_documents(db_session):
    tenant, _, _ = _seed_users(db_session)
    doc = upsert_document(
        db_session,
        tenant_id=tenant.id,
        source_type="manual",
        source_id="pending-doc",
        url=None,
        title="Pending Index",
        author="system",
        raw_text="alpha beta gamma delta epsilon",
        metadata_json={},
    )

    assert doc.index_status == "pending"
    assert doc.current_chunk_version == 0
    chunks_before = db_session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == doc.id, DocumentChunk.tenant_id == tenant.id)
    ).scalars().all()
    assert chunks_before == []

    summary = index_pending_documents(db_session, batch_size=100, max_retries=5)
    assert summary["processed"] == 1
    assert summary["indexed"] == 1
    assert summary["retry"] == 0
    assert summary["failed"] == 0

    updated = db_session.execute(
        select(Document).where(Document.id == doc.id, Document.tenant_id == tenant.id)
    ).scalar_one()
    assert updated.index_status == "indexed"
    assert updated.index_error is None
    assert updated.index_attempts == 0
    assert updated.current_chunk_version >= 1

    chunks_after = db_session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == doc.id, DocumentChunk.tenant_id == tenant.id)
    ).scalars().all()
    assert len(chunks_after) >= 1


def test_auto_index_retry_then_failed(db_session, monkeypatch):
    tenant, _, _ = _seed_users(db_session)
    doc = upsert_document(
        db_session,
        tenant_id=tenant.id,
        source_type="manual",
        source_id="retry-doc",
        url=None,
        title="Retry Index",
        author="system",
        raw_text="content to index",
        metadata_json={},
    )

    def _always_fail(*args, **kwargs):
        raise RuntimeError("forced index failure")

    monkeypatch.setattr("app.services.document_indexing.index_document", _always_fail)

    first = index_pending_documents(db_session, batch_size=100, max_retries=2, backoff_base_seconds=1, max_backoff_seconds=60)
    assert first["processed"] == 1
    assert first["retry"] == 1
    assert first["failed"] == 0

    after_first = db_session.execute(
        select(Document).where(Document.id == doc.id, Document.tenant_id == tenant.id)
    ).scalar_one()
    assert after_first.index_status == "retry"
    assert after_first.index_attempts == 1
    assert after_first.index_error == "forced index failure"
    after_first.next_index_attempt_at = after_first.index_requested_at
    db_session.commit()

    second = index_pending_documents(db_session, batch_size=100, max_retries=2, backoff_base_seconds=1, max_backoff_seconds=60)
    assert second["processed"] == 1
    assert second["retry"] == 0
    assert second["failed"] == 1

    after_second = db_session.execute(
        select(Document).where(Document.id == doc.id, Document.tenant_id == tenant.id)
    ).scalar_one()
    assert after_second.index_status == "failed"
    assert after_second.index_attempts == 2
    assert after_second.index_error == "forced index failure"
    assert after_second.next_index_attempt_at is None


def test_connector_document_update_resets_index_state(db_session):
    tenant, _, _ = _seed_users(db_session)
    doc = upsert_document(
        db_session,
        tenant_id=tenant.id,
        source_type="manual",
        source_id="same-source",
        url=None,
        title="Version 1",
        author="system",
        raw_text="original",
        metadata_json={},
    )
    doc.index_status = "failed"
    doc.index_error = "old failure"
    doc.index_attempts = 4
    db_session.commit()

    updated = upsert_document(
        db_session,
        tenant_id=tenant.id,
        source_type="manual",
        source_id="same-source",
        url=None,
        title="Version 2",
        author="system",
        raw_text="updated",
        metadata_json={},
    )
    assert updated.id == doc.id
    assert updated.index_status == "pending"
    assert updated.index_error is None
    assert updated.index_attempts == 0
    assert updated.next_index_attempt_at is not None


def test_manual_reindex_clears_failed_state(client, db_session):
    tenant, _, _ = _seed_users(db_session)
    admin_token = _login(client, "docs-owner@example.com")
    created = client.post(
        "/api/v1/retrieval/documents",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "source_type": "manual",
            "source_id": "manual-reindex",
            "title": "Manual Reindex",
            "raw_text": "index me now",
        },
    )
    assert created.status_code == 200
    document_id = created.json()["id"]

    doc = db_session.execute(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant.id)
    ).scalar_one()
    doc.index_status = "failed"
    doc.index_error = "temporary index outage"
    doc.index_attempts = 5
    db_session.commit()

    response = client.post(
        f"/api/v1/documents/{document_id}/reindex",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200

    updated = db_session.execute(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant.id)
    ).scalar_one()
    assert updated.index_status == "indexed"
    assert updated.index_error is None
    assert updated.index_attempts == 0
    assert updated.next_index_attempt_at is None


def test_acl_filtered_search_and_forget_flow(client, db_session):
    tenant, _, analyst = _seed_users(db_session)
    admin_token = _login(client, "docs-owner@example.com")
    analyst_token = _login(client, "docs-analyst@example.com")

    group = client.post(
        "/api/v1/admin/groups",
        json={"name": "Research", "description": "Research group"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert group.status_code == 200
    group_id = group.json()["id"]

    add_group = client.post(
        f"/api/v1/admin/users/{analyst.id}/groups",
        json={"group_id": group_id},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert add_group.status_code == 200

    default_doc_policy = client.post(
        "/api/v1/admin/policies",
        json={
            "name": "Research Default Docs",
            "policy_type": "document",
            "resource_id": "*",
            "allow_all": False,
            "allowed_user_ids": [],
            "allowed_group_ids": [group_id],
            "allowed_role_names": [],
            "active": True,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert default_doc_policy.status_code == 200

    restricted_policy = client.post(
        "/api/v1/admin/policies",
        json={
            "name": "Owner Restricted Docs",
            "policy_type": "document",
            "resource_id": "restricted-doc-policy",
            "allow_all": False,
            "allowed_user_ids": [],
            "allowed_group_ids": [],
            "allowed_role_names": ["Owner"],
            "active": True,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert restricted_policy.status_code == 200
    restricted_policy_id = restricted_policy.json()["id"]

    open_doc = client.post(
        "/api/v1/retrieval/documents",
        json={
            "source_type": "manual",
            "source_id": "public-doc",
            "title": "Public Research Memo",
            "raw_text": "public finding alpha beta gamma",
            "acl_policy_id": None,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert open_doc.status_code == 200
    open_doc_id = open_doc.json()["id"]

    restricted_doc = client.post(
        "/api/v1/retrieval/documents",
        json={
            "source_type": "manual",
            "source_id": "private-doc",
            "title": "Private Owner Notes",
            "raw_text": "confidential merger playbook",
            "acl_policy_id": restricted_policy_id,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert restricted_doc.status_code == 200

    bulk_reindex = client.post("/api/v1/documents/reindex", json={"document_ids": []}, headers={"Authorization": f"Bearer {admin_token}"})
    assert bulk_reindex.status_code == 200
    assert bulk_reindex.json()["indexed_documents"] >= 2

    analyst_docs = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {analyst_token}"})
    assert analyst_docs.status_code == 200
    assert len(analyst_docs.json()) == 1
    assert analyst_docs.json()[0]["id"] == open_doc_id

    analyst_search = client.post(
        "/api/v1/documents/search",
        json={"query": "confidential", "limit": 10},
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert analyst_search.status_code == 200
    assert analyst_search.json()["results"] == []

    admin_search = client.post(
        "/api/v1/documents/search",
        json={"query": "confidential", "limit": 10},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_search.status_code == 200
    assert len(admin_search.json()["results"]) >= 1

    forget = client.delete(f"/api/v1/documents/{open_doc_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert forget.status_code == 200

    deleted_doc = db_session.execute(
        select(Document).where(Document.id == open_doc_id, Document.tenant_id == tenant.id)
    ).scalar_one_or_none()
    assert deleted_doc is None

    deleted_chunks = (
        db_session.execute(select(DocumentChunk).where(DocumentChunk.document_id == open_doc_id, DocumentChunk.tenant_id == tenant.id))
        .scalars()
        .all()
    )
    assert deleted_chunks == []
