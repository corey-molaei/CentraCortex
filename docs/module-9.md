# Module 9 - Audit, Governance, and Security Hardening

## Scope delivered

- Tenant-scoped audit log viewer with filters for user, event type, tool, and time range.
- CSV export endpoint for audit logs.
- Governance approval queue for risky tool actions (approve/reject).
- API rate-limiting middleware.
- Optional request-signing middleware (HMAC timestamped signatures).
- Security response headers including CSP.
- Dedicated secrets-management guidance.

## Backend delivery

### New schemas/services/router

- `backend/app/schemas/governance.py`
- `backend/app/services/governance.py`
- `backend/app/routers/governance.py`

### New middleware

- `backend/app/middleware/rate_limit.py`
- `backend/app/middleware/request_signing.py`
- `backend/app/middleware/security_headers.py`

### Configuration additions

In `backend/app/core/config.py` and `.env.example`:

- `SECURITY_HEADERS_ENABLED`
- `CSP_POLICY`
- `RATE_LIMIT_ENABLED`
- `RATE_LIMIT_PER_MINUTE`
- `REQUEST_SIGNING_ENABLED`
- `REQUEST_SIGNING_SECRET`
- `REQUEST_SIGNING_MAX_AGE_SECONDS`

### New governance APIs

- `GET /api/v1/governance/audit-logs`
- `GET /api/v1/governance/audit-logs/export`
- `GET /api/v1/governance/approval-queue`
- `POST /api/v1/governance/approval-queue/{approval_id}/approve`
- `POST /api/v1/governance/approval-queue/{approval_id}/reject`

## Frontend delivery

### New page/API/types

- `frontend/src/pages/GovernancePage.tsx`
- `frontend/src/api/governance.ts`
- `frontend/src/types/governance.ts`

### Route wiring

- `frontend/src/App.tsx`: `/governance`
- `frontend/src/pages/HomePage.tsx`: Governance dashboard entry

### UI capabilities

- filterable audit table
- export CSV button
- approval queue with approve/reject actions

## Tests

New integration tests in `backend/tests/test_governance_security.py` cover:

- audit log filtering and CSV export
- governance approval queue approval flow
- rate-limit enforcement (`429`)
- request-signing enforcement (`401` unsigned, success when signed)

## Security guidance document

- `docs/security-secrets.md`

## CI status after Module 9

- backend: `22 passed`
- frontend: lint clean, tests passing
