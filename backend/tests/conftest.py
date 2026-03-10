import os

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["APP_ENV"] = "development"
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["SKIP_EXTERNAL_HEALTHCHECKS"] = "true"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ENCRYPTION_KEY"] = "dGVzdC1rZXktZm9yLWZlcm5ldC10ZXN0LXNlY3JldA=="

from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def local_qdrant_for_tests(monkeypatch, tmp_path):
    from app.services import document_indexing

    client = QdrantClient(path=str(tmp_path / "qdrant"))
    monkeypatch.setattr(document_indexing, "_qdrant_client", lambda: client)
    try:
        yield
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
