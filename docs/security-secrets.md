# Secrets Management Guidelines

CentraCortex stores and processes sensitive secrets for connectors, model providers, and optional request signing.

## Rules

1. Do not hardcode secrets in source code or committed `.env` files.
2. Rotate all API keys and signing secrets on a fixed schedule and after incidents.
3. Use distinct secrets per environment (dev/stage/prod) and per tenant integration when possible.
4. Restrict operator access to secret values; prefer write-only workflows in admin UIs.
5. Log secret metadata (who changed, when) but never secret plaintext.

## Storage model in this repository

- Connector and provider credentials are encrypted at rest via application encryption key.
- Optional request-signing secret is loaded from runtime environment.
- Password hashes use PBKDF2 (`pbkdf2_sha256`).

## Recommended production setup

1. Store runtime secrets in a dedicated secrets manager (Vault, AWS Secrets Manager, GCP Secret Manager, Azure Key Vault).
2. Inject secrets at runtime via environment or mounted files.
3. Restrict DB backups and object storage backups with encryption and access controls.
4. Keep audit exports in secured buckets with retention and legal hold policies where required.

## Environment variables to protect

- `SECRET_KEY`
- `ENCRYPTION_KEY`
- `REQUEST_SIGNING_SECRET`
- All connector and model provider API tokens
