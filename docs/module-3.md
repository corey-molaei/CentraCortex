# Module 3 - LLM Provider Management

## Implemented Scope

### Data model + migration

Added `20260217_0003_llm_provider_management` with:

- `llm_providers` (tenant-scoped provider configs, encrypted API keys)
- `llm_call_logs` (usage/cost/status telemetry)

### Backend features

- Provider CRUD API under `Tenant Settings / AI`
- Connection testing endpoint per provider
- Default + fallback provider selection
- Per-provider rate limit enforcement (RPM)
- LLM router service with failover
- Token/cost metadata logging (when available)
- Chat completion endpoint using tenant default or explicit provider override

### API endpoints

- `GET /api/v1/tenant-settings/ai/providers`
- `POST /api/v1/tenant-settings/ai/providers`
- `PATCH /api/v1/tenant-settings/ai/providers/{provider_id}`
- `DELETE /api/v1/tenant-settings/ai/providers/{provider_id}`
- `POST /api/v1/tenant-settings/ai/providers/{provider_id}/test`
- `GET /api/v1/tenant-settings/ai/logs`
- `POST /api/v1/chat/complete`

### UI pages

- `/settings/ai-models`
  - add provider
  - mark default/fallback
  - test connection
- `/chat`
  - model/provider indicator
  - provider override selector
  - answer + token/cost stats

### Tests

`backend/tests/test_llm.py` covers:

- provider CRUD flow
- failover behavior when primary provider fails
