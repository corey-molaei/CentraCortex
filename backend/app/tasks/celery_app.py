from celery import Celery
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.connectors.code_repo_connector import CodeRepoConnector
from app.models.connectors.confluence_connector import ConfluenceConnector
from app.models.connectors.db_connector import DBConnector
from app.models.connectors.email_user_connector import EmailUserConnector
from app.models.connectors.google_user_connector import GoogleUserConnector
from app.models.connectors.jira_connector import JiraConnector
from app.models.connectors.logs_connector import LogsConnector
from app.models.connectors.sharepoint_connector import SharePointConnector
from app.models.connectors.slack_connector import SlackConnector
from app.models.document import Document
from app.models.workspace_google_integration import WorkspaceGoogleIntegration
from app.services.audit import audit_event
from app.services.connectors.code_repo_service import sync_connector as sync_code_repo
from app.services.connectors.confluence_service import sync_connector as sync_confluence
from app.services.connectors.db_service import sync_connector as sync_db
from app.services.connectors.email_user_service import sync_connector as sync_email
from app.services.connectors.google_service import sync_connector as sync_google
from app.services.connectors.google_workspace_service import sync_connector as sync_workspace_google
from app.services.connectors.jira_service import sync_connector as sync_jira
from app.services.connectors.logs_service import sync_connector as sync_logs
from app.services.connectors.sharepoint_service import sync_connector as sync_sharepoint
from app.services.connectors.slack_service import sync_connector as sync_slack
from app.services.document_indexing import index_pending_documents as process_pending_documents
from app.services.orchestration.langgraph_runtime import cleanup_expired_checkpoints

celery_app = Celery(
    "centracortex",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "platform-health-ping": {
            "task": "app.tasks.celery_app.platform_health_ping",
            "schedule": 300.0,
        },
        "sync-jira": {
            "task": "app.tasks.celery_app.sync_jira_connectors",
            "schedule": 600.0,
        },
        "sync-slack": {
            "task": "app.tasks.celery_app.sync_slack_connectors",
            "schedule": 600.0,
        },
        "sync-email": {
            "task": "app.tasks.celery_app.sync_email_connectors",
            "schedule": 900.0,
        },
        "sync-google": {
            "task": "app.tasks.celery_app.sync_google_connectors",
            "schedule": 900.0,
        },
        "sync-google-workspace": {
            "task": "app.tasks.celery_app.sync_google_workspace_integrations",
            "schedule": 900.0,
        },
        "sync-code-repo": {
            "task": "app.tasks.celery_app.sync_code_repo_connectors",
            "schedule": 900.0,
        },
        "sync-confluence": {
            "task": "app.tasks.celery_app.sync_confluence_connectors",
            "schedule": 900.0,
        },
        "sync-sharepoint": {
            "task": "app.tasks.celery_app.sync_sharepoint_connectors",
            "schedule": 1200.0,
        },
        "sync-db": {
            "task": "app.tasks.celery_app.sync_db_connectors",
            "schedule": 1200.0,
        },
        "sync-logs": {
            "task": "app.tasks.celery_app.sync_logs_connectors",
            "schedule": 300.0,
        },
        "index-pending-documents": {
            "task": "app.tasks.celery_app.index_pending_documents",
            "schedule": 15.0,
        },
        "cleanup-langgraph-checkpoints": {
            "task": "app.tasks.celery_app.cleanup_langgraph_checkpoints",
            "schedule": 3600.0,
        },
    },
)


@celery_app.task(name="app.tasks.celery_app.platform_health_ping")
def platform_health_ping() -> dict[str, str]:
    return {"status": "ok"}


def _run_for_enabled(model, sync_fn) -> dict[str, int]:
    success = 0
    failed = 0

    with SessionLocal() as db:
        connectors = db.query(model).filter(model.enabled.is_(True)).all()
        for connector in connectors:
            try:
                sync_fn(db, connector)
                success += 1
            except Exception:
                failed += 1
    return {"success": success, "failed": failed}


@celery_app.task(name="app.tasks.celery_app.sync_jira_connectors")
def sync_jira_connectors() -> dict[str, int]:
    return _run_for_enabled(JiraConnector, sync_jira)


@celery_app.task(name="app.tasks.celery_app.sync_slack_connectors")
def sync_slack_connectors() -> dict[str, int]:
    return _run_for_enabled(SlackConnector, sync_slack)


@celery_app.task(name="app.tasks.celery_app.sync_email_connectors")
def sync_email_connectors() -> dict[str, int]:
    return _run_for_enabled(EmailUserConnector, sync_email)


@celery_app.task(name="app.tasks.celery_app.sync_google_connectors")
def sync_google_connectors() -> dict[str, int]:
    if not settings.google_client_id or not settings.google_client_secret:
        return {"success": 0, "failed": 0}
    return _run_for_enabled(
        GoogleUserConnector,
        lambda db, connector: sync_google(
            db,
            connector,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
        ),
    )


@celery_app.task(name="app.tasks.celery_app.sync_google_workspace_integrations")
def sync_google_workspace_integrations() -> dict[str, int]:
    if not settings.google_client_id or not settings.google_client_secret:
        return {"success": 0, "failed": 0}
    return _run_for_enabled(
        WorkspaceGoogleIntegration,
        lambda db, connector: sync_workspace_google(
            db,
            connector,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
        ),
    )


@celery_app.task(name="app.tasks.celery_app.sync_code_repo_connectors")
def sync_code_repo_connectors() -> dict[str, int]:
    return _run_for_enabled(CodeRepoConnector, sync_code_repo)


@celery_app.task(name="app.tasks.celery_app.sync_confluence_connectors")
def sync_confluence_connectors() -> dict[str, int]:
    return _run_for_enabled(ConfluenceConnector, sync_confluence)


@celery_app.task(name="app.tasks.celery_app.sync_sharepoint_connectors")
def sync_sharepoint_connectors() -> dict[str, int]:
    return _run_for_enabled(SharePointConnector, sync_sharepoint)


@celery_app.task(name="app.tasks.celery_app.sync_db_connectors")
def sync_db_connectors() -> dict[str, int]:
    return _run_for_enabled(DBConnector, sync_db)


@celery_app.task(name="app.tasks.celery_app.sync_logs_connectors")
def sync_logs_connectors() -> dict[str, int]:
    return _run_for_enabled(LogsConnector, sync_logs)


@celery_app.task(name="app.tasks.celery_app.index_pending_documents")
def index_pending_documents() -> dict[str, int]:
    with SessionLocal() as db:
        summary = process_pending_documents(
            db,
            batch_size=100,
            max_retries=5,
            backoff_base_seconds=15,
            max_backoff_seconds=900,
        )

        indexed_ids = list(summary.get("indexed_document_ids", []))
        retry_ids = list(summary.get("retry_document_ids", []))
        failed_ids = list(summary.get("failed_document_ids", []))
        all_ids = indexed_ids + retry_ids + failed_ids
        docs_by_id = {
            doc.id: doc
            for doc in db.execute(select(Document).where(Document.id.in_(all_ids))).scalars().all()
        } if all_ids else {}

        for doc_id in indexed_ids:
            doc = docs_by_id.get(doc_id)
            if doc:
                audit_event(
                    db,
                    event_type="document.index.auto_success",
                    resource_type="document",
                    action="auto_index",
                    tenant_id=doc.tenant_id,
                    resource_id=doc.id,
                )
        for doc_id in retry_ids:
            doc = docs_by_id.get(doc_id)
            if doc:
                audit_event(
                    db,
                    event_type="document.index.auto_retry",
                    resource_type="document",
                    action="auto_index_retry",
                    tenant_id=doc.tenant_id,
                    resource_id=doc.id,
                    payload={"index_attempts": doc.index_attempts, "index_error": doc.index_error},
                )
        for doc_id in failed_ids:
            doc = docs_by_id.get(doc_id)
            if doc:
                audit_event(
                    db,
                    event_type="document.index.auto_failed",
                    resource_type="document",
                    action="auto_index_failed",
                    tenant_id=doc.tenant_id,
                    resource_id=doc.id,
                    payload={"index_attempts": doc.index_attempts, "index_error": doc.index_error},
                )

        return {
            "processed": int(summary["processed"]),
            "indexed": int(summary["indexed"]),
            "retry": int(summary["retry"]),
            "failed": int(summary["failed"]),
        }


@celery_app.task(name="app.tasks.celery_app.cleanup_langgraph_checkpoints")
def cleanup_langgraph_checkpoints() -> dict[str, int]:
    with SessionLocal() as db:
        deleted = cleanup_expired_checkpoints(db)
    return {"deleted": deleted}
