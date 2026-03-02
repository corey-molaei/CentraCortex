# Module 1 - Auth + Tenant Isolation + Session

## What is implemented

### Backend

- JWT auth with access + refresh tokens
- Tenant-aware session context in access token (`tenant_id` claim)
- Tenant switch endpoint
- Password reset request + confirm flow
- OIDC-ready provider interface contract
- DB schema and Alembic migration for:
  - `users`
  - `tenants`
  - `tenant_memberships`
  - `refresh_tokens`
  - `password_reset_tokens`
  - `audit_logs`
- Audit events for login, refresh, switch tenant, password reset

### API endpoints

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/switch-tenant`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/password-reset/request`
- `POST /api/v1/auth/password-reset/confirm`
- `GET /api/v1/tenants/mine`
- `GET /api/v1/tenants/current`
- `GET /api/v1/users/me`
- `PATCH /api/v1/users/me`

### Tenant enforcement

- Protected tenant endpoints require tenant context via access token claim or `X-Tenant-ID` header.
- Membership is verified before allowing access.

### Tests

- Login + me + tenant switch flow
- Refresh token flow
- Password reset flow
- Health endpoints

## Seed and bootstrap scripts

```bash
./scripts/create_tenant.py --name "Acme" --slug acme
./scripts/create_admin_user.py --email admin@acme.com --password password123 --tenant-slug acme
./scripts/create_qdrant_collection.py --tenant-id <tenant_uuid>
```
