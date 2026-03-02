# Module 4 - Connectors

## Implemented Connectors

- Jira
- Slack (token + OAuth flow)
- Email (IMAP/SMTP credentials)
- GitHub/GitLab
- Confluence
- SharePoint / Microsoft Graph
- DB Read-only
- Logs ingestion (folder pull)
- File upload (TXT/PDF/DOCX)

## Backend Delivery

### New connector tables

- `jira_connectors`
- `slack_connectors`
- `email_connectors`
- `code_repo_connectors`
- `confluence_connectors`
- `sharepoint_connectors`
- `db_connectors`
- `logs_connectors`
- `file_connectors`
- `connector_sync_runs`
- `connector_oauth_states`

Migration: `backend/alembic/versions/20260217_0004_connectors_module.py`

### Normalized document mapping

Document schema now carries:

- `source_type`
- `source_id`
- `url`
- `title`
- `author`
- `source_created_at`
- `source_updated_at`
- `raw_text`
- `metadata_json`

All connector sync services map provider payloads into these fields and bind default document ACL policy when present.

### API endpoints

Each connector has dedicated endpoints:

- `GET /api/v1/connectors/{connector}/config`
- `PUT /api/v1/connectors/{connector}/config`
- `POST /api/v1/connectors/{connector}/test`
- `POST /api/v1/connectors/{connector}/sync`
- `GET /api/v1/connectors/{connector}/status`

Slack OAuth endpoints:

- `GET /api/v1/connectors/slack/oauth/start`
- `GET /api/v1/connectors/slack/oauth/callback`

File upload ingestion endpoint:

- `POST /api/v1/connectors/file-upload/upload`

### Scheduling

Celery beat now schedules periodic sync tasks for Jira, Slack, Email, Code Repo, Confluence, SharePoint, DB, and Logs connectors.

## Frontend Delivery

Dedicated setup wizard pages (no generic connector page):

- `/connectors/jira`
- `/connectors/slack`
- `/connectors/email`
- `/connectors/code-repo`
- `/connectors/confluence`
- `/connectors/sharepoint`
- `/connectors/db`
- `/connectors/logs`
- `/connectors/file-upload`

Hub page:

- `/connectors`

Each page includes:

- credential/config form
- source selection form section
- test connection action
- run sync now action
- sync status panel with recent runs

## Tests

`backend/tests/test_connectors.py` validates:

- Jira end-to-end sync into documents
- Slack end-to-end sync into documents
- File upload ingestion end-to-end

## Config samples

JSON payload samples for every connector are in:

- `scripts/config_samples/`
