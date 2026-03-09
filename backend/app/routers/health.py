from fastapi import APIRouter
from qdrant_client import QdrantClient
from redis import Redis
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.services.storage import ensure_raw_storage_ready

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict:
    status = {"database": False, "redis": False, "qdrant": False, "storage": False}

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    status["database"] = True

    if settings.skip_external_healthchecks:
        return {"status": "ok", "checks": status}

    redis_client = Redis.from_url(settings.redis_url)
    redis_client.ping()
    status["redis"] = True

    qdrant = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=settings.qdrant_timeout_seconds,
    )
    qdrant.get_collections()
    status["qdrant"] = True

    ensure_raw_storage_ready()
    status["storage"] = True

    return {"status": "ok", "checks": status}
