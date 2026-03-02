# Module 0 - Infrastructure + Foundation

## What is implemented

- Docker Compose stack with `api`, `worker`, `beat`, `postgres`, `redis`, `qdrant`, `minio`, `ui`
- Health checks for all services
- MinIO bootstrap bucket creation
- FastAPI OpenAPI docs (`/docs`, `/openapi.json`)
- Structured JSON logging with request IDs
- Basic CI workflow (`.github/workflows/ci.yml`) and local CI script (`scripts/ci.sh`)

## How to run

```bash
cp .env.example .env
docker compose up --build
```

## Validation

- API liveness: `GET /health/live`
- API readiness: `GET /health/ready`
- UI: `http://localhost:5173`
