# Configuration Map

This document maps runtime configuration for CentraCortex, including:

- `.env` variables
- feature flags
- hidden toggles and implicit behavior switches
- tenant-level configuration surfaces
- AI model configuration
- full Vector + BM25 RAG query parameter map

## 1. Environment Variables (`.env` / `.env.example`)

Source of truth:

- `backend/app/core/config.py`
- `frontend/src/api/*.ts` (for `VITE_API_BASE_URL`)
- `.env.example`

### 1.1 App and Security

| Variable | Default | Used by | Notes |
|---|---:|---|---|
| `APP_NAME` | `CentraCortex` | Backend app metadata | Display/application name |
| `APP_ENV` | `development` | Backend runtime | Environment mode |
| `API_HOST` | `0.0.0.0` | Uvicorn runtime | API bind host |
| `API_PORT` | `8000` | Uvicorn runtime | API bind port |
| `API_BASE_URL` | `http://localhost:8000` | Backend + generated links | External API URL |
| `UI_BASE_URL` | `http://localhost:5173` | Backend + docs/links | External UI URL |
| `LOG_LEVEL` | `INFO` | Backend logging | Logging threshold |
| `REQUEST_ID_HEADER` | `X-Request-ID` | Middleware/audit | Correlation header name |
| `SECURITY_HEADERS_ENABLED` | `true` | API middleware | Enables security headers |
| `CSP_POLICY` | default CSP string | API middleware | Full CSP text |
| `RATE_LIMIT_ENABLED` | `true` | API middleware | Global request rate limit switch |
| `RATE_LIMIT_PER_MINUTE` | `240` | API middleware | Per-minute request cap |
| `REQUEST_SIGNING_ENABLED` | `false` | Security middleware | Enables request signature checks |
| `REQUEST_SIGNING_SECRET` | `change-me-signing-secret` | Security middleware | Signature secret |
| `REQUEST_SIGNING_MAX_AGE_SECONDS` | `300` | Security middleware | Signature freshness window |
| `SECRET_KEY` | `change-me` | JWT/security | Signing key |
| `ENCRYPTION_KEY` | `change-me-32-byte-base64-key` | Secret at-rest encryption | Encrypt/decrypt connector/API secrets |
| `ALGORITHM` | `HS256` | JWT/security | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Auth | Access token TTL |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `14` | Auth | Refresh token TTL |
| `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES` | `30` | Auth | Password reset token TTL |
| `SKIP_EXTERNAL_HEALTHCHECKS` | `false` | Health endpoints | Skips external dependency checks when true |

### 1.2 Data, Queue, and Storage

| Variable | Default | Used by | Notes |
|---|---:|---|---|
| `POSTGRES_HOST` | `postgres` | DB config | Postgres host |
| `POSTGRES_PORT` | `5432` | DB config | Postgres port |
| `POSTGRES_DB` | `centracortex` | DB config | Database name |
| `POSTGRES_USER` | `centracortex` | DB config | DB username |
| `POSTGRES_PASSWORD` | `centracortex` | DB config | DB password |
| `DATABASE_URL` | `postgresql+psycopg2://...` | SQLAlchemy engine | Primary DB DSN |
| `REDIS_URL` | `redis://redis:6379/0` | App cache/queue | Redis endpoint |
| `CELERY_BROKER_URL` | `redis://redis:6379/1` | Celery | Broker DSN |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/2` | Celery | Result backend DSN |
| `QDRANT_URL` | `http://qdrant:6333` | Vector retrieval | Qdrant endpoint |
| `QDRANT_TIMEOUT_SECONDS` | `5.0` | Vector retrieval | Qdrant client timeout |
| `STORAGE_BACKEND` | `local` | Raw document storage | `local` or `gcs` |
| `GCS_PROJECT_ID` | empty | GCS client | Optional explicit project id |
| `GCS_BUCKET_RAW_DOCUMENTS` | `centracortex-raw-documents` | Document ingestion | GCS bucket for raw files |
| `GCS_BUCKET_LOCATION` | `australia-southeast1` | GCS bucket create path | Used when auto-creating bucket |
| `GCS_AUTO_CREATE_BUCKET` | `false` | GCS startup behavior | Auto-create bucket when missing |
| `RAW_DOCUMENTS_LOCAL_PATH` | `/tmp/centracortex-raw-documents` | Local storage backend | Raw document local path |

### 1.3 Retrieval / Chunking / RAG

| Variable | Default | Used by | Notes |
|---|---:|---|---|
| `EMBEDDING_DIMENSION` | `384` | Embedding + Qdrant collection schema | Size of embedding vector |
| `CHUNK_SIZE_CHARS` | `1200` | Chunker | Max char window per chunk |
| `CHUNK_OVERLAP_CHARS` | `150` | Chunker | Chunk overlap |
| `RETRIEVAL_MIN_HYBRID_SCORE` | `0.25` | Chat citation relevance filter | Score threshold for usable hits |
| `RETRIEVAL_MIN_TOKEN_OVERLAP` | `1` | Chat citation relevance filter | Minimum query-token overlap with chunk content |
| `RETRIEVAL_MAX_CITATIONS` | `5` | Chat citation relevance filter | Upper bound on returned citations |

### 1.4 Connector OAuth

| Variable | Default | Used by | Notes |
|---|---:|---|---|
| `SLACK_CLIENT_ID` | empty | Slack OAuth flow | Optional |
| `SLACK_CLIENT_SECRET` | empty | Slack OAuth flow | Optional |

### 1.5 Frontend

| Variable | Default | Used by | Notes |
|---|---:|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | Frontend API clients | Base URL for all browser API calls |

### 1.6 Present in `.env.example` but not primary backend settings keys

| Variable | Default | Notes |
|---|---:|---|
| `REDIS_HOST` | `redis` | Informational in template; backend reads `REDIS_URL` |
| `REDIS_PORT` | `6379` | Informational in template; backend reads `REDIS_URL` |
| `QDRANT_HOST` | `qdrant` | Informational in template; backend reads `QDRANT_URL` |
| `QDRANT_PORT` | `6333` | Informational in template; backend reads `QDRANT_URL` |

## 2. Feature Flags

### 2.1 Global runtime flags (env-driven)

- `SECURITY_HEADERS_ENABLED`
- `RATE_LIMIT_ENABLED`
- `REQUEST_SIGNING_ENABLED`
- `SKIP_EXTERNAL_HEALTHCHECKS`

### 2.2 Tenant runtime flags (DB-driven)

Connector `enabled` flags per tenant (one row per connector type):

- `slack_connectors.enabled`
- `jira_connectors.enabled`
- `email_connectors.enabled`
- `code_repo_connectors.enabled`
- `confluence_connectors.enabled`
- `sharepoint_connectors.enabled`
- `db_connectors.enabled`
- `logs_connectors.enabled`
- `file_connectors.enabled`

AI routing behavior flags per provider:

- `llm_providers.is_default`
- `llm_providers.is_fallback`

Document indexing flags/state:

- `documents.index_status` (`pending|indexed|retry|failed`)
- `documents.index_attempts`
- `documents.next_index_attempt_at`

## 3. Hidden Toggles / Implicit Behavior Switches

These are behavior controls not obvious in UI:

- **DB dialect switch for lexical retrieval** in `document_indexing._bm25_chunks(...)`
  - PostgreSQL: true FTS (`to_tsvector`, `plainto_tsquery`, `ts_rank_cd`)
  - Non-PostgreSQL: `LIKE` token fallback scoring
- **Hybrid merge weights** in `document_indexing.hybrid_search_chunks(...)`
  - lexical contribution: `0.45`
  - vector contribution: `0.55`
- **Retrieval widening before merge**
  - lexical stage receives `limit * 3`
  - vector stage receives `limit * 3`
- **Tokenization floor**
  - lexical token regex: `[a-z0-9_]+`
  - minimum token length: `>=3` (for fallback lexical and citation overlap checks)
- **Citation snippet truncation**
  - snippet length fixed to first `320` chars
- **Provider selection fallback**
  - if no explicit override and no default provider, first provider by `created_at` is used
- **Per-provider rate-limit gate**
  - lookback window is last 1 minute
  - threshold equals `llm_providers.rate_limit_rpm`

## 4. Tenant Configuration Map

### 4.1 Core tenant context

- `tenants`: `name`, `slug`, `is_active`
- `tenant_memberships`: `role`, `is_default` (default tenant for user)
- Requests are tenant-scoped by `X-Tenant-ID` header and membership checks.

### 4.2 Tenant AI model config

Model: `llm_providers`

- identity: `id`, `tenant_id`, `name`
- provider routing: `provider_type`, `base_url`, `model_name`, `is_default`, `is_fallback`, `rate_limit_rpm`
- secret/config payload: `api_key_encrypted`, `config_json`
- timestamps: `created_at`, `updated_at`

### 4.3 Tenant connector config

Each connector has one tenant-unique row and common operational fields:

- `sync_cursor`
- `enabled`
- `last_sync_at`
- `last_items_synced`
- `last_error`

Connector-specific credential/source fields:

- Slack: `workspace_name`, `bot_token_encrypted`, `team_id`, `channel_ids`
- Jira: `base_url`, `email`, `api_token_encrypted`, `project_keys`, `issue_types`, `fields_mapping`
- Email: `imap_host`, `imap_port`, `smtp_host`, `smtp_port`, `username`, `password_encrypted`, `use_ssl`, `folders`
- Code repo: `provider`, `base_url`, `token_encrypted`, `repositories`, include toggles (`include_readme`, `include_issues`, `include_prs`, `include_wiki`)
- Confluence: `base_url`, `email`, `api_token_encrypted`, `space_keys`
- SharePoint: `azure_tenant_id`, `client_id`, `client_secret_encrypted`, `site_ids`, `drive_ids`
- DB: `connection_uri_encrypted`, `table_allowlist`
- Logs: `folder_path`, `file_glob`, `parser_type`
- File upload: `allowed_extensions`

### 4.4 Tenant document + ACL config

- `documents`: source metadata + indexing state + ACL policy link
- `document_chunks`: chunk text, chunk version/index, embedding vector, metadata
- `acl_policies`: document access rules by user/group/role

## 5. Vector + BM25 RAG Query Configuration (Complete Map)

Source files:

- `backend/app/services/document_indexing.py`
- `backend/app/services/chat_runtime.py`
- `backend/app/schemas/llm.py`
- `backend/app/schemas/documents.py`
- `backend/app/services/acl.py`

### 5.1 API entry parameters

#### Chat RAG request (`POST /api/v1/chat/complete`)

- `messages[]` (required)
- `temperature` (default `0.2`)
- `provider_id_override` (optional)
- `conversation_id` (optional)
- `retrieval_limit` (default `6`, range `1..20`)

#### Direct chunk search (`POST /api/v1/documents/search`)

- `query` (required, length `2..300`)
- `limit` (default `8`, range `1..50`)

### 5.2 Runtime function parameters and derived variables

#### `hybrid_search_chunks(db, tenant_id, user_id, query, limit)`

- input params:
  - `tenant_id`
  - `user_id`
  - `query`
  - `limit`
- derived:
  - `accessible_docs` via ACL evaluation
  - `accessible_doc_ids` (documents visible to user)
  - lexical candidate limit = `limit * 3`
  - vector candidate limit = `limit * 3`

#### Lexical stage (`_bm25_chunks`)

- branch control: `db.get_bind().dialect.name`
- PostgreSQL branch:
  - `vector = to_tsvector('english', content)`
  - `ts_query = plainto_tsquery('english', query)`
  - filter: `vector @@ ts_query`
  - score: `ts_rank_cd(vector, ts_query)`
  - ranker label: `"bm25"`
- Non-PostgreSQL branch:
  - tokens from regex `[a-z0-9_]+`, min length `>=3`
  - if empty tokens fallback to stripped query
  - condition: case-insensitive `LIKE` on chunk content
  - score: token occurrence count sum (minimum forced `1.0`)
  - ranker label: `"like"`

#### Vector stage (`_vector_chunks`)

- embedding: `embed_text(query)` (hash-based embedding)
- Qdrant search params:
  - collection per tenant (`tenant_<tenant_id>`)
  - query vector length = `EMBEDDING_DIMENSION`
  - limit = `limit * 3`
- returned score:
  - uses Qdrant similarity score (`hit.score`)
  - ranker label: `"vector"`

#### Hybrid merge (`hybrid_search_chunks`)

- weights:
  - lexical weighted score = `lexical_score * 0.45`
  - vector weighted score = `vector_score * 0.55`
- same chunk in both stages:
  - scores are added
  - ranker updated to `"hybrid"`
- final:
  - sorted descending by combined score
  - returned top `limit`

### 5.3 Chat citation relevance gate (post-retrieval)

In `chat_runtime.run_chat(...)`, after hybrid retrieval:

- `_filter_retrieval_hits(query, hits)` keeps only hits satisfying both:
  - `hit.score >= RETRIEVAL_MIN_HYBRID_SCORE` (default `0.25`)
  - token overlap count with query >= `RETRIEVAL_MIN_TOKEN_OVERLAP` (default `1`)
    - tokenization regex `[a-z0-9_]+`, min token length `>=3`
- citation cap:
  - `max_citations = min(retrieval_limit, RETRIEVAL_MAX_CITATIONS)` (default max `5`)
- only filtered/capped hits are converted into `citations[]`.
- if none survive filter:
  - context text becomes: `"No relevant retrieval context was found."`
  - returned citations are `[]`

### 5.4 Additional RAG-related constants and behavior

- document chunk snippet used in citations/search results: `chunk.content[:320]`
- current chunk version only is considered in retrieval
- deleted documents are excluded
- ACL is enforced before retrieval (`get_accessible_documents`)

## 6. AI Model Config Surface (API + DB)

### 6.1 API payload fields

Create/update fields (from `LLMProviderCreate` / `LLMProviderUpdate`):

- `name`
- `provider_type` (`openai|vllm|ollama|other`)
- `base_url`
- `api_key` (optional)
- `model_name`
- `is_default`
- `is_fallback`
- `rate_limit_rpm` (`1..10000`)
- `config_json` (provider-specific arbitrary map)

### 6.2 Runtime AI behavior controls

- provider override support (`provider_id_override`)
- default + fallback selection strategy
- provider-specific call adapters:
  - OpenAI-compatible: `POST /v1/chat/completions`
  - Ollama: `POST /api/chat`
- per-provider per-tenant rate limiting from call logs

## 7. Change Management Notes

If you adjust retrieval quality, review these first:

- `RETRIEVAL_MIN_HYBRID_SCORE`
- `RETRIEVAL_MIN_TOKEN_OVERLAP`
- `RETRIEVAL_MAX_CITATIONS`
- hybrid merge weights in `hybrid_search_chunks(...)`
- lexical branch behavior (PostgreSQL BM25 vs fallback LIKE)

If you adjust tenant behavior, verify:

- `X-Tenant-ID` handling
- membership role/default tenant
- ACL policy resolution defaults
- connector `enabled` states and sync cursors
