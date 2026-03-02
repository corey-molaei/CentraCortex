# Module 5 - Document Store, Chunking, and Indexing

## Scope delivered

- Raw document persistence to MinIO with local fallback storage for non-container local/test runs.
- Chunking service with versioning (`current_chunk_version` on documents).
- `document_chunks` table with ACL metadata on each chunk.
- Per-tenant Qdrant indexing (`tenant_<tenant_id>` collection).
- Postgres BM25-compatible full-text index on chunk content.
- Reindex APIs (single and bulk).
- Delete/forget flow removing DB records, chunk records, Qdrant points, and raw blob.
- ACL enforcement in list/detail/hybrid search retrieval paths.

## Data model additions

Migration: `backend/alembic/versions/20260218_0005_document_store_chunking.py`

### `documents` updates

- `tags_json`
- `raw_object_key`
- `current_chunk_version`
- `indexed_at`
- `deleted_at`
- unique constraint on `(tenant_id, source_type, source_id)`

### New table: `document_chunks`

- Chunk identity + ordering (`chunk_index`, `chunk_version`)
- Content + token count
- Embedding data (`embedding_model`, `embedding_vector`)
- ACL binding (`acl_policy_id`)
- Source metadata (`metadata_json`)

## Backend APIs

### List/filter docs

- `GET /api/v1/documents`
- Filters: `source_type`, `tag`, `acl_policy_id`, `created_from`, `created_to`, `q`

### Document detail

- `GET /api/v1/documents/{document_id}`
- Includes metadata + latest-version chunk list

### Reindex

- `POST /api/v1/documents/{document_id}/reindex`
- `POST /api/v1/documents/reindex`

### Forget/delete

- `DELETE /api/v1/documents/{document_id}`

### Hybrid retrieval search

- `POST /api/v1/documents/search`
- Combines vector search (Qdrant) + BM25/LIKE scoring
- Applies ACL filtering before returning chunks

## Frontend pages

- `/documents`:
  - filters + document list
  - single/bulk reindex
  - forget action
  - hybrid search panel (ACL-enforced)
- `/documents/:documentId`:
  - metadata view
  - chunks view
  - reindex + forget actions

## ACL and tenant guardrails

- Cross-tenant indexing is rejected.
- Documents with explicit `acl_policy_id` enforce that exact policy (not wildcard fallback).
- Documents without explicit policy use default `document/*` policy if configured; otherwise tenant members can access.
- Retrieval/search output is always scoped by tenant and ACL.

## Tests

`backend/tests/test_documents.py` covers:

- Reindex and chunk version progression.
- ACL-filtered list/search behavior.
- Forget flow and chunk cleanup.
