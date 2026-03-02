# CentraCortex

Production-grade multi-tenant SaaS platform for secure enterprise knowledge retrieval and agent operations.

## Stack

- Backend: FastAPI, SQLAlchemy, Alembic, Celery, Redis, Postgres, Qdrant, MinIO
- Frontend: React + TypeScript + Tailwind
- Multi-tenant from day 1 with tenant-aware auth context and isolated access

## Quick Start

1. Copy environment template:

```bash
cp .env.example .env
```

2. Start everything:

```bash
docker compose up --build
```

3. Open services:

- API docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- UI: [http://localhost:5173](http://localhost:5173)
- MinIO console: [http://localhost:9001](http://localhost:9001)
- Qdrant: [http://localhost:6333](http://localhost:6333)

## Module Progress

- Module 0: Infrastructure + Foundation (implemented)
- Module 1: Auth + Tenant Isolation + Session (implemented)
- Module 2: RBAC + Groups + Fine-Grained ACL (implemented)
- Module 3: LLM Provider Management + Router Failover (implemented)
- Module 4: Connectors + Scheduled Sync + Ingestion (implemented)
- Module 5: Document Store + Chunking + Indexing (implemented)
- Module 6: Retrieval + Chat hardening (implemented)
- Module 7: Agent Runtime + Tools (implemented)
- Module 8: No-Code Agent Builder (implemented)
- Module 9: Audit + Governance + Security hardening (implemented)
- All requested modules are implemented; details remain in `docs/roadmap.md`.

## Scripts

- `scripts/create_tenant.py`
- `scripts/create_admin_user.py`
- `scripts/create_qdrant_collection.py`

## Testing and Lint

```bash
./scripts/ci.sh
```
