from fastapi import APIRouter
from minio import Minio
from qdrant_client import QdrantClient
from redis import Redis
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict:
    status = {"database": False, "redis": False, "qdrant": False, "minio": False}

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    status["database"] = True

    if settings.skip_external_healthchecks:
        return {"status": "ok", "checks": status}

    redis_client = Redis.from_url(settings.redis_url)
    redis_client.ping()
    status["redis"] = True

    qdrant = QdrantClient(url=settings.qdrant_url)
    qdrant.get_collections()
    status["qdrant"] = True

    minio_client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    minio_client.bucket_exists(settings.minio_bucket_raw_documents)
    status["minio"] = True

    return {"status": "ok", "checks": status}
