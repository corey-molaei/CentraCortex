# Module 7 - Agent Runtime + Tools

## Scope delivered

- Multi-agent runtime with RouterAgent selecting one of: `knowledge`, `comms`, `ops`, `sql`, `guard`.
- LangGraph-ready orchestration path:
  - Uses LangGraph when installed.
  - Falls back to built-in deterministic orchestration when LangGraph is unavailable.
- Tool framework with per-tool schema validation and ACL enforcement.
- Risky tool approval workflow for `send_email`, `post_slack_message`, `run_script`, and `create_ticket`.
- Full execution trace persistence (route, tool call/result, approval steps) with redacted reasoning notes.
- Audit logging for catalog operations, run creation, and approval decisions.

## Backend delivery

### New tables

Migration: `backend/alembic/versions/20260218_0007_agent_runtime_tools.py`

- `agent_definitions`
- `agent_runs`
- `agent_trace_steps`
- `tool_approvals`

### New schemas

- `backend/app/schemas/agents.py`
  - catalog create/update/read schemas
  - run request/read schemas
  - trace and approval read schemas

### New service

- `backend/app/services/agent_runtime.py`
  - RouterAgent decisioning and orchestration
  - tool planning and validation
  - tool ACL enforcement (`policy_type = tool`)
  - approval queue and decision handling
  - trace serialization and run detail assembly

### New APIs

Router: `backend/app/routers/agents.py`

- `GET /api/v1/agents/catalog`
- `POST /api/v1/agents/catalog`
- `GET /api/v1/agents/catalog/{agent_id}`
- `PATCH /api/v1/agents/catalog/{agent_id}`
- `DELETE /api/v1/agents/catalog/{agent_id}`
- `POST /api/v1/agents/runs`
- `GET /api/v1/agents/runs`
- `GET /api/v1/agents/runs/{run_id}`
- `GET /api/v1/agents/approvals`
- `POST /api/v1/agents/approvals/{approval_id}/approve`
- `POST /api/v1/agents/approvals/{approval_id}/reject`

## Frontend delivery

### New pages

- `frontend/src/pages/AgentCatalogPage.tsx`
  - create/delete agent definitions
  - tool selection + runtime config
- `frontend/src/pages/RunAgentPage.tsx`
  - execute runs with tool input JSON
  - recent runs list with status
- `frontend/src/pages/AgentTracePage.tsx`
  - run summary
  - approvals queue with approve/reject actions
  - full trace timeline with input/output payloads

### New API/types

- `frontend/src/api/agents.ts`
- `frontend/src/types/agents.ts`

### Route wiring

- `frontend/src/App.tsx`
  - `/agents`
  - `/agents/run`
  - `/agents/runs/:runId`
- `frontend/src/pages/HomePage.tsx`
  - dashboard entry for Agents module

## Security and governance behavior

- Tool execution is blocked unless ACL policy allows the tool for the caller.
- Risky tools are blocked pending approval before execution.
- Approvals are tenant-admin-only actions.
- Guard route blocks exfiltration-like requests before tool execution.
- Trace records include redacted reasoning only (no unrestricted chain-of-thought).

## Tests

New backend integration tests: `backend/tests/test_agents.py`

- catalog + knowledge run with trace recording
- risky-tool approval flow (pending -> approved)
- ACL denial for disallowed user/tool combinations

CI status after Module 7 changes:

- backend: `18 passed`
- frontend: lint clean, tests passing
