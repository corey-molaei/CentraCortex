# Module 6 - Retrieval + Chat Hardening

## Scope delivered

- Hybrid retrieval integrated into chat responses:
  - Vector retrieval path (Qdrant)
  - BM25/LIKE retrieval path (Postgres/SQLite fallback)
  - Rank merge with ACL enforcement
- Citation-rich chat responses including document title/link/snippet and chunk metadata.
- Tenant-scoped conversation history persisted in database.
- Prompt injection and exfiltration safety filters with block behavior for high-risk requests.
- Answer reporting flow with audit logging.

## Backend delivery

### New tables

Migration: `backend/alembic/versions/20260218_0006_chat_retrieval_safety.py`

- `chat_conversations`
- `chat_messages`
- `chat_feedback`

### New services

- `backend/app/services/chat_runtime.py`
  - Conversation create/load
  - Message persistence
  - Safety analysis (prompt injection + exfiltration)
  - Retrieval-augmented prompt context
  - Feedback creation
- `backend/app/services/document_indexing.py` (updated)
  - Better SQLite BM25 fallback tokenization for local/test retrieval behavior

### Updated APIs

- `POST /api/v1/chat/complete`
  - accepts `conversation_id` + `retrieval_limit`
  - returns conversation ids, safety flags, and citations
- `GET /api/v1/chat/conversations`
- `GET /api/v1/chat/conversations/{conversation_id}`
- `POST /api/v1/chat/conversations/{conversation_id}/messages/{message_id}/report`

## Frontend delivery

Updated chat workspace: `frontend/src/pages/ChatPage.tsx`

- Model indicator panel
- Conversation history sidebar
- Main chat transcript area
- Citation panel
- View Sources drawer
- Report Answer action

## Safety behavior

- Prompt injection indicators are flagged and logged.
- Exfiltration-like prompts are blocked before LLM execution and return guard response.
- Safety flags are persisted on chat messages for traceability.

## Tests

Updated tests in `backend/tests/test_llm.py` cover:

- provider failover response path
- citation-backed chat + conversation history + report flow
- blocked exfiltration prompt behavior
